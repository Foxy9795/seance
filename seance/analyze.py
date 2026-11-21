"""Static analysis of COBOL programs: what discovery tools such as IBM ADDI, Rocket Enterprise Analyzer, Google MAT and
AWS Transform report before a migration, computed locally and deterministically (no language model, so the same source always
gives the same answer).

For one program: size and complexity metrics, the paragraph flow graph (PERFORM, GO TO, fall-through) with unreferenced
paragraphs, business rules in plain English (exportable as Gherkin), a data dictionary with where each field is read and
written, data lineage from input fields to output fields, and the program's external dependencies. For the workspace: a
portfolio assessment and a dependency graph.

Everything is read from the source text. Where the reader is not sure it says nothing rather than guess.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import normalize
from .layout import walk
from .model import ModelError, ProgramModel, load_model
from .recorder import ROOT
from .spec import _logical, _narrate, _symbols

VERBS = {"ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE", "EVALUATE", "EXEC", "EXIT",
         "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MERGE", "MOVE", "MULTIPLY", "OPEN", "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE",
         "SEARCH", "SET", "SORT", "START", "STOP", "STRING", "SUBTRACT", "UNSTRING", "WRITE"}
STRUCT = {"WHEN", "ELSE", "AT", "NOT", "ON", "INVALID", "THEN"}
SYSTEM_RECORDS = {"DFHAID", "DFHBMSCA", "DFHEIBLK", "SQLCA", "SQLDA", "SQLCODE", "DFHRESP"}  # supplied by CICS, DB2 or the precompilers
NOT_PARAGRAPH = VERBS | {"CONTINUE", "EXIT", "GOBACK", "DECLARATIVES", "ELSE"}
_STR = re.compile(r"'[^']*'|\"[^\"]*\"")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
_HOST = re.compile(r":([A-Za-z][A-Za-z0-9-]*)")


def _mask(text: str) -> str:
    """Upper-case the text and blank the inside of every literal, so words in a literal are never mistaken for code."""
    return _STR.sub(lambda m: m.group(0)[0] + "_" * (len(m.group(0)) - 2) + m.group(0)[0], text).upper()


def _toks(text: str) -> list[str]:
    return re.findall(r"[A-Z0-9][A-Z0-9-]*|[<>=]+|[():.,]", text)


@dataclass
class Unit:
    line: int
    indent: int
    text: str
    para: str

    @property
    def masked(self) -> str:
        return _mask(self.text)

    @property
    def first(self) -> str:
        t = _toks(self.masked)
        return t[0] if t else ""


@dataclass
class Para:
    name: str
    kind: str  # paragraph, section or start
    line: int
    section: str = ""
    units: list[Unit] = field(default_factory=list)
    end_line: int = 0


def rating(complexity: int) -> str:
    """McCabe's bands: up to 10 simple, to 20 moderate, to 50 high, beyond that very high."""
    return "Low" if complexity <= 10 else "Moderate" if complexity <= 20 else "High" if complexity <= 50 else "Very high"


def _build(lines, start: int) -> tuple[list[Para], list[Unit]]:
    """Paragraphs and statement units of the PROCEDURE DIVISION. A line that does not start a statement continues the one above."""
    logical = _logical(lines[start + 1:])
    paras: list[Para] = [Para("(start)", "start", lines[start].number)]
    units: list[Unit] = []
    section = ""
    for number, indent, text in logical:
        t = text.strip()
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9-]*)(\s+SECTION)?\s*\.", t, re.I)
        if m and len(indent) <= 3 and m.group(1).upper() not in NOT_PARAGRAPH and not re.fullmatch(r"\d+", m.group(1)):
            if m.group(2):
                section = m.group(1).upper()
            paras.append(Para(m.group(1).upper(), "section" if m.group(2) else "paragraph", number, section))
            continue
        first = (_toks(_mask(t)) or [""])[0]
        starts = first in VERBS or first in STRUCT or first.startswith("END-")
        cur = paras[-1]
        if starts or not cur.units:
            u = Unit(number, len(indent), t, cur.name)
            cur.units.append(u)
            units.append(u)
        else:
            cur.units[-1].text += " " + t
        cur.end_line = number
    paras = [p for p in paras if p.kind != "start" or p.units]
    for i, p in enumerate(paras):
        if not p.end_line:
            p.end_line = p.line
    return paras, units


# ---------------------------------------------------------------- flow
def _segments(masked: str) -> list[list[str]]:
    """Split one unit into statements at each verb, so 'AT END MOVE 1 TO X NOT AT END PERFORM Y' is two statements."""
    toks = _toks(masked)
    segs: list[list[str]] = []
    cur: list[str] = []
    depth = 0
    for i, t in enumerate(toks):
        if t == "EXEC":
            depth = 1
        if depth and t == "END-EXEC":
            depth = 0
        starts = t in VERBS and not depth and not (t == "EXEC" and cur and cur[0] == "EXEC") and not (cur and cur[-1] in ("NEXT", "END") and False)
        # EXIT PERFORM / EXIT PARAGRAPH are one statement; READ ... NEXT RECORD too
        if starts and cur and not (t == "PERFORM" and cur[-1] == "EXIT") and not (t == "GO" and cur[-1] == "STOP"):
            segs.append(cur)
            cur = []
        cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _flow(paras: list[Para], names: set[str], section_members: dict[str, list[str]]) -> tuple[list[dict], dict, list[dict]]:
    """Edges between paragraphs, which paragraphs can ever run, and the CALL/LINK/XCTL statements."""
    order = [p.name for p in paras]
    index = {n: i for i, n in enumerate(order)}
    edges: list[dict] = []
    calls: list[dict] = []
    terminal: dict[str, bool] = {}

    def span(a: str, b: str | None) -> list[str]:
        if a not in index:
            return []
        if section_members.get(a) and not b:
            return [a] + section_members[a]
        hi = index.get(b, index[a]) if b else index[a]
        return order[index[a]: max(index[a], hi) + 1]

    ranges: dict[str, list[list[str]]] = {n: [] for n in order}  # paragraph -> ranges it PERFORMs
    for p in paras:
        for u in p.units:
            masked = u.masked
            toks = _toks(masked)
            for i, t in enumerate(toks):
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if t == "PERFORM" and nxt in names:
                    b = toks[i + 3] if i + 3 < len(toks) and toks[i + 2] in ("THRU", "THROUGH") and toks[i + 3] in names else None
                    edges.append({"from": p.name, "to": nxt, "kind": "perform", "line": u.line, "thru": b})
                    ranges[p.name].append(span(nxt, b))
                elif t == "GO" and nxt == "TO":
                    j = i + 2
                    while j < len(toks) and toks[j] in names:
                        edges.append({"from": p.name, "to": toks[j], "kind": "goto", "line": u.line, "depending": "DEPENDING" in toks[j + 1: j + 3]})
                        j += 1
                elif t in ("INPUT", "OUTPUT") and nxt == "PROCEDURE":
                    j = i + 2
                    if j < len(toks) and toks[j] == "IS":
                        j += 1
                    if j < len(toks) and toks[j] in names:
                        b = toks[j + 2] if j + 2 < len(toks) and toks[j + 1] in ("THRU", "THROUGH") and toks[j + 2] in names else None
                        edges.append({"from": p.name, "to": toks[j], "kind": "perform", "line": u.line, "thru": b, "sort": True})
                        ranges[p.name].append(span(toks[j], b))
            if "EXEC CICS" in masked.replace("  ", " ") and re.search(r"\bHANDLE\b", masked):
                for h in re.findall(r"\(\s*([A-Z0-9-]+)\s*\)", masked):
                    if h in names:
                        edges.append({"from": p.name, "to": h, "kind": "handler", "line": u.line})
            for lit in re.finditer(r"\bCALL\s+(['\"])([^'\"]+)\1", u.text, re.I):
                calls.append({"target": lit.group(2).upper(), "kind": "call", "line": u.line, "dynamic": False, "from": p.name})
            for dyn in re.finditer(r"\bCALL\s+([A-Za-z][A-Za-z0-9-]*)\b", u.text, re.I):
                calls.append({"target": dyn.group(1).upper(), "kind": "call", "line": u.line, "dynamic": True, "from": p.name})
            for cm in re.finditer(r"\bEXEC\s+CICS\s+(LINK|XCTL)\b.*?\bPROGRAM\s*\(\s*(['\"])([^'\"]+)\2", u.text, re.I | re.S):
                calls.append({"target": cm.group(3).upper(), "kind": cm.group(1).lower(), "line": u.line, "dynamic": False, "from": p.name})
        last = p.units[-1] if p.units else None
        base = min((u.indent for u in p.units), default=0)
        text = _mask(last.text).rstrip(". ") if last else ""
        terminal[p.name] = bool(last and last.indent <= base and (re.fullmatch(r"(STOP RUN|GOBACK|EXIT PROGRAM)( .*)?", text) or (re.fullmatch(r"GO TO [A-Z0-9-]+", text))
                                                                   or re.search(r"\bEXEC CICS (RETURN|XCTL|ABEND)\b", text.replace("  ", " "))))
    gotos: dict[str, list[str]] = {n: [] for n in order}
    for e in edges:
        if e["kind"] in ("goto", "handler"):
            gotos[e["from"]].append(e["to"])
    live: set[str] = set()
    flowed: set[str] = set()
    work = [(order[0], "flow")] if order else []
    while work:
        name, mode = work.pop()
        if name not in index:
            continue
        again = name not in live or (mode == "flow" and name not in flowed)
        live.add(name)
        if not again:
            continue
        if mode == "flow":
            flowed.add(name)
        for rng in ranges.get(name, []):
            for m in rng:
                if m not in live:
                    work.append((m, "call"))
        for g in gotos.get(name, []):
            work.append((g, "flow"))
        if mode == "flow" and not terminal.get(name) and index[name] + 1 < len(order):
            nxt = order[index[name] + 1]
            work.append((nxt, "flow"))
            edges.append({"from": name, "to": nxt, "kind": "fall", "line": paras[index[name]].end_line})
    # a performed range also runs the paragraphs inside it, in order: they fall into each other
    for p in paras:
        for rng in ranges.get(p.name, []):
            for a, b in zip(rng, rng[1:]):
                if not any(e["from"] == a and e["to"] == b and e["kind"] == "fall" for e in edges):
                    edges.append({"from": a, "to": b, "kind": "fall", "line": paras[index[a]].end_line})
    return edges, {"live": live, "entry": order[0] if order else None}, calls


# ---------------------------------------------------------------- data effects
_TARGET_AFTER = {"TO": 1, "INTO": 1, "GIVING": 1}


def _effects(seg: list[str], names: set[str]) -> tuple[set[str], set[str]]:
    """(reads, writes) of one statement, by the rules of the verb."""
    if not seg:
        return set(), set()
    verb = seg[0]
    body = seg[1:]
    ds = [t for t in body if t in names]
    reads, writes = set(), set()
    rounded = lambda toks: [t for t in toks if t not in ("ROUNDED", "ON", "SIZE", "ERROR")]  # noqa: E731
    if verb == "MOVE" and "TO" in body:
        i = body.index("TO")
        reads |= {t for t in body[:i] if t in names}
        writes |= {t for t in body[i + 1:] if t in names}
    elif verb == "COMPUTE" and "=" in body:
        i = body.index("=")
        writes |= {t for t in rounded(body[:i]) if t in names}
        reads |= {t for t in body[i + 1:] if t in names}
    elif verb in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
        joiner = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[verb]
        if "GIVING" in body:
            g = body.index("GIVING")
            reads |= {t for t in body[:g] if t in names}
            writes |= {t for t in rounded(body[g + 1:]) if t in names and t != "REMAINDER"}
            if "REMAINDER" in body:
                writes |= {t for t in body[body.index("REMAINDER") + 1:] if t in names}
        elif joiner in body or (verb == "DIVIDE" and "BY" in body):
            j = body.index(joiner) if joiner in body else body.index("BY")
            reads |= {t for t in body[:j] if t in names}
            for t in body[j + 1:]:
                if t in names:
                    writes.add(t)
                    reads.add(t)
        else:
            reads |= set(ds)
    elif verb in ("STRING", "UNSTRING") and "INTO" in body:
        i = body.index("INTO")
        reads |= {t for t in body[:i] if t in names}
        writes |= {t for t in body[i + 1:] if t in names and t not in ("WITH", "POINTER", "TALLYING")}
        if "POINTER" in body:
            p = body.index("POINTER")
            if p + 1 < len(body) and body[p + 1] in names:
                writes.add(body[p + 1]); reads.add(body[p + 1])
    elif verb == "READ" and "INTO" in body:
        i = body.index("INTO")
        reads |= {t for t in body[:i] if t in names}
        writes |= {t for t in body[i + 1:i + 2] if t in names}
        if "KEY" in body:
            reads |= {t for t in body[body.index("KEY") + 1:] if t in names}
    elif verb in ("WRITE", "REWRITE") and "FROM" in body:
        i = body.index("FROM")
        writes |= {t for t in body[:i] if t in names}
        reads |= {t for t in body[i + 1:] if t in names}
    elif verb == "ACCEPT":
        writes |= {t for t in body[:1] if t in names}
    elif verb in ("INITIALIZE", "SET"):
        if verb == "SET" and ("UP" in body or "DOWN" in body):
            writes |= set(ds[:1]); reads |= set(ds[:1]) | set(ds[1:])
        elif verb == "SET" and "TO" in body:
            i = body.index("TO")
            writes |= {t for t in body[:i] if t in names}
            reads |= {t for t in body[i + 1:] if t in names}
        else:
            writes |= {t for t in body if t in names and t not in ("REPLACING", "WITH", "ALL", "TO")}
    elif verb == "INSPECT":
        if ds:
            writes.add(ds[0]); reads.add(ds[0]); reads |= set(ds[1:])
    elif verb == "CALL":
        for t in ds:
            reads.add(t); writes.add(t)  # BY REFERENCE: the callee may change it
    elif verb == "EXEC":
        # EXEC SQL: host variables after INTO are written; EXEC CICS: INTO( ) and RESP( ) are written
        text = re.sub(r":\s+", ":", " ".join(body))
        if body[:1] == ["SQL"]:
            into = re.search(r"\bINTO\b(.*?)(?:\bFROM\b|\bWHERE\b|\bEND-EXEC\b|$)", text)
            written = set(_HOST.findall(into.group(1))) if into else set()
            writes |= {w for w in (x.upper() for x in written) if w in names}
            reads |= {t.upper() for t in _HOST.findall(text) if t.upper() in names} - writes
        else:
            for opt, names_ in re.findall(r"\b(INTO|RESP2?|SET|ITEM|ABSTIME)\s*\(\s*([A-Z0-9-]+)\s*\)", text):
                if names_ in names:
                    writes.add(names_)
            reads |= {t for t in body if t in names} - writes
    else:
        reads |= set(ds)
    return reads, writes


# ---------------------------------------------------------------- plain English
_OPS = [
    (r" NOT (?:EQUAL TO|EQUAL|=) ", " does not equal "), (r" <> ", " does not equal "),
    (r" (?:IS )?NOT (?:GREATER THAN|>) ", " is not greater than "), (r" (?:IS )?NOT (?:LESS THAN|<) ", " is not less than "),
    (r" (?:IS )?(?:GREATER THAN OR EQUAL TO|GREATER OR EQUAL TO|>=) ", " is at least "),
    (r" (?:IS )?(?:LESS THAN OR EQUAL TO|LESS OR EQUAL TO|<=) ", " is at most "),
    (r" (?:IS )?(?:GREATER THAN|>) ", " is greater than "), (r" (?:IS )?(?:LESS THAN|<) ", " is less than "),
    (r" (?:IS )?(?:EQUAL TO|=) ", " equals "),
    (r" IS NOT NUMERIC ", " is not numeric "), (r" IS NUMERIC ", " is numeric "),
    (r" IS NOT ALPHABETIC ", " is not alphabetic "), (r" IS ALPHABETIC ", " is alphabetic "),
    (r" AND ", " and "), (r" OR ", " or "),
]


def plain(cond: str, cond88: dict[str, str] | None = None) -> str:
    """A COBOL condition in plain words. Literals are left exactly as written."""
    parts = re.split(r"('[^']*'|\"[^\"]*\")", re.sub(r"\s+", " ", cond.strip().rstrip(".")))
    out = []
    for i, seg in enumerate(parts):
        if i % 2 == 0:
            lead, trail = seg[: len(seg) - len(seg.lstrip())], seg[len(seg.rstrip()):]
            s = f" {seg.strip()} "
            for pat, rep in _OPS:
                s = re.sub(pat, rep, s, flags=re.I)
            seg = lead + s.strip() + trail
            if cond88:
                seg = re.sub(r"[A-Za-z][A-Za-z0-9-]*", lambda m: f"{m.group(0)} ({cond88[m.group(0).upper()]})" if m.group(0).upper() in cond88 else m.group(0), seg)
        out.append(seg)
    return "".join(out).strip()


def _fmt(v) -> str:
    return f"'{v}'" if isinstance(v, str) and v not in ("SPACE", "SPACES", "ZERO", "ZEROS", "HIGH-VALUE", "LOW-VALUE") else str(v)


def _cond88(model: ProgramModel) -> dict[str, str]:
    out: dict[str, str] = {}
    roots = [r for f in model.files for r in f.records] + list(model.ws_records) + list(model.linkage_records)
    for r in roots:
        for it in walk(r):
            for name, choices in it.conds:
                vals = []
                for lo, hi in choices:
                    vals.append(_fmt(lo) if hi is None or lo == hi else f"{_fmt(lo)} to {_fmt(hi)}")
                out[name.upper()] = f"{it.name} = {' or '.join(vals)}" if vals else it.name
    return out


def _lc(s: str) -> str:
    """Lower-case the first letter of a sentence unless it starts with a data name (two capitals)."""
    return s if s[:2].isupper() or not s else s[0].lower() + s[1:]


def _split_handler(sentence: str) -> tuple[str, str]:
    """'When the file is exhausted: copies X' -> ('the file is exhausted', 'copies X')."""
    if sentence.startswith("When ") and ": " in sentence:
        a, b = sentence[5:].split(": ", 1)
        return a, b
    m = re.match(r"If (.+?), (sets .+|moves .+|.+)$", sentence)
    if sentence.startswith("If ") and m:
        return m.group(1), m.group(2)
    return "", sentence


def _rules(paras: list[Para], table, cond88: dict[str, str]) -> list[dict]:
    """Decisions, cases, calculations, loops and handlers, each with what happens in plain words, in source order."""
    rules: list[dict] = []
    covered: set[int] = set()

    def say(u: Unit) -> str:
        return _narrate(u.text, table) or ""

    def block(units: list[Unit], i: int, indent: int) -> tuple[list[Unit], int]:
        got, j = [], i
        while j < len(units) and units[j].indent > indent:
            got.append(units[j])
            j += 1
        return got, j

    def sentences(us: list[Unit]) -> list[str]:
        """What the statements directly inside a branch do. Deeper ones are described by their own rule."""
        base = min((x.indent for x in us), default=0)
        out = []
        for x in us:
            if x.indent != base or x.first in ("IF", "EVALUATE", "WHEN", "ELSE") or x.first.startswith("END-"):
                continue
            covered.add(id(x))
            if sentence := say(x):
                out.append(sentence)
        return out[:6]

    def loop_text(u: Unit) -> str:
        sentence = say(u)
        m = re.search(r"\bUNTIL\b(.*)$", u.text, re.I)
        if sentence and m and "until" in sentence.lower():
            sentence = sentence[: sentence.lower().rfind("until")] + "until " + plain(m.group(1), cond88) + "."
        return sentence or re.sub(r"\s+", " ", u.text)

    # pass 1: decisions and cases, which mark the statements they already describe
    for p in paras:
        us = p.units
        for i, u in enumerate(us):
            m = _mask(u.text)
            if u.first == "IF":
                verb = re.search(r"\b(" + "|".join(sorted(VERBS - {"IF"})) + r")\b", m)
                cond_text = re.sub(r"\bTHEN\b", "", u.text[2:verb.start()] if verb else u.text[2:], flags=re.I)
                then_us, j = block(us, i + 1, u.indent)
                if verb:  # statements on the same line as the condition
                    then_us = [Unit(u.line, u.indent + 1, u.text[verb.start():], p.name)] + then_us
                other: list[Unit] = []
                if j < len(us) and us[j].first == "ELSE" and us[j].indent == u.indent:
                    other, _ = block(us, j + 1, u.indent)
                rules.append({"kind": "decision", "paragraph": p.name, "line": u.line, "when": plain(cond_text, cond88), "then": sentences(then_us), "otherwise": sentences(other)})
            elif u.first == "EVALUATE":
                subject = re.sub(r"^EVALUATE\s+", "", u.text, flags=re.I).rstrip(".")
                j = i + 1
                while j < len(us) and not (us[j].first.startswith("END-") and us[j].indent <= u.indent):
                    if us[j].first == "WHEN" and us[j].indent > u.indent:
                        cond = re.sub(r"^WHEN\s+", "", us[j].text, flags=re.I)
                        body, _ = block(us, j + 1, us[j].indent)
                        when = "in every other case" if re.match(r"OTHER\b", cond, re.I) else plain(cond, cond88) if subject.upper() == "TRUE" else f"{subject} is {plain(cond, cond88)}"
                        rules.append({"kind": "case", "paragraph": p.name, "line": us[j].line, "when": when, "then": sentences(body), "otherwise": []})
                    j += 1
    # pass 2: what is left
    for p in paras:
        us = p.units
        for i, u in enumerate(us):
            if id(u) in covered:
                continue
            f, m = u.first, _mask(u.text)
            if f in ("COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE") and (s := say(u)):
                guard = ""
                if i + 1 < len(us) and us[i + 1].first == "ON" and "SIZE ERROR" in _mask(us[i + 1].text):
                    guard = say(us[i + 1]) or "handles a result that does not fit"
                elif "SIZE ERROR" in m:
                    guard = "handles a result that does not fit"
                rules.append({"kind": "calculation", "paragraph": p.name, "line": u.line, "when": "", "then": [s], "otherwise": [], "rounding": "half away from zero" if "ROUNDED" in m else "truncated", "guard": guard})
            elif f == "PERFORM" and re.search(r"\b(UNTIL|VARYING|TIMES|FOREVER)\b", m):
                rules.append({"kind": "loop", "paragraph": p.name, "line": u.line, "when": "", "then": [loop_text(u)], "otherwise": []})
            elif f in ("ON", "AT", "INVALID", "NOT") and re.search(r"\b(SIZE ERROR|AT END|INVALID KEY|EXCEPTION)\b", m) and (s := say(u)):
                when, then = _split_handler(s)
                rules.append({"kind": "handler", "paragraph": p.name, "line": u.line, "when": when, "then": [then[0].upper() + then[1:] if then else then], "otherwise": []})
    rules.sort(key=lambda r: (r["line"], {"decision": 0, "case": 1, "loop": 2, "handler": 3, "calculation": 4}[r["kind"]]))
    for n, r in enumerate(rules, 1):
        r["id"] = f"R{n}"
    return rules


def gherkin(a: dict) -> str:
    """The business rules as Gherkin scenarios (the format AWS Transform also writes its extracted rules in)."""
    def steps(first: str, lines: list[str]) -> list[str]:
        return [f"    {first if i == 0 else 'And'} {_lc(s.rstrip('.'))}" for i, s in enumerate(lines)]

    out = [f"Feature: {a['program_id'] or a['name'].upper()}", f"  # Business rules read from {a['file']} by Séance (static analysis, no AI).", ""]
    for r in a["rules"]:
        title = f"  Scenario: {r['id']} {r['paragraph']}, line {r['line']}"
        if r["kind"] in ("decision", "case"):
            out += [title, f"    Given {_lc(r['when'])}"] + steps("Then", r["then"] or ["nothing else happens"])
            if r["otherwise"]:
                out += ["", f"  Scenario: {r['id']} otherwise, line {r['line']}", f"    Given it is not the case that {_lc(r['when'])}"] + steps("Then", r["otherwise"])
        elif r["kind"] == "calculation":
            out += [title, f"    When {r['paragraph']} runs"] + steps("Then", r["then"])
            if r.get("guard"):
                out += [f"    And {_lc(r['guard'].rstrip('.'))}"]
        elif r["kind"] == "handler":
            out += [title, f"    Given {_lc(r['when'])}" if r["when"] else f"    When {r['paragraph']} runs"] + steps("Then", r["then"])
        else:
            out += [title, f"    When {r['paragraph']} runs"] + steps("Then", r["then"])
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- one program
def _decisions(masked: str) -> int:
    n = len(re.findall(r"(?<![A-Z0-9-])IF(?![A-Z0-9-])", masked))
    n += len(re.findall(r"(?<![A-Z0-9-])WHEN(?!\s+OTHER)(?![A-Z0-9-])", masked))
    n += len(re.findall(r"(?<![A-Z0-9-])UNTIL(?![A-Z0-9-])", masked))
    n += len(re.findall(r"(?<!NOT )(?<!NOT  )ON SIZE ERROR", masked)) + len(re.findall(r"(?<!NOT )AT END", masked))
    n += len(re.findall(r"(?<!NOT )INVALID KEY", masked)) + len(re.findall(r"(?<!NOT )ON EXCEPTION", masked))
    n += len(re.findall(r"DEPENDING ON", masked))
    return n


def _unit_analysis(model: ProgramModel, path: Path, fixed: bool, program_id: str, label: str, subs_ids: set[str]) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    own = normalize(text, fixed)  # the file as written, for its size
    lines = normalize(text, fixed, model.copy_dirs or None) if model.copy_dirs else own  # what cobc reads: COPY expanded
    raw_lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if not l.comment and l.text.strip().upper().startswith("PROCEDURE DIVISION")), None)
    blank = sum(1 for l in raw_lines if not l.strip())
    comment = sum(1 for l in own if l.comment and l.text.strip())
    code = [l for l in own if not l.comment and l.text.strip()]
    metrics = {"lines": len(raw_lines), "code": len(code), "comments": comment, "blank": blank}
    if start is None:
        return {"name": label, "program_id": program_id, "file": path.name, "metrics": metrics, "paragraphs": [], "edges": [], "rules": [], "dictionary": [], "lineage": [], "calls": [], "error": "no PROCEDURE DIVISION"}
    paras, units = _build(lines, start)
    names_order = [p.name for p in paras]
    section_members: dict[str, list[str]] = {}
    for p in paras:
        if p.section and p.kind == "paragraph":
            section_members.setdefault(p.section, []).append(p.name)
    pnames = set(names_order) - {"(start)"}
    edges, flow, calls = _flow(paras, pnames, section_members)
    table = _symbols(lines[:start], model)
    cond88 = _cond88(model)
    rules = _rules(paras, table, cond88)

    # per paragraph numbers
    decisions_by: dict[str, int] = {}
    stmts_by: dict[str, int] = {}
    io_by: dict[str, dict[str, set]] = {}
    file_of_record = {r.name.upper(): f for f in model.files for r in f.records}
    file_by_name = {f.name.upper(): f for f in model.files}
    for p in paras:
        d = s = 0
        io = {"reads": set(), "writes": set()}
        for u in p.units:
            masked = u.masked
            d += _decisions(masked)
            for seg in _segments(masked):
                if seg and seg[0] in VERBS:
                    s += 1
                    verb = seg[0]
                    if verb == "READ" and len(seg) > 1 and seg[1] in file_by_name:
                        io["reads"].add(file_by_name[seg[1]].assign)
                    elif verb in ("WRITE", "REWRITE") and len(seg) > 1 and seg[1] in file_of_record:
                        io["writes"].add(file_of_record[seg[1]].assign)
                    elif verb == "OPEN":
                        mode = None
                        for t in seg[1:]:
                            if t in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                                mode = t
                            elif t in file_by_name and mode:
                                (io["reads"] if mode == "INPUT" else io["writes"]).add(file_by_name[t].assign)
        decisions_by[p.name], stmts_by[p.name], io_by[p.name] = d, s, io
    total_decisions = sum(decisions_by.values())
    total_masked = " ".join(u.masked for u in units)
    totals = Counter_(total_masked)

    # cross reference over every name in the data division
    ours = lambda r: r.name.upper() not in SYSTEM_RECORDS and not r.name.upper().startswith(("CIB-", "SQB-"))  # noqa: E731
    roots = [("File", f.assign, r) for f in model.files for r in f.records[:1] if f.organization not in ("sqldb", "cicsdb")] + [("Working-Storage", "", r) for r in model.ws_records if ours(r)] + [("Linkage", "", r) for r in model.linkage_records if ours(r)]
    items: dict[str, tuple] = {}
    for section, owner, r in roots:
        for it in walk(r):
            if it.name and it.name.upper() != "FILLER":
                items.setdefault(it.name.upper(), (section, owner, r, it))
    names = set(items) | set(cond88) | {f.name.upper() for f in model.files}
    for fdef in model.files:
        if fdef.status:
            names.add(fdef.status.upper())
    refs: dict[str, list[dict]] = {}
    lineage: dict[str, set[str]] = {}
    for p in paras:
        for u in p.units:
            masked = u.masked
            for seg in _segments(masked):
                if not seg:
                    continue
                s = seg[:]
                while s and s[0] in ("NOT", "AT", "END", "ON", "SIZE", "ERROR", "INVALID", "KEY", "ELSE", "THEN", "EXCEPTION"):
                    s = s[1:]
                if s and s[0] == "WHEN":
                    s = ["WHEN"] + s[1:]
                reads, writes = _effects(s, names) if s and s[0] in VERBS else ({t for t in s if t in names}, set())
                for n in reads | writes:
                    mode = "rw" if n in reads and n in writes else "w" if n in writes else "r"
                    refs.setdefault(n, []).append({"line": u.line, "paragraph": p.name, "mode": mode})
                for w in writes:
                    lineage.setdefault(w, set()).update(reads - {w})
    dictionary = []
    for name, (section, owner, rec, it) in items.items():
        rs = refs.get(name, [])
        # a group's fields count as used when the group is moved or read whole
        used = bool(rs) or any(refs.get(c.name.upper()) for c in walk(it) if c is not it) or any(refs.get(a.name.upper()) for a in _ancestors(it))
        dictionary.append({
            "name": name, "section": section, "record": rec.name, "level": it.level, "kind": it.kind, "usage": it.usage, "pic": it.pic, "bytes": it.size, "offset": it.offset + 1,
            "digits": it.digits, "scale": it.scale, "signed": it.signed, "occurs": it.occurs, "redefines": it.redefines, "value": None if it.value is None else str(it.value),
            "conditions": [n for n, _c in it.conds], "reads": sum(1 for x in rs if "r" in x["mode"]), "writes": sum(1 for x in rs if "w" in x["mode"]),
            "lines": sorted({x["line"] for x in rs})[:60], "paragraphs": sorted({x["paragraph"] for x in rs}), "unused": section != "File" and not used and not it.redefines and it.level < 88,
            "file": owner,
        })
    # lineage: which input fields reach each output field, through which intermediate fields
    inputs = {n for n, v in items.items() if v[0] == "File" and any(f.is_input and f.assign == v[1] for f in model.files)}
    outputs = {n for n, v in items.items() if v[0] == "File" and any(f.is_output and f.assign == v[1] for f in model.files) and v[3].kind != "group"}
    out_lineage = []
    for o in sorted(outputs):
        seen, stack, via, src = set(), [o], set(), set()
        while stack:
            cur = stack.pop()
            for s_ in lineage.get(cur, ()):
                if s_ in seen:
                    continue
                seen.add(s_)
                if s_ in inputs:
                    src.add(s_)
                else:
                    via.add(s_)
                stack.append(s_)
        if src or via:
            out_lineage.append({"field": o, "from": sorted(src), "via": sorted(via - src), "file": items[o][1]})

    copybooks = sorted({m.upper() for m in re.findall(r"\bCOPY\s+([A-Za-z0-9-]+)", "\n".join(l.text for l in lines if not l.comment), re.I)})
    sql_stmts = re.findall(r"\bEXEC\s+SQL\b(.*?)\bEND-EXEC", " ".join(l.text for l in code), re.I | re.S)
    cics_stmts = re.findall(r"\bEXEC\s+CICS\b(.*?)\bEND-EXEC", " ".join(l.text for l in code), re.I | re.S)
    sql_tables = sorted({t.upper() for s_ in sql_stmts for t in re.findall(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([A-Za-z][A-Za-z0-9_.$#@-]*)", s_, re.I) if not t.startswith(":")} - {"SQLCA"})
    cics_res = sorted({f"{k.upper()} {v}" for s_ in cics_stmts for k, v in re.findall(r"\b(FILE|DATASET|MAP|QUEUE|TRANSID|PROGRAM)\s*\(\s*['\"]([^'\"]+)['\"]", s_, re.I)})
    for c in calls:
        c["resolved"] = c["target"] in subs_ids
    unref = [p.name for p in paras if p.kind != "section" and p.name != "(start)" and p.name not in flow["live"]]
    complexity = 1 + total_decisions
    paragraph_info = [{
        "name": p.name, "kind": p.kind, "line": p.line, "end": p.end_line, "section": p.section, "statements": stmts_by[p.name], "complexity": 1 + decisions_by[p.name],
        "live": p.name in flow["live"] or p.kind == "section", "entry": p.name == flow["entry"], "reads": sorted(io_by[p.name]["reads"]), "writes": sorted(io_by[p.name]["writes"]),
    } for p in paras]
    metrics.update({"paragraphs": sum(1 for p in paras if p.kind == "paragraph"), "sections": sum(1 for p in paras if p.kind == "section"), "statements": sum(stmts_by.values()),
                    "complexity": complexity, "rating": rating(complexity), "goto": totals["GO TO"], "performs": totals["PERFORM"], "ifs": totals["IF"], "evaluates": totals["EVALUATE"],
                    "calls": len([c for c in calls if c["kind"] == "call"]), "sql": len(sql_stmts), "cics": len(cics_stmts), "files": len(model.files), "copybooks": len(copybooks),
                    "data_items": len(items), "unreferenced": len(unref), "unused_data": sum(1 for d in dictionary if d["unused"]),
                    "deepest": max((u.indent for u in units), default=0) // 4 + 1})
    return {"name": label, "program_id": program_id, "file": path.name, "metrics": metrics, "paragraphs": paragraph_info,
            "edges": [dict(e) for e in _dedupe(edges)], "unreferenced": unref, "rules": rules, "dictionary": dictionary, "lineage": out_lineage, "calls": calls,
            "files": [{"name": f.name, "assign": f.assign, "organization": f.organization, "mode": "input" if f.is_input and not f.is_output else "output" if f.is_output and not f.is_input else "update", "record": f.record.name if f.record else None, "size": f.size} for f in model.files if f.organization not in ("sqldb", "cicsdb")],
            "copybooks": copybooks, "sql_tables": sql_tables, "cics_resources": cics_res, "error": None}


def Counter_(masked: str) -> dict:
    """Counts of the statement kinds that matter for assessment."""
    class C(dict):
        def __missing__(self, k):
            return 0
    c = C()
    c["GO TO"] = len(re.findall(r"(?<![A-Z0-9-])GO\s+TO(?![A-Z0-9-])", masked))
    c["PERFORM"] = len(re.findall(r"(?<![A-Z0-9-])PERFORM(?![A-Z0-9-])", masked))
    c["IF"] = len(re.findall(r"(?<![A-Z0-9-])IF(?![A-Z0-9-])", masked))
    c["EVALUATE"] = len(re.findall(r"(?<![A-Z0-9-])EVALUATE(?![A-Z0-9-])", masked))
    return c


def _ancestors(it):
    p = it.parent
    while p is not None:
        yield p
        p = p.parent


def _dedupe(edges: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["kind"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def analyze(program: str, root: Path = ROOT) -> dict:
    """Everything the analysis tab shows for one program (and, in `called`, the same figures for each program it CALLs)."""
    from .jobs import job_names

    if program in job_names(root):
        return analyze_job(program, root)
    try:
        model = load_model(program, root)
    except ModelError as exc:
        raise ValueError(str(exc)) from exc
    subs = model._every()[1:]
    sub_ids = {m.program_id.upper() for m in subs}
    main = _unit_analysis(model, model.path, model.fixed, model.program_id, program, sub_ids)
    main["called"] = [_unit_analysis(m, m.path, m.fixed, m.program_id, m.program_id.lower(), set()) for m in subs]
    for c in main["called"]:
        c.pop("dictionary", None); c.pop("lineage", None)
    main["job"] = False
    return main


def analyze_job(name: str, root: Path = ROOT) -> dict:
    from .jobs import UTILITIES, describe, job_programs

    d = describe(name, root)
    text = (root / "legacy" / name / f"{name}.jcl").read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    steps = d["steps"]
    edges = [{"from": a["step"], "to": b["step"], "kind": "fall", "line": b["line"]} for a, b in zip(steps, steps[1:])]
    paragraphs = [{"name": s["step"], "kind": "step", "line": s["line"], "end": s["line"], "section": "", "statements": 1, "complexity": 1 + len(s["cond"]) + len(s["when"]), "live": True, "entry": i == 0,
                   "reads": [], "writes": [], "label": s["pgm"], "condition": " ".join([f"COND=({c[0]},{c[1]})" for c in s["cond"]] + [w[0] for w in s["when"]])} for i, s in enumerate(steps)]
    return {"name": name, "program_id": d["job"].upper(), "file": f"{name}.jcl", "job": True, "metrics": {"lines": len(lines), "code": sum(1 for l in lines if l.startswith("//") and not l.startswith("//*")),
            "comments": sum(1 for l in lines if l.startswith("//*")), "blank": sum(1 for l in lines if not l.strip()), "steps": len(steps), "programs": len(job_programs(name, root)),
            "utilities": sum(1 for s in steps if s["pgm"] in UTILITIES), "complexity": 1 + sum(len(s["cond"]) + len(s["when"]) for s in steps), "rating": rating(1 + sum(len(s["cond"]) + len(s["when"]) for s in steps)),
            "paragraphs": len(steps), "statements": len(steps), "goto": 0, "calls": 0, "sql": 0, "cics": 0, "files": len(d["inputs"]), "copybooks": 0, "data_items": 0, "unreferenced": 0, "unused_data": 0, "performs": 0, "ifs": sum(1 for s in steps if s["when"]), "evaluates": 0, "deepest": 1},
            "paragraphs": paragraphs, "edges": edges, "unreferenced": [], "rules": [], "dictionary": [], "lineage": [], "calls": [{"target": s["program"], "kind": "step", "line": s["line"], "dynamic": False, "resolved": True, "from": s["step"]} for s in steps if s["program"]],
            "files": [{"name": i, "assign": i, "organization": "dataset", "mode": "input", "record": None, "size": 0} for i in d["inputs"]], "copybooks": [], "sql_tables": [], "cics_resources": [], "called": [], "error": None}


# ---------------------------------------------------------------- the whole workspace
def portfolio(root: Path = ROOT) -> dict:
    """The assessment of every program and job: a table of figures and a dependency graph."""
    from .jobs import job_info, job_names
    from .programs import program_info, program_names

    rows, nodes, edges = [], {}, []

    def node(id_: str, kind: str, label: str) -> None:
        nodes.setdefault(id_, {"id": id_, "kind": kind, "label": label})

    for name in program_names(root):
        info = program_info(name, root)
        try:
            a = analyze(name, root)
        except ValueError as exc:
            rows.append({"name": name, "title": info["title"], "kind": "program", "error": str(exc)})
            continue
        m = a["metrics"]
        called_m = [c["metrics"] for c in a["called"]]
        draft = info.get("draft") or {}
        gaps = draft.get("gaps")
        last = (info["implementations"][0].get("last_check") or {}) if info["implementations"] else {}
        status = "Cannot read" if info.get("error") else "Not translated" if not draft.get("translated") else ("Needs work" if gaps else "Ready")
        rows.append({"name": name, "title": info["title"], "kind": "program", "format": info.get("format"), "lines": m["lines"] + sum(c["lines"] for c in called_m), "code": m["code"] + sum(c["code"] for c in called_m),
                     "comments": m["comments"], "paragraphs": m["paragraphs"], "statements": m["statements"] + sum(c.get("statements", 0) for c in called_m), "complexity": max([m["complexity"]] + [c.get("complexity", 0) for c in called_m]),
                     "rating": rating(max([m["complexity"]] + [c.get("complexity", 0) for c in called_m])), "goto": m["goto"], "calls": m["calls"], "copybooks": m["copybooks"], "files": m["files"], "sql": m["sql"], "cics": m["cics"],
                     "unreferenced": m["unreferenced"], "unused_data": m["unused_data"], "gaps": gaps, "readiness": status, "verdict": last.get("verdict"), "checked_current": last.get("current"),
                     "compared": last.get("compared"), "coverage": last.get("coverage"), "kinds": info.get("kinds", []), "sample": info.get("sample", False), "error": None})
        node(name, "program", info["title"])
        own = {sub["program_id"].upper() for sub in a["called"]}
        for sub in a["called"]:
            node(sub["program_id"].lower(), "called", sub["program_id"])
        for c in a["calls"]:
            if c["kind"] in ("call", "link", "xctl") and not c["dynamic"]:
                tid = c["target"].lower()
                node(tid, "program" if tid in program_names(root) else "called" if c["target"] in own else "missing", c["target"])
                edges.append({"from": name, "to": tid, "kind": c["kind"]})
        for f in a["files"]:
            fid = "file:" + f["assign"]
            node(fid, "file", f["assign"])
            edges.append({"from": name, "to": fid, "kind": "writes" if f["mode"] == "output" else "reads" if f["mode"] == "input" else "updates"})
        for t in a["sql_tables"]:
            node("table:" + t, "table", t)
            edges.append({"from": name, "to": "table:" + t, "kind": "sql"})
    for name in job_names(root):
        info = job_info(name, root)
        try:
            a = analyze_job(name, root)
        except Exception as exc:  # a job that cannot be read still gets a row
            rows.append({"name": name, "title": info["title"], "kind": "job", "error": str(exc)})
            continue
        m = a["metrics"]
        last = (info["implementations"][0].get("last_check") or {}) if info.get("implementations") else {}
        rows.append({"name": name, "title": info["title"], "kind": "job", "format": "jcl", "lines": m["lines"], "code": m["code"], "comments": m["comments"], "paragraphs": m["steps"], "statements": m["steps"],
                     "complexity": m["complexity"], "rating": m["rating"], "goto": 0, "calls": m["programs"], "copybooks": 0, "files": m["files"], "sql": 0, "cics": 0, "unreferenced": 0, "unused_data": 0, "gaps": 0,
                     "readiness": "Needs work" if info.get("error") else "Ready", "verdict": last.get("verdict"), "checked_current": last.get("current"), "compared": last.get("compared"), "coverage": None, "kinds": ["jcl"],
                     "sample": info.get("sample", False), "error": None})
        node(name, "job", info["title"])
        for s in a["calls"]:
            tid = s["target"]
            node(tid, "program", tid)
            edges.append({"from": name, "to": tid, "kind": "step"})
    ok = [r for r in rows if not r.get("error")]
    totals = {"programs": sum(1 for r in ok if r["kind"] == "program"), "jobs": sum(1 for r in ok if r["kind"] == "job"), "lines": sum(r["lines"] for r in ok), "code": sum(r["code"] for r in ok),
              "statements": sum(r["statements"] for r in ok), "ready": sum(1 for r in ok if r["readiness"] == "Ready"), "needs_work": sum(1 for r in ok if r["readiness"] != "Ready"),
              "high_complexity": sum(1 for r in ok if r["rating"] in ("High", "Very high")), "uses_sql": sum(1 for r in ok if r["sql"]), "uses_cics": sum(1 for r in ok if r["cics"]),
              "verified": sum(1 for r in ok if r["verdict"] and "matched" in str(r["verdict"]).lower() and r["checked_current"])}
    # waves: programs with nothing they depend on first (the order a migration can follow)
    deps = {n: {e["to"] for e in edges if e["from"] == n and e["to"] in nodes and nodes[e["to"]]["kind"] in ("program", "job") and e["to"] != n} for n in nodes if nodes[n]["kind"] in ("program", "job")}
    waves, done = [], set()
    while deps and len(done) < len(deps):
        wave = sorted(n for n, d in deps.items() if n not in done and d <= done)
        if not wave:
            wave = sorted(n for n in deps if n not in done)  # a cycle: take what is left together
        waves.append(wave)
        done |= set(wave)
    return {"rows": rows, "totals": totals, "nodes": list(nodes.values()), "edges": edges, "waves": waves}


COLUMNS = [("title", "Program"), ("kind", "Kind"), ("format", "Format"), ("lines", "Lines"), ("code", "Code lines"), ("comments", "Comment lines"), ("paragraphs", "Paragraphs or steps"), ("statements", "Statements"),
           ("complexity", "Complexity"), ("rating", "Rating"), ("goto", "GO TO"), ("calls", "CALLs"), ("copybooks", "Copybooks"), ("files", "Files"), ("sql", "SQL statements"), ("cics", "CICS commands"),
           ("unreferenced", "Unreferenced paragraphs"), ("unused_data", "Unused data items"), ("gaps", "Statements needing a person"), ("readiness", "Migration readiness"), ("verdict", "Last check"),
           ("compared", "Lines compared"), ("coverage", "Coverage %")]


def portfolio_csv(p: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([h for _k, h in COLUMNS])
    for r in p["rows"]:
        w.writerow([("" if r.get(k) is None else r.get(k)) for k, _h in COLUMNS] if not r.get("error") else [r["title"], r["kind"], "cannot read: " + r["error"][:80]])
    return out.getvalue()
