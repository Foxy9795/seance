"""Turn a COBOL program into a plain-English spec, linked to source line numbers.

This is a rule-based reader, not a language model. It narrates only the statements it
recognizes with confidence and lists the rest under "Needs human review", so a wrong
sentence never hides in the description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cobol_src import Line, normalize
from .layout import Item, leaves, walk
from .model import ModelError, ProgramModel, load_model

ROOT = Path(__file__).resolve().parent.parent

_PIC = re.compile(r"^\s*(\d{2})\s+([A-Z0-9-]+)\s+PIC(?:TURE)?\s+(?:IS\s+)?(\S+)", re.I)
_CONTINUES = re.compile(r"(=|[-+*/(]|\*\*)$")


@dataclass
class Capacity:
    digits: int
    scale: int
    signed: bool

    def describe(self) -> str:
        int_digits = self.digits - self.scale
        top = "9" * int_digits + ("." + "9" * self.scale if self.scale else "")
        return f"holds {'+/-' if self.signed else ''}{top} at most"


@dataclass
class Spec:
    program: str
    markdown: str
    review: list[str] = field(default_factory=list)


def _symbols(lines: list[Line], model: ProgramModel) -> dict[str, Capacity]:
    table: dict[str, Capacity] = {}
    roots = [r for f in model.files for r in f.records] + list(model.ws_records)
    for root in roots:
        for it in walk(root):
            if it.kind == "num":
                table[it.name] = Capacity(it.digits, it.scale, it.signed)
    return table


def _cap_note(target: str, table: dict[str, Capacity]) -> str:
    cap = table.get(target)
    return f" ({target} {cap.describe()}; larger values lose their leading digits)" if cap else ""


_FOR = {"ROUNDED": "rounded half away from zero"}


_VERB = re.compile(r"\b(MOVE|COMPUTE|ADD|SUBTRACT|MULTIPLY|DIVIDE|DISPLAY|PERFORM|SET|INITIALIZE|CONTINUE|GO TO|EXIT|WRITE|READ|REWRITE|"
                   r"DELETE|START|STRING|UNSTRING|INSPECT|CALL|STOP RUN|GOBACK|ACCEPT|SEARCH|RELEASE|RETURN|NEXT SENTENCE)\b")


def _split_inline(t: str) -> tuple[str, str | None]:
    """WHEN "F" MOVE .05 TO RATE -> ('"F"', 'MOVE .05 TO RATE'). Words inside quotes never count as a verb."""
    plain = re.sub(r"'[^']*'|\"[^\"]*\"", lambda m: "_" * len(m.group(0)), t)
    m = _VERB.search(plain)
    if not m or m.start() == 0:
        return t, None
    return t[: m.start()].strip(), t[m.start():].strip()


def _lower_first(s: str) -> str:
    return s if s[:2].isupper() else s[:1].lower() + s[1:]


def _list(names: str) -> str:
    parts = [p for p in re.split(r"[\s,]+", names.strip()) if p]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _narrate(text: str, table: dict[str, Capacity], subject: str | None = None) -> str | None:
    """English for one statement, or None when we are not sure what it does.
    subject: what the EVALUATE that holds this statement compares ("TRUE" for EVALUATE TRUE)."""
    t = re.sub(r"\s+", " ", text.strip().rstrip(".").strip())
    u = t.upper()
    if m := re.fullmatch(r"WHEN OTHER(?: (.+))?", u):
        if not m[1]:
            return "In every other case:"
        rest = _narrate(t[len("WHEN OTHER "):], table)
        return f"In every other case: {_lower_first(rest)}" if rest else None
    if m := re.fullmatch(r"WHEN (.+)", u):
        cond, inline = _split_inline(t[5:])
        what = cond if (subject in (None, "TRUE")) else f"{subject} is {cond.replace(' ALSO ', ' and ')}"
        if inline is None:
            return f"When {what}:"
        rest = _narrate(inline, table)
        return f"When {what}: {_lower_first(rest)}" if rest else None
    if m := re.fullmatch(r"EVALUATE (.+)", u):
        return "Picks the first case below that is true:" if m[1] == "TRUE" else f"Compares {m[1]} with the cases below and takes the first that matches:"
    if m := re.fullmatch(r"IF (.+)", u):
        cond, inline = _split_inline(t[3:])
        if inline:
            rest = _narrate(inline, table)
            return f"If {cond}: {_lower_first(rest)}" if rest else None
    if m := re.fullmatch(r"(NOT )?(?:ON )?SIZE ERROR (.+)", u):
        rest = _narrate(t[len(m.group(0)) - len(m.group(2)):], table)
        if rest:
            return ("If the result fits: " if m[1] else "If the result does not fit, or a division by zero happens: ") + _lower_first(rest)
    if m := re.fullmatch(r"(NOT )?INVALID KEY (.+)", u):
        rest = _narrate(t[len(m.group(0)) - len(m.group(2)):], table)
        if rest:
            return ("If the key is found: " if m[1] else "If the key is not found: ") + _lower_first(rest)
    if m := re.fullmatch(r"GO TO ([A-Z0-9-]+)", u):
        return f"Jumps to paragraph {m[1]}."
    if m := re.fullmatch(r"PERFORM ([A-Z0-9-]+) (?:THRU|THROUGH) ([A-Z0-9-]+)", u):
        return f"Runs paragraphs {m[1]} through {m[2]}."
    if m := re.fullmatch(r"CALL ['\"]?([A-Z0-9-]+)['\"]?(?: USING (.+))?", u):
        args = re.sub(r"\bBY (REFERENCE|CONTENT|VALUE)\b", "", m[2] or "").strip()
        return f"Calls program {m[1]}" + (f" with {_list(args)}." if args else ".")
    if m := re.fullmatch(r"ACCEPT ([A-Z0-9-]+) FROM (DATE|DAY|TIME|DAY-OF-WEEK)(?: .+)?", u):
        return f"Takes the current {m[2].lower().replace('-', ' ')} into {m[1]}."
    if m := re.fullmatch(r"ACCEPT ([A-Z0-9-]+)", u):
        return f"Reads {m[1]} from the console."
    if m := re.fullmatch(r"STRING .+ INTO ([A-Z0-9-]+).*", u):
        return f"Joins pieces of text into {m[1]}."
    if m := re.fullmatch(r"UNSTRING ([A-Z0-9-]+) .*?INTO (.+?)(?: WITH POINTER .+| TALLYING .+)?", u):
        return f"Splits {m[1]} into {_list(re.sub(r'(DELIMITER|COUNT) IN [A-Z0-9-]+', '', m[2]))}."
    if m := re.fullmatch(r"INSPECT ([A-Z0-9-]+) (TALLYING|REPLACING|CONVERTING) .+", u):
        return {"TALLYING": f"Counts characters in {m[1]}.", "REPLACING": f"Replaces characters in {m[1]}.",
                "CONVERTING": f"Converts characters in {m[1]}."}[m[2]]
    if m := re.fullmatch(r"SEARCH (ALL )?([A-Z0-9-]+).*", u):
        return f"Looks up a row of table {m[2]}" + (" by binary search." if m[1] else ", one row at a time.")
    if m := re.fullmatch(r"REWRITE ([A-Z0-9-]+).*", u):
        return f"Replaces record {m[1]} in its file."
    if m := re.fullmatch(r"DELETE ([A-Z0-9-]+)(?: RECORD)?", u):
        return f"Deletes the current record of {m[1]}."
    if m := re.fullmatch(r"START ([A-Z0-9-]+).*", u):
        return f"Positions file {m[1]} by its key."
    if m := re.fullmatch(r"SET ([A-Z0-9- ]+?) (UP|DOWN) BY (\S+)", u):
        return f"Moves {_list(m[1])} {m[2].lower()} by {m[3]}."
    if m := re.fullmatch(r"SET ([A-Z0-9- ]+?) TO (?!TRUE$)(\S+)", u):
        return f"Sets {_list(m[1])} to {m[2]}."
    if m := re.fullmatch(r"SORT ([A-Z0-9-]+) ON (ASCENDING|DESCENDING) KEY ([A-Z0-9- ]+?)(?: (?:USING|INPUT|WITH) .+)?", u):
        return f"Sorts {m[1]} by {_list(m[3])}, {m[2].lower()}."
    if m := re.fullmatch(r"RELEASE ([A-Z0-9-]+).*", u):
        return f"Passes record {m[1]} to the sort."
    if m := re.fullmatch(r"RETURN ([A-Z0-9-]+).*", u):
        return f"Takes the next sorted record from {m[1]}."
    if u in ("EXIT PERFORM", "EXIT PERFORM CYCLE"):
        return "Leaves the loop." if u == "EXIT PERFORM" else "Goes on with the next turn of the loop."
    if u in ("EXIT PARAGRAPH", "EXIT SECTION"):
        return f"Leaves this {u.split()[1].lower()}."
    if u == "NEXT SENTENCE":
        return "Goes on after the next period."
    if m := re.fullmatch(r"MOVE CORR(?:ESPONDING)? ([A-Z0-9-]+) TO ([A-Z0-9-]+)", u):
        return f"Copies each field of {m[1]} into the field of {m[2]} with the same name."
    if m := re.fullmatch(r"MOVE (.+?) TO ([A-Z0-9-]+(?: [A-Z0-9-]+)+)", u):
        if not re.search(r"\(", m[2]):
            return f"Copies {m[1]} into {_list(m[2])}."
    if m := re.fullmatch(r"(ADD|SUBTRACT) (.+) (?:TO|FROM) (.+) GIVING ([A-Z0-9-]+)( ROUNDED)?", u):
        op = "Adds" if m[1] == "ADD" else "Subtracts"
        return f"{op} {m[2]} {'and' if m[1] == 'ADD' else 'from'} {m[3]} and stores the result in {m[4]}{', rounded' if m[5] else ''}."
    if m := re.fullmatch(r"MULTIPLY (.+) BY (.+) GIVING ([A-Z0-9-]+)( ROUNDED)?", u):
        return f"Multiplies {m[1]} by {m[2]} and stores the result in {m[3]}{', rounded' if m[4] else ''}."
    if m := re.fullmatch(r"DIVIDE (.+) (INTO|BY) (.+) GIVING ([A-Z0-9-]+)( ROUNDED)?(?: REMAINDER ([A-Z0-9-]+))?", u):
        a, b = (m[3], m[1]) if m[2] == "INTO" else (m[1], m[3])
        return f"Divides {a} by {b} and stores the result in {m[4]}{', rounded' if m[5] else ''}" + (f", the remainder in {m[6]}." if m[6] else ".")
    if m := re.fullmatch(r"OPEN (.+)", u):
        return f"Opens files ({m[1].lower()})."
    if m := re.fullmatch(r"CLOSE (.+)", u):
        return f"Closes {m[1].replace(' ', ' and ')}."
    if u in ("STOP RUN", "GOBACK"):
        return "Ends the program."
    if u in ("CONTINUE", "EXIT", "EXIT PROGRAM"):
        return "Does nothing here." if u == "CONTINUE" else "Leaves this paragraph."
    if m := re.fullmatch(r"(INPUT|OUTPUT|I-O|EXTEND) ([A-Z0-9- ]+)", u):
        return f"(continued) opens {m[2]} for {'reading' if m[1] == 'INPUT' else 'writing'}."
    if m := re.fullmatch(r"PERFORM UNTIL (.+)", u):
        return f"Repeats the steps below until {m[1]}."
    if m := re.fullmatch(r"PERFORM ([A-Z0-9-]+) UNTIL (.+)", u):
        return f"Runs paragraph {m[1]} again and again until {m[2]}."
    if m := re.fullmatch(r"PERFORM ([A-Z0-9-]+) (\S+) TIMES", u):
        return f"Runs paragraph {m[1]} {m[2]} times."
    if m := re.fullmatch(r"PERFORM VARYING ([A-Z0-9-]+) FROM (\S+) BY (\S+) UNTIL (.+)", u):
        return f"Repeats the steps below with {m[1]} counting from {m[2]} in steps of {m[3]}, until {m[4]}."
    if m := re.fullmatch(r"INITIALIZE (.+)", u):
        return f"Resets {m[1]}: numbers to zero, text to spaces."
    if m := re.fullmatch(r"SET ([A-Z0-9-]+) TO TRUE", u):
        return f"Makes condition {m[1]} true."
    if m := re.fullmatch(r"PERFORM ([A-Z0-9-]+)", u):
        return f"Runs paragraph {m[1]}."
    if m := re.fullmatch(r"READ ([A-Z0-9-]+)", u):
        return f"Reads the next record from {m[1]}."
    if m := re.fullmatch(r"(NOT )?AT END (.+)", u):
        rest = _narrate(t[len(m.group(0)) - len(m.group(2)):], table)
        if rest is None:
            return None
        return ("When there is another record: " if m[1] else "When the file is exhausted: ") + rest[0].lower() + rest[1:]
    if m := re.fullmatch(r"WRITE ([A-Z0-9-]+)(?: FROM ([A-Z0-9-]+))?(?: (?:BEFORE|AFTER) ADVANCING .+)?", u):
        return f"Writes record {m[1]}{' (taken from ' + m[2] + ')' if m[2] else ''} to the output file."
    if m := re.fullmatch(r"MOVE (.+) TO ([A-Z0-9-]+)", u):
        note = _cap_note(m[2], table) if re.fullmatch(r"[A-Z][A-Z0-9-]*", m[1]) else ""
        return f"Copies {m[1]} into {m[2]}.{note}"
    if m := re.fullmatch(r"COMPUTE ([A-Z0-9-]+)( ROUNDED)? = (.+)", u):
        return f"Calculates {m[3]} and stores it in {m[1]}, {_FOR['ROUNDED'] if m[2] else 'with extra decimals cut off (not rounded)'}."
    if m := re.fullmatch(r"ADD (.+) TO ([A-Z0-9-]+)( ROUNDED)?", u):
        return f"Adds {m[1]} to {m[2]}{', rounded' if m[3] else ''}."
    if m := re.fullmatch(r"SUBTRACT (.+) FROM ([A-Z0-9-]+)( ROUNDED)?", u):
        return f"Subtracts {m[1]} from {m[2]}{', rounded' if m[3] else ''}."
    if m := re.fullmatch(r"MULTIPLY (.+) BY ([A-Z0-9-]+)( ROUNDED)?", u):
        return f"Multiplies {m[2]} by {m[1]}{', rounded' if m[3] else ''}."
    if m := re.fullmatch(r"DIVIDE (.+) INTO ([A-Z0-9-]+)( ROUNDED)?", u):
        return f"Divides {m[2]} by {m[1]}{', rounded' if m[3] else ''}."
    if m := re.fullmatch(r"DISPLAY (.+)", u):
        return f"Shows {m[1]} on the console."
    if m := re.fullmatch(r"IF (.+)", u):
        return f"If {m[1]}:"
    if u == "ELSE":
        return "Otherwise:"
    if m := re.fullmatch(r"ON SIZE ERROR MOVE (.+) TO ([A-Z0-9-]+)", u):
        return f"If that result does not fit or a division by zero happens, sets {m[2]} to {m[1]}."
    if u.startswith("END-") and u[4:] in {"IF", "READ", "PERFORM", "EVALUATE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "WRITE", "REWRITE", "DELETE",
                                          "START", "STRING", "UNSTRING", "CALL", "SEARCH", "ACCEPT", "DISPLAY", "RETURN"}:
        return ""  # structural, nothing to say
    return None


def _logical(lines: list[Line]) -> list[tuple[int, str, str]]:
    """(line number, indentation text, statement text). Statements that wrap onto the next line are joined."""
    code = [l for l in lines if not l.comment]
    result: list[tuple[int, str, str]] = []
    i = 0
    while i < len(code):
        raw = code[i].text
        text, number = raw.strip(), code[i].number
        while _CONTINUES.search(text) and i + 1 < len(code):
            i += 1
            text = f"{text} {code[i].text.strip()}"
        result.append((number, raw[: len(raw) - len(raw.lstrip())], text))
        i += 1
    return result


def _purpose(lines: list[Line]) -> str:
    block: list[str] = []
    for l in lines:
        if l.comment:
            cleaned = re.sub(r"^[-=*\s]+|[-=*\s]+$", "", l.text)
            if cleaned and not cleaned.upper().startswith(("COPYRIGHT", "SPDX")):
                block.append(cleaned)
        elif block:
            break
    return " ".join(block)[:300]


_USAGE = {"packed": "packed decimal (COMP-3)", "binary": "binary (COMP)", "native": "native binary (COMP-5)", "index": "index"}
_SIGNS = {
    "none": "unsigned",
    "leading_sep": "separate +/- character first",
    "trailing_sep": "separate +/- character last",
    "trailing_over": "sign stored in the last digit",
    "leading_over": "sign stored in the first digit",
}


def _meaning(it: Item) -> str:
    if it.kind == "alpha":
        return f"text, {it.size} character{'s' if it.size != 1 else ''}"
    if it.kind == "edited":
        return f"number shown with editing, picture `{it.pic}`"
    ints, decs = it.digits - it.scale, it.scale
    shape = (f"{ints} digit{'s' if ints != 1 else ''} before the decimal point and {decs} after" if decs > 0
             else f"{ints} digit{'s' if ints != 1 else ''}, no decimals")
    text = f"number, {shape}, {_SIGNS.get(it.sign, 'signed' if it.signed else 'unsigned')}"
    if it.usage != "display":
        text += f", stored as {_USAGE.get(it.usage, it.usage)} in {it.size} bytes"
    return text


def _layout_table(rec: Item, label: str) -> list[str]:
    out = [f"## {label}: {rec.name} ({rec.size} bytes per record)", "", "| Field | Bytes | Meaning |", "| --- | --- | --- |"]
    for lf in leaves(rec):
        out.append(f"| {lf.name} | {lf.offset + 1}-{lf.offset + lf.width} | {_meaning(lf.item)} |")
    return out + [""]


def generate_spec(program: str, root: Path = ROOT) -> Spec:
    try:
        model = load_model(program, root)
    except ModelError as exc:
        raise ValueError(str(exc)) from exc
    text = model.path.read_text(encoding="utf-8", errors="replace")
    lines = normalize(text, model.fixed, model.copy_dirs or None)
    start = next((i for i, l in enumerate(lines) if not l.comment and l.text.strip().upper().startswith("PROCEDURE DIVISION")), None)
    if start is None:
        raise ValueError(f"{model.path.name}: no PROCEDURE DIVISION")
    table = _symbols(lines[:start], model)

    out = [f"# Spec: {program.upper()} (from `{model.path.relative_to(root).as_posix()}`)", ""]
    purpose = _purpose(lines)
    if purpose:
        out += [f"Purpose, from the source comment: {purpose}", ""]
    def kind(f):
        return "text lines" if f.organization == "line" else "fixed-length records"

    io = [f"reads `{f.assign}` ({kind(f)})" for f in model.inputs] + [f"writes `{f.assign}` ({kind(f)})" for f in model.outputs]
    if model.accepts:
        io.append("reads console input (ACCEPT " + ", ".join(model.accepts) + ")")
    out += [f"The program {', '.join(io) or 'uses no files'}. Source format: {'fixed (columns 8-72)' if model.fixed else 'free'}.", ""]
    for note in model.notes:
        out += [f"Note: {note}", ""]
    for f in model.files:
        for rec in f.records[:1]:
            out += _layout_table(rec, f"{'Input' if f.is_input else 'Output'} file {f.assign}")
    for item in model.unsupported:
        out += [f"Not runnable yet: {item}.", ""]

    logical = _logical(lines[start + 1:])
    out += ["## Behavior by paragraph", ""]
    review: list[str] = []
    subjects: list[str] = []  # what each open EVALUATE compares
    for number, indent, stmt in logical:
        if re.fullmatch(r"[A-Z0-9-]+(\s+SECTION)?\.", stmt, re.I) and len(indent) <= 3:
            out += ["", f"### {stmt[:-1].upper()} (line {number})", ""]
            continue
        head = re.sub(r"\s+", " ", stmt.strip().rstrip(".")).upper()
        if head.startswith("EVALUATE "):
            subjects.append(head[9:])
        sentence = _narrate(stmt, table, subjects[-1] if subjects else None)
        if head == "END-EVALUATE" or (stmt.rstrip().endswith(".") and subjects and not head.startswith("EVALUATE ")):
            subjects.pop() if head == "END-EVALUATE" else subjects.clear()
        bullet = "  " * max(0, len(indent) // 4 - 1)
        if sentence is None:
            review.append(f"line {number}: `{stmt}` was not summarized")
            out.append(f"{bullet}- L{number}: (not summarized) `{stmt}`")
        elif sentence:
            out.append(f"{bullet}- L{number}: {sentence}")

    out += ["", "## Where values can silently change", ""]
    risks = []
    for idx, (number, _indent, stmt) in enumerate(logical):
        m = re.fullmatch(r"COMPUTE ([A-Z0-9-]+)( ROUNDED)? = .+", stmt.upper().rstrip("."))
        if m and m[1] in table:
            kind = "rounds half away from zero" if m[2] else "truncates extra decimals"
            guarded = idx + 1 < len(logical) and logical[idx + 1][2].upper().startswith("ON SIZE ERROR")
            tail = (
                "A result that does not fit triggers the ON SIZE ERROR branch instead of losing digits."
                if guarded
                else f"A result that does not fit loses its leading digits ({table[m[1]].describe()})."
            )
            risks.append(f"- L{number}: `{m[1]}` {kind}. {tail} A migration must reproduce this exactly.")
    out += risks or ["- None detected."]

    out += ["", "## Needs human review", ""]
    out += [f"- {r}" for r in review] or ["- Every statement was recognized."]
    return Spec(program, "\n".join(out) + "\n", review)


def write_spec(program: str, root: Path = ROOT) -> Path:
    spec = generate_spec(program, root)
    target = root / "docs" / "specs" / f"{program}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(spec.markdown, encoding="utf-8")
    return target
