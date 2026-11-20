"""Where is a name used, across every program in the workspace: data items, conditions, paragraphs and files.

Read from the source the compiler reads (after COPY and the precompiler), outside comments and literals. Each hit says
whether the line defines the name, changes it, or only uses it, so a field's impact can be followed program by program.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .cobol_src import normalize
from .precompile import _outside_quotes
from .recorder import ROOT

WORD = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]|[A-Za-z])(?![A-Za-z0-9_-])")
_RESERVED = set("""ACCEPT ADD ADVANCING AFTER ALL ALSO ALTER AND ANY ARE AREA AS ASCENDING ASSIGN AT AUTHOR BEFORE BINARY BLANK BY CALL CANCEL
CHARACTER CHARACTERS CLOSE COMP COMP-1 COMP-2 COMP-3 COMP-4 COMP-5 COMPUTATIONAL COMPUTE CONFIGURATION CONTAINS CONTENT CONTINUE CONTROL
CONVERTING COPY CORR CORRESPONDING COUNT DATA DATE DAY DECIMAL-POINT DELETE DELIMITED DELIMITER DEPENDING DESCENDING DISPLAY DIVIDE DIVISION
DOWN DUPLICATES DYNAMIC ELSE END END-ADD END-CALL END-COMPUTE END-DELETE END-DIVIDE END-EVALUATE END-IF END-MULTIPLY END-PERFORM END-READ
END-RETURN END-REWRITE END-SEARCH END-START END-STRING END-SUBTRACT END-UNSTRING END-WRITE ENVIRONMENT EQUAL ERROR EVALUATE EXCEPTION EXIT
EXTEND FALSE FD FILE FILE-CONTROL FILLER FIRST FOR FROM FUNCTION GIVING GO GOBACK GREATER HIGH-VALUE HIGH-VALUES I-O I-O-CONTROL IDENTIFICATION
IF IN INDEX INDEXED INITIAL INITIALIZE INPUT INPUT-OUTPUT INSPECT INTO INVALID IS JUST JUSTIFIED KEY LABEL LEADING LENGTH LESS LINE LINES
LINKAGE LOW-VALUE LOW-VALUES MERGE MODE MOVE MULTIPLY NEXT NO NOT NUMERIC OBJECT-COMPUTER OCCURS OF OFF OMITTED ON OPEN OPTIONAL OR
ORGANIZATION OTHER OUTPUT OVERFLOW PACKED-DECIMAL PERFORM PIC PICTURE POINTER PROCEDURE PROGRAM PROGRAM-ID QUOTE QUOTES RANDOM READ RECORD
RECORDS REDEFINES REFERENCE RELATIVE RELEASE REMAINDER REPLACING RETURN REWRITE ROUNDED RUN SEARCH SECTION SELECT SENTENCE SEPARATE
SEQUENTIAL SET SIGN SIZE SORT SOURCE-COMPUTER SPACE SPACES SPECIAL-NAMES STANDARD START STATUS STOP STRING SUBTRACT TALLYING TEST THAN THEN
THROUGH THRU TIME TIMES TO TRAILING TRUE UNSTRING UNTIL UP UPON USAGE USING VALUE VALUES VARYING WHEN WITH WORKING-STORAGE WRITE ZERO ZEROES
ZEROS""".split())
_CHANGES = re.compile(r"\b(?:TO|INTO|GIVING|FROM)\s+$|\b(?:ACCEPT|INITIALIZE|SET|COMPUTE|READ\s+\S+\s+INTO)\s+$", re.I)


@lru_cache(maxsize=256)
def _program_lines(path: str, stamp: float) -> tuple[tuple[int, str], ...]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return tuple((ln.number, ln.text) for ln in normalize(text) if not ln.comment and ln.text.strip())


def _sources(root: Path) -> list[tuple[str, Path]]:
    from .programs import program_names

    out = []
    for name in program_names(root):
        folder = root / "legacy" / name
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in (".cbl", ".cob", ".cobol", ".cpy", ".copy"):
                out.append((name, p))
    return out


def _role(text: str, start: int, end: int, in_data: bool) -> str:
    before = text[:start]
    if in_data and re.match(r"\s*\d{1,2}\s+$", before):
        return "defined"
    if in_data and re.match(r"\s*(FD|SD)\s+$", before, re.I):
        return "defined"
    if not in_data and not before.strip() and re.match(r"\s*(SECTION)?\s*\.\s*$", text[end:], re.I):
        return "paragraph"
    if re.match(r"\s*=", text[end:]) and re.search(r"\bCOMPUTE\s+$", before, re.I):
        return "changed"
    if _CHANGES.search(before):
        return "changed"
    return "used"


def hits(name: str, root: Path = ROOT, limit: int = 400) -> list[dict]:
    """Every line in the workspace that names `name`, with the program, the file, the line and the role."""
    target = name.upper()
    out: list[dict] = []
    for program, path in _sources(root):
        in_data = True
        for number, text in _program_lines(str(path), path.stat().st_mtime):
            if re.match(r"\s*PROCEDURE\s+DIVISION", text, re.I):
                in_data = False
            found = []
            _outside_quotes(text, lambda s, acc=found: (acc.extend(m for m in WORD.finditer(s) if m.group(1).upper() == target), s)[1])
            if not found:
                continue
            m = re.search(r"(?<![A-Za-z0-9_-])" + re.escape(target) + r"(?![A-Za-z0-9_-])", text, re.I)
            role = _role(text, m.start(), m.end(), in_data) if m else "used"
            out.append({"program": program, "file": path.name, "line": number, "text": text.strip()[:160], "role": role})
            if len(out) >= limit:
                return out
    return out


def names(query: str, root: Path = ROOT, limit: int = 12) -> list[dict]:
    """Names in the workspace that contain the query, with how often each program uses them; best matches first."""
    q = query.strip().upper()
    if len(q) < 2 or not re.fullmatch(r"[A-Z0-9_-]+", q):
        return []
    counts: dict[str, dict[str, int]] = {}
    for program, path in _sources(root):
        for _number, text in _program_lines(str(path), path.stat().st_mtime):
            words: list[str] = []
            _outside_quotes(text, lambda s, acc=words: (acc.extend(m.group(1).upper() for m in WORD.finditer(s)), s)[1])
            for w in words:
                if q in w and w not in _RESERVED and not w.isdigit():
                    counts.setdefault(w, {})
                    counts[w][program] = counts[w].get(program, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (not kv[0].startswith(q), kv[0] != q, -sum(kv[1].values()), kv[0]))
    return [{"name": n, "total": sum(c.values()), "programs": [{"program": p, "count": k} for p, k in sorted(c.items())]} for n, c in ranked[:limit]]
