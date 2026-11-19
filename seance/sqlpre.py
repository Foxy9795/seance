"""Precompiler for embedded SQL (EXEC SQL ... END-EXEC), the job DB2's precompiler does, targeting SQLite.

Every EXEC SQL becomes plain COBOL: the statement is replaced, on the same lines, by a PERFORM of a generated
paragraph (appended at the end of the program) plus any WHENEVER tests, so no line of the program moves.
The generated paragraph moves host variables to text, CALLs 'SQLBRIDGE' and moves the results back. Because the
output is ordinary COBOL, GnuCOBOL compiles it and Séance's translator turns the same code into Python; both call
an SQLBRIDGE with the same rules (C on the COBOL side, Python on the other), on the same SQLite database.

Handled: INCLUDE (SQLCA and DCLGEN members), DECLARE TABLE (gives the schema), BEGIN/END DECLARE SECTION,
SELECT ... INTO, INSERT, UPDATE, DELETE (searched and WHERE CURRENT OF), DECLARE CURSOR, OPEN, FETCH, CLOSE,
COMMIT, ROLLBACK, WHENEVER SQLERROR / SQLWARNING / NOT FOUND, CONNECT and SET (accepted, do nothing), host
variables with indicators (:HV:IND, :HV INDICATOR :IND), qualified host variables (:REC.FIELD) and VARCHAR
(49-level length/text pairs). DB2 spellings rewritten for SQLite: CURRENT DATE/TIME/TIMESTAMP (the fixed run
clock), FETCH FIRST n ROWS ONLY, WITH UR/CS/RS/RR, FOR FETCH/READ ONLY, FOR UPDATE OF, VALUE(.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import detect_fixed

FIXED_DATE, FIXED_TIME = "2026-10-31", "23:59:58"
_EXEC = re.compile(r"EXEC\s+SQL\b(.*?)\bEND-EXEC(\s*\.)?", re.I | re.S)

SQLCA_COPY = """      * SQLCA and the work area of Seance's SQL bridge (generated).
       01  SQLCA.
           05  SQLCAID        PIC X(8).
           05  SQLCABC        PIC S9(9) COMP-5.
           05  SQLCODE        PIC S9(9) COMP-5.
           05  SQLERRM.
               10  SQLERRML   PIC S9(4) COMP-5.
               10  SQLERRMC   PIC X(70).
           05  SQLERRP        PIC X(8).
           05  SQLERRD        PIC S9(9) COMP-5 OCCURS 6 TIMES.
           05  SQLWARN.
               10  SQLWARN0   PIC X.
               10  SQLWARN1   PIC X.
               10  SQLWARN2   PIC X.
               10  SQLWARN3   PIC X.
               10  SQLWARN4   PIC X.
               10  SQLWARN5   PIC X.
               10  SQLWARN6   PIC X.
               10  SQLWARN7   PIC X.
               10  SQLWARN8   PIC X.
               10  SQLWARN9   PIC X.
               10  SQLWARNA   PIC X.
           05  SQLSTATE       PIC X(5).
       01  SQB-OP             PIC X(8).
       01  SQB-CURSOR         PIC X(30).
       01  SQB-TEXT           PIC X(4000).
       01  SQB-NPARAM         PIC 9(4).
       01  SQB-PARAMS.
           05  SQB-PARAM      PIC X(256) OCCURS 64 TIMES.
       01  SQB-PNULLS.
           05  SQB-PNULL      PIC X OCCURS 64 TIMES.
       01  SQB-NRES           PIC 9(4).
       01  SQB-RESULTS.
           05  SQB-RES        PIC X(256) OCCURS 64 TIMES.
       01  SQB-RNULLS.
           05  SQB-RNULL      PIC X OCCURS 64 TIMES.
       01  SQB-RLENS.
           05  SQB-RLEN       PIC 9(4) OCCURS 64 TIMES.
""" + "".join(f"       01  SQB-ED{s}            PIC -(19)9{('.9(' + str(s) + ')') if s else ''}.\n" for s in range(10))


class SqlError(ValueError):
    pass


@dataclass
class HostVar:
    name: str  # COBOL reference (FIELD OF REC for :REC.FIELD)
    indicator: str | None = None


@dataclass
class Table:
    name: str
    columns: list[tuple[str, str, bool]]  # (name, type text, not null)

    def ddl(self) -> str:
        cols = []
        for name, typ, nn in self.columns:
            t = typ.upper()
            aff = ("INTEGER" if re.match(r"(SMALLINT|INTEGER|INT|BIGINT)\b", t) else
                   "NUMERIC" if re.match(r"(DECIMAL|DEC|NUMERIC)\b", t) else
                   "REAL" if re.match(r"(FLOAT|DOUBLE|REAL)\b", t) else "TEXT")
            cols.append(f'"{name}" {aff}{" NOT NULL" if nn else ""}')
        return f'CREATE TABLE "{self.name}" ({", ".join(cols)});'


@dataclass
class Result:
    tables: dict[str, Table] = field(default_factory=dict)
    statements: int = 0
    notes: list[str] = field(default_factory=list)


def has_sql(text: str) -> bool:
    return bool(re.search(r"\bEXEC\s+SQL\b", text, re.I))


def _code_text(text: str, fixed: bool) -> str:
    """Comments removed (they must not be read as SQL); columns kept so offsets stay valid."""
    out = []
    for line in text.split("\n"):
        if fixed and len(line) > 6 and line[6] in "*/":
            out.append(" " * len(line))
        elif not fixed and line.lstrip().startswith("*>"):
            out.append(" " * len(line))
        elif fixed and len(line) > 72:
            out.append(line[:72] + " " * (len(line) - 72))
        else:
            out.append(line)
    return "\n".join(out)


def _declare_table(body: str) -> Table:
    m = re.match(r"\s*DECLARE\s+([A-Z0-9_.$#@-]+)\s+TABLE\s*\((.*)\)\s*$", body, re.I | re.S)
    if not m:
        raise SqlError(f"cannot read DECLARE TABLE: {body.strip()[:60]}")
    name = m.group(1).split(".")[-1].upper()
    cols, depth, cur = [], 0, ""
    for ch in m.group(2):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            cols.append(cur)
            cur = ""
        else:
            cur += ch
    cols.append(cur)
    out = []
    for c in cols:
        parts = c.split()
        if not parts:
            continue
        out.append((parts[0].upper(), " ".join(parts[1:]), bool(re.search(r"NOT\s+NULL", c, re.I))))
    return Table(name, out)


def _strip_strings(sql: str) -> list[tuple[bool, str]]:
    """Split SQL into (is_string, text) pieces so rewrites never touch quoted literals."""
    pieces, i = [], 0
    while i < len(sql):
        if sql[i] == "'":
            j = i + 1
            while j < len(sql):
                if sql[j] == "'" and (j + 1 >= len(sql) or sql[j + 1] != "'"):
                    break
                j += 2 if sql[j] == "'" else 1
            pieces.append((True, sql[i:j + 1]))
            i = j + 1
        else:
            j = sql.find("'", i)
            j = len(sql) if j < 0 else j
            pieces.append((False, sql[i:j]))
            i = j
    return pieces


_HV = re.compile(r":\s*([A-Z0-9][A-Z0-9-]*(?:\.[A-Z0-9][A-Z0-9-]*)?)(?:\s*(?:INDICATOR\s*)?:\s*([A-Z0-9][A-Z0-9-]*))?", re.I)


def _hostvars(sql: str) -> tuple[str, list[HostVar]]:
    out, hvs = [], []
    for is_str, text in _strip_strings(sql):
        if is_str:
            out.append(text)
            continue

        def sub(m):
            ref = m.group(1).upper()
            if "." in ref:
                rec, fld = ref.split(".", 1)
                ref = f"{fld} OF {rec}"
            hvs.append(HostVar(ref, m.group(2).upper() if m.group(2) else None))
            return "?"
        out.append(_HV.sub(sub, text))
    return "".join(out), hvs


def _db2_to_sqlite(sql: str) -> str:
    out = []
    for is_str, text in _strip_strings(sql):
        if not is_str:
            t = text
            t = re.sub(r"\bCURRENT[\s_]TIMESTAMP\b", f"'{FIXED_DATE}-23.59.58.000000'", t, flags=re.I)
            t = re.sub(r"\bCURRENT[\s_]DATE\b", f"'{FIXED_DATE}'", t, flags=re.I)
            t = re.sub(r"\bCURRENT[\s_]TIME\b", f"'{FIXED_TIME.replace(':', '.')}'", t, flags=re.I)
            t = re.sub(r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY\b", r"LIMIT \1", t, flags=re.I)
            t = re.sub(r"\bFETCH\s+FIRST\s+ROW\s+ONLY\b", "LIMIT 1", t, flags=re.I)
            t = re.sub(r"\bWITH\s+(UR|CS|RS|RR)\b", "", t, flags=re.I)
            t = re.sub(r"\bFOR\s+(FETCH|READ)\s+ONLY\b", "", t, flags=re.I)
            t = re.sub(r"\bFOR\s+UPDATE(\s+OF\s+[A-Z0-9_,\s-]+?)?(?=$|\bOPTIMIZE\b)", "", t, flags=re.I)
            t = re.sub(r"\bOPTIMIZE\s+FOR\s+\d+\s+ROWS?\b", "", t, flags=re.I)
            t = re.sub(r"\bVALUE\s*\(", "COALESCE(", t, flags=re.I)
            t = re.sub(r"(?<![\"A-Za-z0-9_])([A-Za-z0-9_$]*[#@][A-Za-z0-9_#@$]*)", r'"\1"', t)
            out.append(t)
        else:
            out.append(text)
    sql = re.sub(r"\s+", " ", "".join(out)).strip()
    first = sql.split(" ", 1)
    return (first[0].upper() + (" " + first[1] if len(first) > 1 else "")).strip()


def _into(sql: str) -> tuple[str, str]:
    """Split 'SELECT a, b INTO :x, :y FROM ...' into ('SELECT a, b FROM ...', ':x, :y')."""
    pieces = _strip_strings(sql)
    flat = "".join("\x00" * len(t) if s else t for s, t in pieces)
    m = re.search(r"\bINTO\b(.*?)(?=\bFROM\b|$)", flat, re.I | re.S)
    if not m:
        return sql, ""
    return sql[:m.start()] + sql[m.end():], sql[m.start(1):m.end(1)]


class Generator:
    def __init__(self, fixed: bool, items: dict):
        self.fixed, self.items, self.paras, self.n = fixed, items, [], 0
        self.cursors: dict[str, tuple[str, list[HostVar], bool]] = {}
        self.whenever = {"SQLERROR": None, "SQLWARNING": None, "NOT FOUND": None}
        self.tables_out: dict[str, Table] = {}

    # ---- emitting
    def _line(self, text: str, para: bool = False) -> list[str]:
        if not self.fixed:
            return [("" if para else "    ") + text]
        lead = " " * 7 if para else " " * 11
        return [lead + text]

    def _lines(self, stmts: list[str]) -> list[str]:
        """Statements at column 12, wrapped at spaces (outside quotes) so nothing passes column 72."""
        out = []
        for st in stmts:
            if not self.fixed:
                out += self._line(st)
                continue
            indent = len(st) - len(st.lstrip(" "))
            words, cur, rows, quote = [], "", [], False
            for ch in st.strip(" "):
                if ch == '"':
                    quote = not quote
                if ch == " " and not quote:
                    words.append(cur)
                    cur = ""
                else:
                    cur += ch
            words.append(cur)
            line = ""
            width = 61 - indent
            for w in words:
                if line and len(line) + 1 + len(w) > width:
                    rows.append(line)
                    line = w
                else:
                    line = f"{line} {w}".strip()
            rows.append(line)
            out.append(" " * (11 + indent) + rows[0])
            out += [" " * (15 + indent) + r for r in rows[1:]]
        return out

    def _literal_moves(self, sql: str) -> list[str]:
        """MOVE the statement text into SQB-TEXT in chunks short enough for column 72."""
        chunks = [sql[i:i + 40] for i in range(0, len(sql), 40)] or [""]
        stmts = ["MOVE SPACES TO SQB-TEXT", "STRING"]
        for c in chunks:
            stmts.append('    "' + c.replace('"', '""') + '"')
        stmts.append("    DELIMITED BY SIZE INTO SQB-TEXT")
        stmts.append("END-STRING")
        return stmts

    def _kind(self, name: str):
        """(kind, scale, varchar) of a host variable."""
        base = name.split(" OF ")[0]
        it = self.items.get(base)
        if it is None:
            raise SqlError(f"host variable {name} is not defined")
        if it.kind == "group" and len(it.children) == 2 and all(c.level == 49 for c in it.children):
            return "varchar", 0, it.children
        if it.kind == "num":
            return "num", max(0, min(it.scale, 9)), None
        return "alpha", 0, None

    def expand(self, hvs: list[HostVar]) -> list[HostVar]:
        """A host structure (:CUSTOMER-RECORD) stands for its elementary items, in order."""
        from .layout import walk

        def varchar(it) -> bool:
            return it.kind == "group" and len(it.children) == 2 and all(c.level == 49 for c in it.children)

        def leaves_of(it, top) -> list[HostVar]:
            found = []
            for c in it.children:
                if c.name.startswith("FILLER"):
                    continue
                if varchar(c) or not c.children:
                    found.append(HostVar(f"{c.name} OF {top.name}"))
                else:
                    found += leaves_of(c, top)
            return found

        out = []
        for hv in hvs:
            it = self.items.get(hv.name.split(" OF ")[0])
            if it is not None and it.kind == "group" and it.children and not varchar(it):
                out += leaves_of(it, it)
            else:
                out.append(hv)
        return out

    def _param_moves(self, hvs: list[HostVar]) -> list[str]:
        out = [f"MOVE {len(hvs)} TO SQB-NPARAM", "MOVE ALL 'N' TO SQB-PNULLS"]
        for i, hv in enumerate(hvs, start=1):
            kind, scale, parts = self._kind(hv.name)
            of = hv.name[len(hv.name.split(" OF ")[0]):]
            if kind == "num":
                out += [f"MOVE {hv.name} TO SQB-ED{scale}", f"MOVE SQB-ED{scale} TO SQB-PARAM({i})"]
            elif kind == "varchar":
                ln, tx = parts[0].name + of, parts[1].name + of
                out += [f"MOVE SPACES TO SQB-PARAM({i})", f"IF {ln} > 0", f"    MOVE {tx}(1:{ln}) TO SQB-PARAM({i})", "END-IF"]
            else:
                out.append(f"MOVE {hv.name} TO SQB-PARAM({i})")
            if hv.indicator:
                out += [f"IF {hv.indicator} < 0", f"    MOVE 'Y' TO SQB-PNULL({i})", "END-IF"]
        return out

    def _result_moves(self, hvs: list[HostVar]) -> list[str]:
        out = []
        for i, hv in enumerate(hvs, start=1):
            kind, scale, parts = self._kind(hv.name)
            of = hv.name[len(hv.name.split(" OF ")[0]):]
            if kind == "num":
                put = [f"    COMPUTE {hv.name} = FUNCTION NUMVAL(SQB-RES({i}))"]
            elif kind == "varchar":
                ln, tx = parts[0].name + of, parts[1].name + of
                put = [f"    MOVE SQB-RLEN({i}) TO {ln}", f"    MOVE SQB-RES({i}) TO {tx}"]
            else:
                put = [f"    MOVE SQB-RES({i}) TO {hv.name}"]
            out += [f"IF SQB-RNULL({i}) = 'N'"] + put
            if hv.indicator:
                out += [f"    MOVE 0 TO {hv.indicator}", "ELSE", f"    MOVE -1 TO {hv.indicator}"]
            else:  # DB2: a NULL value with no indicator variable is SQLCODE -305
                out += ["ELSE", "    MOVE -305 TO SQLCODE", "    MOVE '22002' TO SQLSTATE"]
            out.append("END-IF")
        return out

    def _call(self) -> str:
        return ("CALL 'SQLBRIDGE' USING SQLCA SQB-OP SQB-CURSOR SQB-TEXT SQB-NPARAM SQB-PARAMS SQB-PNULLS SQB-NRES SQB-RESULTS"
                " SQB-RNULLS SQB-RLENS")

    def _paragraph(self, body: list[str]) -> str:
        self.n += 1
        name = f"SQB-STMT-{self.n:04d}"
        call = self._call().split(" USING ")
        stmts = body[:]
        idx = stmts.index("@CALL")
        args = call[1].split()
        call_lines = [call[0] + " USING " + " ".join(args[:4])]
        for k in range(4, len(args), 4):
            call_lines.append("    " + " ".join(args[k:k + 4]))
        call_lines.append("END-CALL")
        stmts[idx:idx + 1] = call_lines
        self.paras.append("\n".join(self._line(name + ".", para=True) + self._lines(stmts) + self._lines(["CONTINUE."])))
        return name

    def statement(self, body: str) -> tuple[str | None, bool]:
        """(paragraph to PERFORM or None, whether WHENEVER tests apply) for one EXEC SQL body."""
        sql = re.sub(r"\s+", " ", body).strip()
        up = sql.upper()
        if up.startswith("WHENEVER"):
            m = re.match(r"WHENEVER\s+(SQLERROR|SQLWARNING|NOT\s+FOUND)\s+(CONTINUE|GO\s*TO\s+([A-Z0-9-]+)|GOTO\s+([A-Z0-9-]+))", up)
            if not m:
                raise SqlError(f"cannot read {sql[:60]}")
            key = "NOT FOUND" if m.group(1).startswith("NOT") else m.group(1)
            self.whenever[key] = m.group(3) or m.group(4)
            return None, False
        if re.match(r"(CONNECT|SET|LOCK|RELEASE|DISCONNECT)\b", up):
            return self._paragraph(["MOVE 'NOOP' TO SQB-OP", "@CALL"]), True
        if re.match(r"(COMMIT|ROLLBACK)\b", up):
            return self._paragraph([f"MOVE '{up.split()[0]}' TO SQB-OP", "@CALL"]), True
        m = re.match(r"DECLARE\s+([A-Z0-9_-]+)\s+(?:(?:INSENSITIVE|SCROLL|SENSITIVE)\s+)*CURSOR\s+(?:WITH\s+(?:HOLD|RETURN)\s+)*FOR\s+(.*)$", sql, re.I | re.S)
        if m:
            name = m.group(1).upper()
            for_update = bool(re.search(r"\bFOR\s+UPDATE\b", up))
            text, hvs = _hostvars(m.group(2))
            hvs = self.expand(hvs)
            text = _db2_to_sqlite(text)
            if for_update:  # the bridge needs each row's rowid for UPDATE/DELETE ... WHERE CURRENT OF
                flat = "".join("\x00" * len(t) if s else t for s, t in _strip_strings(text))
                fm = re.search(r"\bFROM\b", flat, re.I)
                if not fm:
                    raise SqlError(f"cursor {name}: cannot find FROM")
                text = text[:fm.start()].rstrip() + ", rowid " + text[fm.start():]
            self.cursors[name] = (text, hvs, for_update)
            return None, False
        m = re.match(r"(OPEN|CLOSE)\s+([A-Z0-9_-]+)$", up)
        if m:
            name = m.group(2)
            if m.group(1) == "CLOSE":
                return self._paragraph(["MOVE 'CLOSE' TO SQB-OP", f"MOVE '{name}' TO SQB-CURSOR", "@CALL"]), True
            if name not in self.cursors:
                raise SqlError(f"OPEN of undeclared cursor {name} (DECLARE CURSOR must come first in the source)")
            text, hvs, upd = self.cursors[name]
            body_ = [f"MOVE '{'OPENU' if upd else 'OPEN'}' TO SQB-OP", f"MOVE '{name}' TO SQB-CURSOR"] + self._literal_moves(text) + self._param_moves(hvs) + ["MOVE 0 TO SQB-NRES", "@CALL"]
            return self._paragraph(body_), True
        m = re.match(r"FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?([A-Z0-9_-]+)\s+INTO\s+(.*)$", sql, re.I | re.S)
        if m:
            name = m.group(1).upper()
            _, hvs = _hostvars(m.group(2))
            hvs = self.expand(hvs)
            return self._paragraph(["MOVE 'FETCH' TO SQB-OP", f"MOVE '{name}' TO SQB-CURSOR", f"MOVE {len(hvs)} TO SQB-NRES", "@CALL",
                                    "IF SQLCODE = 0"] + ["    " + x for x in self._result_moves(hvs)] + ["END-IF"]), True
        if re.match(r"(SELECT|WITH|VALUES|INSERT|UPDATE|DELETE)\b", up):
            current = re.search(r"\bWHERE\s+CURRENT\s+OF\s+([A-Z0-9_-]+)\s*$", up)
            target = ""
            if current:
                target = current.group(1)
                sql = sql[:current.start()] + " WHERE rowid = ?"
            stmt, into = _into(sql) if up.startswith(("SELECT", "WITH")) else (sql, "")
            text, hvs = _hostvars(stmt)
            hvs = self.expand(hvs)
            _, outs = _hostvars(into)
            outs = self.expand(outs)
            text = _db2_to_sqlite(text)
            body_ = [f"MOVE '{'CURRENT' if current else 'EXEC'}' TO SQB-OP", f"MOVE '{target}' TO SQB-CURSOR"] + self._literal_moves(text)
            body_ += self._param_moves(hvs) + [f"MOVE {len(outs)} TO SQB-NRES", "@CALL"]
            if outs:
                body_ += ["IF SQLCODE = 0 OR SQLCODE = -811"] + ["    " + x for x in self._result_moves(outs)] + ["END-IF"]
            return self._paragraph(body_), True
        raise SqlError(f"EXEC SQL {sql.split()[0] if sql else ''} is not supported yet")

    def tests(self) -> list[str]:
        out = []
        if self.whenever["SQLERROR"]:
            out.append(f"IF SQLCODE < 0 GO TO {self.whenever['SQLERROR']} END-IF")
        if self.whenever["SQLWARNING"]:
            out.append(f"IF SQLCODE > 0 AND SQLCODE NOT = 100 GO TO {self.whenever['SQLWARNING']} END-IF")
        if self.whenever["NOT FOUND"]:
            out.append(f"IF SQLCODE = 100 GO TO {self.whenever['NOT FOUND']} END-IF")
        return out


def _fit(lines_avail: int, first_col: int, stmts: list[str], fixed: bool, period: bool) -> list[str]:
    """Lay statements over the original block's lines without moving later lines."""
    text = " ".join(stmts) + ("." if period else "")
    if not fixed:
        return [" " * first_col + text] + [""] * (lines_avail - 1)
    width = 72 - max(first_col, 11)
    words, rows, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            rows.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    rows.append(cur)
    if len(rows) > lines_avail:
        raise SqlError("the statements that replace an EXEC SQL do not fit its lines")
    out = [" " * max(first_col, 11) + rows[0]] + [" " * 11 + r for r in rows[1:]]
    return out + [""] * (lines_avail - len(out))


def precompile_text(text: str, gen: Generator, only_data: bool = False) -> str:
    fixed = gen.fixed
    code = _code_text(text, fixed)
    pm = re.search(r"\bPROCEDURE\s+DIVISION\b", code, re.I)
    proc_at = pm.start() if pm else len(code)
    plans = []
    for m in _EXEC.finditer(code):  # forward: cursors are declared and WHENEVER takes effect in source order
        body = m.group(1)
        start_line = text.count("\n", 0, m.start())
        end_line = text.count("\n", 0, m.end())
        line_start = text.rfind("\n", 0, m.start()) + 1
        first_col = m.start() - line_start
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end < 0 else line_end
        before = text[line_start:m.start()]
        after = text[m.end():line_end]
        span = end_line - start_line + 1
        up = re.sub(r"\s+", " ", body).strip().upper()
        if up.startswith("INCLUDE"):
            member = up.split()[1].strip("'\"")
            replacement = [before + f"COPY {member}." + after]
        elif up.startswith(("BEGIN DECLARE", "END DECLARE")):
            replacement = [before + after]
        elif up.startswith("DECLARE") and " TABLE" in f" {up}" and "CURSOR" not in up:
            t = _declare_table(body)
            gen.tables_out[t.name] = t
            replacement = [before + after]
        elif only_data:
            continue
        else:
            para, tests = gen.statement(body)
            if para is None and m.start() < proc_at:  # DECLARE CURSOR or WHENEVER in the data division: nothing to run
                plans.append((start_line, end_line, [before + after] + [""] * (span - 1)))
                continue
            stmts = ([f"PERFORM {para}"] if para else ["CONTINUE"]) + (gen.tests() if tests else [])
            fitted = _fit(span, first_col, stmts, fixed, bool(m.group(2)))
            fitted[-1] += after
            replacement = [before.rstrip() + " " + fitted[0].lstrip()] if before.strip() else [fitted[0]]
            replacement += fitted[1:]
        replacement += [""] * (span - len(replacement))
        plans.append((start_line, end_line, replacement[:span]))
    lines = text.split("\n")
    for start_line, end_line, replacement in reversed(plans):
        lines[start_line:end_line + 1] = replacement
    return "\n".join(lines)


def precompile_folder(src_dir: Path, main: str, out_dir: Path) -> Result:
    """Write precompiled copies of every program and copybook in src_dir to out_dir, plus SQLCA.cpy."""
    from .layout import parse_entries, walk
    from .cobol_src import normalize, sentences

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    result = Result()
    files = [p for p in src_dir.iterdir() if p.is_file() and p.name != ".user"]
    texts = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in files}
    # pass 1: data-division SQL (INCLUDE, DECLARE TABLE, DECLARE SECTION) in every file
    main_text = texts.get(f"{main}.cbl", next(iter(texts.values()), ""))
    stage = {}
    for name, text in texts.items():
        fixed = detect_fixed(text) if re.search(r"\bDIVISION\b", text, re.I) else detect_fixed(main_text)
        gen = Generator(fixed, {})
        gen.tables_out = result.tables
        stage[name] = precompile_text(text, gen, only_data=True) if has_sql(text) else text
    stage["SQLCA.cpy"] = SQLCA_COPY
    for name, text in stage.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    # pass 2: procedure SQL, now that host variables can be looked up
    for name, text in list(stage.items()):
        if not name.lower().endswith((".cbl", ".cob", ".cobol")) or not has_sql(text):
            continue
        fixed = detect_fixed(text)
        items = _data_items(out_dir / name, fixed)
        gen = Generator(fixed, items)
        gen.tables_out = result.tables
        new = precompile_text(text, gen)
        if not re.search(r"\bCOPY\s+SQLCA\b", new, re.I):
            new = re.sub(r"(WORKING-STORAGE\s+SECTION\s*\.)", r"\1 COPY SQLCA.", new, count=1, flags=re.I)
        if gen.paras:
            tail = "\n".join(gen._line("SQB-END-OF-PROGRAM.", para=True) + gen._line("GOBACK.")) + "\n" + "\n".join(gen.paras) + "\n"
            em = re.search(r"^.*\bEND\s+PROGRAM\b.*$", new, re.I | re.M)
            new = (new[:em.start()] + tail + new[em.start():]) if em else (new.rstrip("\n") + "\n" + tail)
        result.statements += gen.n
        (out_dir / name).write_text(new, encoding="utf-8")
    return result


def _data_items(path: Path, fixed: bool) -> dict:
    """Data items by name, from the program and its copybooks (procedure SQL blanked out)."""
    from .cobol_src import normalize, sentences
    from .layout import parse_entries, walk
    from .model import _inline_copies

    text = path.read_text(encoding="utf-8", errors="replace")
    text = _EXEC.sub(lambda m: " " * len(m.group(0)), _code_text(text, fixed))
    items = _inline_copies(sentences(normalize(text, fixed)), path.parent)
    entries, section = [], ""
    for line, s in items:
        up = s.upper().strip()
        if re.match(r"^(FILE|WORKING-STORAGE|LOCAL-STORAGE|LINKAGE)\s+SECTION$", up):
            section = up
            continue
        if re.match(r"^PROCEDURE\s+DIVISION", up):
            break
        if re.match(r"^(FD|SD)\s", up):
            continue
        if section and re.match(r"^\d{1,2}\s", up):
            entries.append((line, s))
    out = {}
    for root in parse_entries(entries):
        for it in walk(root):
            out.setdefault(it.name, it)
    return out


def schema_and_seed(tables: dict[str, Table], rows: dict[str, list[list]] | None = None) -> str:
    lines = [t.ddl() for t in tables.values()]
    for name, data in (rows or {}).items():
        for r in data:
            def lit(v):
                if v is None:
                    return "NULL"
                if isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v)):
                    return str(v)
                return "'" + str(v).replace("'", "''") + "'"
            vals = ", ".join(lit(v) for v in r)
            lines.append(f'INSERT INTO "{name}" VALUES ({vals});')
    return "\n".join(lines) + "\n"
