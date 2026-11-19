"""Precompiler for CICS commands (EXEC CICS ... END-EXEC), the job of the CICS translator, for testing off the mainframe.

As with SQL, every command becomes plain COBOL on the same lines: a PERFORM of a generated paragraph that CALLs
'CICSBRIDGE', followed by the condition handling CICS would do (RESP, HANDLE CONDITION, HANDLE AID, or an abend
when nothing handles it). Files, temporary storage, the terminal and the COMMAREA live in a SQLite database that
the C bridge (COBOL side) and the Python bridge (Python side) both use, so a transaction can be replayed on both.

A transaction runs pseudo-conversationally: the program starts with the COMMAREA from the test case, and each time
it RETURNs with a TRANSID while the user still has screens to send, it runs again with the COMMAREA it returned.

Commands: READ (EQUAL, GTEQ, GENERIC, UPDATE), WRITE, REWRITE, DELETE, STARTBR, READNEXT, READPREV, ENDBR, RESETBR,
SEND TEXT, SEND MAP, SEND CONTROL, RECEIVE, RECEIVE MAP, RETURN (TRANSID, COMMAREA), LINK, XCTL, ABEND, WRITEQ TS/TD,
READQ TS/TD, DELETEQ TS/TD, ASKTIME, FORMATTIME, SYNCPOINT, HANDLE CONDITION, HANDLE AID, IGNORE CONDITION,
HANDLE ABEND, PUSH/POP HANDLE, ENQ, DEQ. Options RESP, RESP2, NOHANDLE, LENGTH (including LENGTH OF), KEYLENGTH.
DFHRESP(condition) is replaced by its number, and DFHEIBLK, DFHAID and DFHBMSCA are supplied.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from .cicsbridge import RESP
from .cobol_src import detect_fixed

_EXEC = re.compile(r"EXEC\s+CICS\b(.*?)\bEND-EXEC(\s*\.)?", re.I | re.S)
ABEND_FOR = {"QZERO": "AEYG", "NOTFND": "AEIM", "DUPREC": "AEIN", "ENDFILE": "AEIL", "LENGERR": "AEIV", "QIDERR": "AEYH", "ITEMERR": "AEYJ",
             "MAPFAIL": "AEI9", "INVREQ": "AEIP", "ERROR": "AEIP"}
AIDS = {"ENTER": "'", "CLEAR": "_", "PA1": "%", "PA2": ">", "PA3": ",", **{f"PF{i}": c for i, c in zip(range(1, 25), "123456789:#@ABCDEFGHI¢.<")}}

DFHEIBLK = """       01  DFHEIBLK.
           02  EIBTIME        PIC S9(7) COMP-3.
           02  EIBDATE        PIC S9(7) COMP-3.
           02  EIBTRNID       PIC X(4).
           02  EIBTASKN       PIC S9(7) COMP-3.
           02  EIBTRMID       PIC X(4).
           02  DFHEIGDI       PIC S9(4) COMP.
           02  EIBCPOSN       PIC S9(4) COMP.
           02  EIBCALEN       PIC S9(4) COMP.
           02  EIBAID         PIC X.
           02  EIBFN          PIC X(2).
           02  EIBRCODE       PIC X(6).
           02  EIBDS          PIC X(8).
           02  EIBREQID       PIC X(8).
           02  EIBRSRCE       PIC X(8).
           02  EIBSYNC        PIC X.
           02  EIBFREE        PIC X.
           02  EIBRECV        PIC X.
           02  EIBSEND        PIC X.
           02  EIBATT         PIC X.
           02  EIBEOC         PIC X.
           02  EIBFMH         PIC X.
           02  EIBCOMPL       PIC X.
           02  EIBSIG         PIC X.
           02  EIBCONF        PIC X.
           02  EIBERR         PIC X.
           02  EIBERRCD       PIC X(4).
           02  EIBSYNRB       PIC X.
           02  EIBNODAT       PIC X.
           02  EIBRESP        PIC S9(8) COMP.
           02  EIBRESP2       PIC S9(8) COMP.
           02  EIBRLDBK       PIC X.
"""
CIBWORK = """       01  CIB-OP             PIC X(8).
       01  CIB-NAME           PIC X(8).
       01  CIB-KEYLEN         PIC 9(5).
       01  CIB-DATALEN        PIC 9(5).
       01  CIB-ITEM           PIC 9(5).
       01  CIB-DUMMY          PIC X.
       01  CIB-SAVE-CALEN     PIC S9(4) COMP.
       01  CIB-TEXT           PIC X(2000).
"""
DFHAID = "       01  DFHAID.\n" + "".join(
    f"           02  DFH{k:<10} PIC X VALUE X'{v.encode('latin-1').hex().upper()}'.\n" for k, v in AIDS.items()
) + "           02  DFHNULL       PIC X VALUE LOW-VALUE.\n"
DFHBMSCA = """       01  DFHBMSCA.
           02  DFHBMPEM       PIC X VALUE X'19'.
           02  DFHBMPNL       PIC X VALUE X'15'.
           02  DFHBMASK       PIC X VALUE '0'.
           02  DFHBMUNP       PIC X VALUE ' '.
           02  DFHBMUNN       PIC X VALUE '&'.
           02  DFHBMPRO       PIC X VALUE '-'.
           02  DFHBMBRY       PIC X VALUE 'H'.
           02  DFHBMDAR       PIC X VALUE '<'.
           02  DFHBMFSE       PIC X VALUE 'A'.
           02  DFHBMPRF       PIC X VALUE '/'.
           02  DFHBMASF       PIC X VALUE '1'.
           02  DFHBMASB       PIC X VALUE '8'.
"""


class CicsError(ValueError):
    pass


def has_cics(text: str) -> bool:
    return bool(re.search(r"\bEXEC\s+CICS\b", text, re.I))


def _code_text(text: str, fixed: bool) -> str:
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


def parse_options(body: str) -> tuple[list[str], dict[str, str | None]]:
    """'READ FILE('CUST') INTO(WS-REC) RIDFLD(WS-KEY) UPDATE' -> (['READ'], {'FILE': "'CUST'", ..., 'UPDATE': None})."""
    i, n = 0, len(body)
    words, opts = [], {}
    while i < n:
        while i < n and body[i] in " \t\r\n":
            i += 1
        m = re.match(r"[A-Za-z0-9-]+", body[i:])
        if not m:
            if i < n:
                raise CicsError(f"cannot read {body[i:i + 20]!r}")
            break
        word = m.group(0).upper()
        i += len(m.group(0))
        while i < n and body[i] in " \t":
            i += 1
        if i < n and body[i] == "(":
            depth, j, quote = 0, i, ""
            while j < n:
                ch = body[j]
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch in "'\"":
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            opts[word] = re.sub(r"\s+", " ", body[i + 1:j]).strip()
            i = j + 1
        elif not opts:
            words.append(word)
        else:
            opts[word] = None
    return words, opts


class Generator:
    def __init__(self, fixed: bool, items: dict):
        self.fixed, self.items, self.paras, self.n = fixed, items, [], 0
        self.handlers: dict[str, str] = {}  # condition -> paragraph (HANDLE CONDITION)
        self.aids: dict[str, str] = {}  # AID name -> paragraph (HANDLE AID)
        self.ignored: set[str] = set()
        self.notes: list[str] = []
        self.main = True  # False in a program reached by LINK or XCTL

    # ---- emitting (the same layout rules as the SQL precompiler)
    def _lines(self, stmts: list[str]) -> list[str]:
        out = []
        for st in stmts:
            if not self.fixed:
                out.append("    " + st)
                continue
            indent = len(st) - len(st.lstrip(" "))
            words, cur, quote = [], "", ""
            for ch in st.strip(" "):
                if quote:
                    if ch == quote:
                        quote = ""
                elif ch in "'\"":
                    quote = ch
                if ch == " " and not quote:
                    words.append(cur)
                    cur = ""
                else:
                    cur += ch
            words.append(cur)
            rows, line, width = [], "", 61 - indent
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

    def paragraph(self, stmts: list[str]) -> str:
        self.n += 1
        name = f"CIB-STMT-{self.n:04d}"
        head = (" " * 7 if self.fixed else "") + name + "."
        self.paras.append("\n".join([head] + self._lines(stmts + ["CONTINUE."])))
        return name

    def size(self, ref: str) -> int:
        base = re.split(r"[\s(]", ref.strip(), 1)[0].upper()
        it = self.items.get(base)
        if it is None:
            raise CicsError(f"{ref} is not a data item")
        return it.size

    def value(self, v: str | None) -> str:
        """An option value as a COBOL sending item: literal, data name, or LENGTH OF x as a number."""
        if v is None:
            return "SPACES"
        m = re.fullmatch(r"LENGTH\s+OF\s+(.+)", v, re.I)
        if m:
            return str(self.size(m.group(1)))
        return v

    def length(self, opts: dict, key: str, area: str | None) -> str:
        if opts.get(key):
            return self.value(opts[key])
        if area is None:
            return "0"
        if re.match(r"^['\"]", area):
            return str(len(area) - 2)
        return str(self.size(area))

    def _call(self, op: str, name: str, keylen: str, key: str, datalen: str, data: str) -> list[str]:
        assert len(op) <= 8, f"bridge operation {op} does not fit CIB-OP PIC X(8)"
        data_ref, pre = data, []
        if re.match(r"^['\"]", data):  # a literal FROM: through CIB-TEXT
            pre, data_ref = [f"MOVE {data} TO CIB-TEXT"], "CIB-TEXT"
        return pre + [f"MOVE '{op}' TO CIB-OP", f"MOVE {name} TO CIB-NAME", f"MOVE {keylen} TO CIB-KEYLEN", f"MOVE {datalen} TO CIB-DATALEN",
                      f"CALL 'CICSBRIDGE' USING DFHEIBLK CIB-OP CIB-NAME CIB-KEYLEN {key} CIB-DATALEN {data_ref} CIB-ITEM",
                      "END-CALL"]

    def _after(self, opts: dict) -> list[str]:
        out = []
        if opts.get("RESP"):
            out.append(f"MOVE EIBRESP TO {opts['RESP']}")
        if opts.get("RESP2"):
            out.append(f"MOVE EIBRESP2 TO {opts['RESP2']}")
        return out

    def tests(self, opts: dict, conds: list[str]) -> list[str]:
        """What CICS does when a command does not end NORMAL: RESP and NOHANDLE mean the program checks;
        otherwise a HANDLE CONDITION label is taken, or the task abends."""
        if "RESP" in opts or "NOHANDLE" in opts:
            return [], []
        out, inner = [], []
        for c in conds:
            code = RESP[c]
            if c in self.ignored:
                continue
            if c in self.handlers:
                out.append(f"IF EIBRESP = {code} GO TO {self.handlers[c]} END-IF")
        if "ERROR" in self.handlers:
            out.append(f"IF EIBRESP NOT = 0 GO TO {self.handlers['ERROR']} END-IF")
        else:
            unhandled = [c for c in conds if c not in self.handlers and c not in self.ignored]
            if unhandled:
                ab = self.paragraph(["MOVE 'ABEND' TO CIB-OP", "EVALUATE EIBRESP"]
                                    + [f"    WHEN {RESP[c]} MOVE '{ABEND_FOR.get(c, 'AEIP')}' TO CIB-NAME" for c in unhandled]
                                    + ["    WHEN OTHER MOVE 'AEIP' TO CIB-NAME", "END-EVALUATE", "MOVE 0 TO CIB-KEYLEN CIB-DATALEN",
                                       "CALL 'CICSBRIDGE' USING DFHEIBLK CIB-OP CIB-NAME CIB-KEYLEN CIB-DUMMY CIB-DATALEN CIB-DUMMY CIB-ITEM",
                                       "END-CALL"])
                inner.append(f"IF EIBRESP NOT = 0 PERFORM {ab} GOBACK END-IF")
        return inner, out

    def _site(self, body_: list[str], opts: dict, conds: list[str], tail: list[str] | None = None) -> list[str]:
        """The statements left where the command was: a PERFORM of its paragraph, then any HANDLE CONDITION jumps."""
        inner, outer = self.tests(opts, conds)
        return [f"PERFORM {self.paragraph(body_ + self._after(opts) + inner + (tail or []))}"] + outer

    def command(self, body: str) -> list[str]:
        """Statements to put where the EXEC CICS was."""
        words, o = parse_options(body)
        verb = " ".join(words) if words else next(iter(o))
        first = words[0] if words else verb
        if first in ("READ", "WRITE", "REWRITE", "DELETE", "STARTBR", "READNEXT", "READPREV", "ENDBR", "RESETBR"):
            file = self.value(o.get("FILE") or o.get("DATASET") or o.get("FILE"))
            ridfld = o.get("RIDFLD")
            keylen = self.value(o["KEYLENGTH"]) if o.get("KEYLENGTH") else (str(self.size(ridfld)) if ridfld else "0")
            key = ridfld or "CIB-DUMMY"
            if first in ("READ", "READNEXT", "READPREV"):
                area = o.get("INTO")
                if area is None:
                    raise CicsError(f"{first} with SET (pointers) is not supported; use INTO")
                op = first if first != "READ" else ("READGEN" if "GENERIC" in o else "READGE" if "GTEQ" in o else "READ")
                body_ = self._call(op, file, keylen, key, self.length(o, "LENGTH", area), area)
                if o.get("LENGTH") and not re.fullmatch(r"\d+|LENGTH\s+OF.*", o["LENGTH"], re.I):
                    body_.append(f"MOVE CIB-DATALEN TO {o['LENGTH']}")
                conds = ["NOTFND", "LENGERR"] if first == "READ" else ["ENDFILE", "LENGERR", "INVREQ"]
            elif first == "WRITE":
                area = o.get("FROM")
                body_ = self._call("WRITE", file, keylen, key, self.length(o, "LENGTH", area), area)
                conds = ["DUPREC"]
            elif first == "REWRITE":
                area = o.get("FROM")
                body_ = self._call("REWRITE", file, "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area)
                conds = ["INVREQ"]
            elif first == "DELETE":
                body_ = self._call("DELETE", file, keylen if ridfld else "0", key, "0", "CIB-DUMMY")
                conds = ["NOTFND", "INVREQ"]
            elif first in ("STARTBR", "RESETBR"):
                body_ = self._call("STARTBR", file, keylen, key, "0", "CIB-DUMMY")
                conds = ["NOTFND"]
            else:
                body_ = self._call("ENDBR", file, "0", "CIB-DUMMY", "0", "CIB-DUMMY")
                conds = ["INVREQ"]
            return self._site(body_, o, conds)
        if first == "SEND":
            if "MAP" in o:
                area = o.get("FROM") or (self._symbolic(o["MAP"], "O"))
                body_ = self._call("SENDMAP", self.value(o["MAP"]), "0", "CIB-DUMMY", self.length(o, "LENGTH", area) if area else "0", area or "CIB-DUMMY")
            elif "CONTROL" in words or "CONTROL" in o:
                body_ = self._call("SEND", "SPACES", "0", "CIB-DUMMY", "0", "CIB-DUMMY")
            else:
                area = o.get("FROM")
                body_ = self._call("SEND", "SPACES", "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area or "CIB-DUMMY")
            return self._site(body_, o, ["INVREQ"])
        if first == "RECEIVE":
            area = o.get("INTO") or (self._symbolic(o["MAP"], "I") if "MAP" in o else None)
            if area is None:
                raise CicsError("RECEIVE needs INTO (or a MAP with a symbolic map)")
            body_ = self._call("RECEIVE", self.value(o.get("MAP")) if "MAP" in o else "SPACES", "0", "CIB-DUMMY",
                               self.length(o, "MAXLENGTH", area) if "MAXLENGTH" in o else str(self.size(area)), area)
            if o.get("LENGTH") and not re.fullmatch(r"\d+", o["LENGTH"]):
                body_.append(f"MOVE CIB-DATALEN TO {o['LENGTH']}")
            out = self._site(body_, o, ["MAPFAIL", "LENGERR"])
            for aid, label in self.aids.items():  # HANDLE AID
                out.append("IF EIBAID NOT = DFHENTER GO TO " + label + " END-IF" if aid == "ANYKEY" else f"IF EIBAID = DFH{aid} GO TO {label} END-IF")
            return out
        if first == "RETURN":
            if "TRANSID" in o:
                area = o.get("COMMAREA")
                body_ = self._call("RETURN", self.value(o["TRANSID"]), "0", "CIB-DUMMY", self.length(o, "LENGTH", area) if area else "0", area or "CIB-DUMMY")
            elif not self.main:
                return ["GOBACK"]  # a LINKed program goes back to the program that linked to it
            else:
                body_ = self._call("RETURN", "SPACES", "0", "CIB-DUMMY", "0", "CIB-DUMMY")
            return [f"PERFORM {self.paragraph(body_ + ['GOBACK'])}"]
        if first in ("LINK", "XCTL"):
            prog = self.value(o.get("PROGRAM"))
            area = o.get("COMMAREA")
            calen = self.length(o, "LENGTH", area) if area else "0"
            body_ = ["MOVE 0 TO EIBRESP EIBRESP2", "MOVE EIBCALEN TO CIB-SAVE-CALEN", f"MOVE {calen} TO EIBCALEN",
                     f"CALL {prog} USING DFHEIBLK {area or 'CIB-DUMMY'}", "    ON EXCEPTION MOVE 27 TO EIBRESP", "END-CALL",
                     f"CANCEL {prog}",  # every LINK gets fresh WORKING-STORAGE, as in CICS
                     "MOVE CIB-SAVE-CALEN TO EIBCALEN"]
            return self._site(body_, o, ["PGMIDERR"], ["GOBACK"] if first == "XCTL" else None)
        if first == "ABEND":
            body_ = self._call("ABEND", self.value(o.get("ABCODE") or "'ABND'"), "0", "CIB-DUMMY", "0", "CIB-DUMMY")
            return [f"PERFORM {self.paragraph(body_ + ['GOBACK'])}"]
        if first in ("WRITEQ", "READQ", "DELETEQ") and ("TD" in words or "TD" in o):
            # transient data: READQ TD takes the oldest record off the queue; QZERO when it is empty
            q = self.value(o.get("QUEUE") or o.get("QNAME"))
            if first == "WRITEQ":
                area = o.get("FROM")
                body_ = self._call("WRITEQTD", q, "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area)
                conds = []
            elif first == "READQ":
                area = o.get("INTO")
                body_ = self._call("READQTD", q, "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area)
                if o.get("LENGTH") and not re.fullmatch(r"\d+|LENGTH\s+OF.*", o["LENGTH"], re.I):
                    body_.append(f"MOVE CIB-DATALEN TO {o['LENGTH']}")
                conds = ["QZERO"]
            else:
                body_ = self._call("DELQTD", q, "0", "CIB-DUMMY", "0", "CIB-DUMMY")
                conds = []
            return self._site(body_, o, conds)
        if first in ("WRITEQ", "READQ", "DELETEQ"):
            q = self.value(o.get("QUEUE") or o.get("QNAME"))
            if first == "WRITEQ":
                area = o.get("FROM")
                body_ = self._call("WRITEQTS", q, "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area)
                if o.get("ITEM"):
                    body_.append(f"MOVE CIB-ITEM TO {o['ITEM']}")
                conds = ["QIDERR"]
            elif first == "READQ":
                area = o.get("INTO")
                body_ = [f"MOVE {self.value(o['ITEM']) if o.get('ITEM') and 'NEXT' not in o else 0} TO CIB-ITEM"]
                body_ += self._call("READQTS", q, "0", "CIB-DUMMY", self.length(o, "LENGTH", area), area)
                conds = ["QIDERR", "ITEMERR"]
            else:
                body_ = self._call("DELQTS", q, "0", "CIB-DUMMY", "0", "CIB-DUMMY")
                conds = ["QIDERR"]
            return self._site(body_, o, conds)
        if first == "ASKTIME":
            stmts = []
            if o.get("ABSTIME"):
                stmts.append(f"MOVE {ABSTIME} TO {o['ABSTIME']}")
            return stmts or ["CONTINUE"]
        if first == "FORMATTIME":
            sep = (o.get("DATESEP") or "'/'").strip("'\"") if "DATESEP" in o else ""
            tsep = (o.get("TIMESEP") or "':'").strip("'\"") if "TIMESEP" in o else ""
            d = datetime(2026, 10, 31, 23, 59, 58)
            forms = {"YYYYMMDD": f"{d:%Y}{sep}{d:%m}{sep}{d:%d}", "MMDDYYYY": f"{d:%m}{sep}{d:%d}{sep}{d:%Y}",
                     "DDMMYYYY": f"{d:%d}{sep}{d:%m}{sep}{d:%Y}", "YYMMDD": f"{d:%y}{sep}{d:%m}{sep}{d:%d}",
                     "MMDDYY": f"{d:%m}{sep}{d:%d}{sep}{d:%y}", "DDMMYY": f"{d:%d}{sep}{d:%m}{sep}{d:%y}",
                     "YYYYDDD": f"{d:%Y}{sep}{d:%j}", "TIME": f"{d:%H}{tsep}{d:%M}{tsep}{d:%S}", "YEAR": f"{d:%Y}",
                     "DAYOFMONTH": f"{d.day}", "MONTHOFYEAR": f"{d.month}"}
            return [f"MOVE '{v}' TO {o[k]}" for k, v in forms.items() if o.get(k)] or ["CONTINUE"]
        if first == "SYNCPOINT":
            return [f"PERFORM {self.paragraph(self._call('SYNCPNT', 'SPACES', '0', 'CIB-DUMMY', '0', 'CIB-DUMMY'))}"]
        if first == "HANDLE" and words[1:2] == ["CONDITION"] or (first == "HANDLE" and "CONDITION" in o):
            for c in words[2:]:  # HANDLE CONDITION NOTFND ENDFILE: no labels, so these are cancelled
                self.handlers.pop(c, None)
            for c, label in o.items():
                if c == "CONDITION":
                    continue
                if label:
                    self.handlers[c] = label.strip()
                else:
                    self.handlers.pop(c, None)
                self.ignored.discard(c)
            return ["CONTINUE"]
        if first == "HANDLE" and (words[1:2] == ["AID"] or "AID" in o):
            for k, label in o.items():
                if k != "AID" and label:
                    self.aids[k] = label.strip()
            return ["CONTINUE"]
        if first == "IGNORE":
            self.ignored |= {c for c in list(o) + words[2:] if c != "CONDITION"}
            return ["CONTINUE"]
        if first in ("PUSH", "POP", "HANDLE", "ENQ", "DEQ", "ADDRESS", "ASSIGN"):
            if first in ("ADDRESS", "ASSIGN"):
                self.notes.append(f"EXEC CICS {first} is accepted and does nothing here.")
            return ["CONTINUE"]
        raise CicsError(f"EXEC CICS {verb} is not supported yet")

    def _symbolic(self, mapname: str, suffix: str) -> str | None:
        name = mapname.strip("'\"").upper() + suffix
        return name if name in self.items else None


def _abstime() -> int:
    d = datetime(2026, 10, 31, 23, 59, 58)
    return int((d - datetime(1900, 1, 1)).total_seconds() * 1000)


ABSTIME = _abstime()


def _fit(span: int, first_col: int, stmts: list[str], fixed: bool, period: bool) -> list[str]:
    text = " ".join(stmts) + ("." if period else "")
    if not fixed:
        return [" " * first_col + text] + [""] * (span - 1)
    width = 72 - max(first_col, 11)
    rows, cur, quote = [], "", ""
    for w in text.split(" "):
        if cur and len(cur) + 1 + len(w) > width:
            rows.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    rows.append(cur)
    if len(rows) > span:
        rows = [" ".join(rows)]  # free-standing: let it run long; lines must not move
        if len(rows[0]) > width:
            raise CicsError("the statements that replace an EXEC CICS do not fit its lines; give the command more lines")
    out = [" " * max(first_col, 11) + rows[0]] + [" " * 11 + r for r in rows[1:]]
    return out + [""] * (span - len(out))


def precompile_text(text: str, gen: Generator, main: bool) -> str:
    fixed = gen.fixed
    code = _code_text(text, fixed)
    plans = []
    for m in _EXEC.finditer(code):
        start_line = text.count("\n", 0, m.start())
        end_line = text.count("\n", 0, m.end())
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line_end = len(text) if line_end < 0 else line_end
        before, after = text[line_start:m.start()], text[m.end():line_end]
        span = end_line - start_line + 1
        stmts = gen.command(m.group(1))
        fitted = _fit(span, m.start() - line_start, stmts, fixed, bool(m.group(2)))
        fitted[-1] += after
        rep = [before.rstrip() + " " + fitted[0].lstrip()] if before.strip() else [fitted[0]]
        rep += fitted[1:]
        plans.append((start_line, end_line, (rep + [""] * span)[:span]))
    lines = text.split("\n")
    for a, b, rep in reversed(plans):
        lines[a:b + 1] = rep
    out = "\n".join(lines)
    # DFHRESP(NOTFND) -> 13, keeping columns
    out = re.sub(r"DFHRESP\s*\(\s*([A-Z0-9]+)\s*\)", lambda mm: str(RESP.get(mm.group(1).upper(), 1)).ljust(len(mm.group(0))), out, flags=re.I)
    return out


def precompile_folder(src_dir: Path, main: str, out_dir: Path) -> list[str]:
    from .sqlpre import _data_items

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    notes: list[str] = []
    for p in src_dir.iterdir():
        if p.is_file() and p.name != ".user":
            shutil.copy(p, out_dir / p.name)
    for name, text in (("DFHEIBLK.cpy", DFHEIBLK), ("CIBWORK.cpy", CIBWORK), ("DFHAID.cpy", DFHAID), ("DFHBMSCA.cpy", DFHBMSCA)):
        (out_dir / name).write_text(text, encoding="utf-8")
    for p in sorted(out_dir.iterdir()):
        if p.suffix.lower() not in (".cbl", ".cob", ".cobol"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not has_cics(text):
            continue
        fixed = detect_fixed(text)
        is_main = p.stem.lower() == main.lower()
        # storage the program expects from CICS: the EIB, the work area, and (for the main program) its COMMAREA
        staged = text
        if is_main:
            staged = re.sub(r"^(.*?)\bLINKAGE\s+SECTION\s*\.(.*)$", lambda mm: mm.group(1) + " " * len("LINKAGE SECTION.") + mm.group(2),
                            staged, count=1, flags=re.I | re.M)
            staged = re.sub(r"(PROCEDURE\s+DIVISION)\s+USING\s+DFHEIBLK(\s+DFHCOMMAREA)?", r"\1", staged, count=1, flags=re.I)
        if re.search(r"\bWORKING-STORAGE\s+SECTION\s*\.", staged, re.I):
            staged = re.sub(r"(WORKING-STORAGE\s+SECTION\s*\.)", r"\1 COPY CIBWORK." + (" COPY DFHEIBLK." if is_main else ""), staged, count=1, flags=re.I)
        else:
            staged = re.sub(r"(DATA\s+DIVISION\s*\.)", r"\1 WORKING-STORAGE SECTION. COPY CIBWORK." + (" COPY DFHEIBLK." if is_main else ""),
                            staged, count=1, flags=re.I)
        if not is_main:
            if re.search(r"\bLINKAGE\s+SECTION\s*\.", staged, re.I):
                staged = re.sub(r"(LINKAGE\s+SECTION\s*\.)", r"\1 COPY DFHEIBLK.", staged, count=1, flags=re.I)
            has_area = re.search(r"\b01\s+DFHCOMMAREA\b", staged, re.I)
            staged = re.sub(r"(PROCEDURE\s+DIVISION)(\s+USING\s+[^.]*)?\.", r"\1 USING DFHEIBLK" + (" DFHCOMMAREA" if has_area else "") + ".",
                            staged, count=1, flags=re.I)
        p.write_text(staged, encoding="utf-8")
        items = _data_items(p, fixed)
        gen = Generator(fixed, items)
        gen.main = is_main
        new = precompile_text(staged, gen, is_main)
        if is_main:
            area = "DFHCOMMAREA" if "DFHCOMMAREA" in items else "CIB-DUMMY"
            calen = str(items["DFHCOMMAREA"].size) if area == "DFHCOMMAREA" else "0"
            entry = gen.paragraph(["MOVE 'ENTRY' TO CIB-OP", "MOVE SPACES TO CIB-NAME", "MOVE 0 TO CIB-KEYLEN", f"MOVE {calen} TO CIB-DATALEN",
                                   f"CALL 'CICSBRIDGE' USING DFHEIBLK CIB-OP CIB-NAME CIB-KEYLEN CIB-DUMMY CIB-DATALEN {area} CIB-ITEM",
                                   "END-CALL"])
            new = re.sub(r"(PROCEDURE\s+DIVISION\s*\.)", r"\1 PERFORM " + entry + ".", new, count=1, flags=re.I)
        if gen.paras:
            end = (" " * 7 if fixed else "") + "CIB-END-OF-PROGRAM.\n" + (" " * 11 if fixed else "    ") + "GOBACK.\n"
            tail = end + "\n".join(gen.paras) + "\n"
            em = re.search(r"^.*\bEND\s+PROGRAM\b.*$", new, re.I | re.M)
            new = (new[:em.start()] + tail + new[em.start():]) if em else (new.rstrip("\n") + "\n" + tail)
        notes += gen.notes
        p.write_text(new, encoding="utf-8")
    return notes


def usage(text: str) -> dict:
    """What a CICS program touches: files (with their record area and key field), the areas it RECEIVEs into."""
    fixed = detect_fixed(text)
    files: dict[str, dict] = {}
    receives: list[str] = []
    queues: set[str] = set()
    for m in _EXEC.finditer(_code_text(text, fixed)):
        try:
            words, o = parse_options(m.group(1))
        except CicsError:
            continue
        first = words[0] if words else ""
        name = (o.get("FILE") or o.get("DATASET") or "").strip("'\"").upper()
        if first in ("READ", "WRITE", "REWRITE", "READNEXT", "READPREV") and name:
            f = files.setdefault(name, {"area": None, "key": None})
            f["area"] = f["area"] or (o.get("INTO") or o.get("FROM"))
            f["key"] = f["key"] or o.get("RIDFLD")
        if first in ("STARTBR", "DELETE") and name:
            files.setdefault(name, {"area": None, "key": o.get("RIDFLD")})
        if first == "RECEIVE":
            area = o.get("INTO") or ((o.get("MAP") or "").strip("'\"").upper() + "I")
            receives.append(area)
        if first in ("READQ", "WRITEQ") and o.get("QUEUE"):
            queues.add(o["QUEUE"])
    return {"files": files, "receives": receives, "queues": sorted(queues)}
