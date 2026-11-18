"""Read COBOL source text: detect fixed/free format, drop comments, split into sentences."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID_DIV = re.compile(r"^(\s*)(IDENTIFICATION|ID)\s+DIVISION", re.I)


@dataclass(frozen=True)
class Line:
    number: int  # 1-based line in the original file
    text: str  # code with indentation relative to column 8 (fixed) or column 1 (free)
    comment: bool = False


def detect_fixed(text: str) -> bool:
    """Fixed format puts code in columns 8-72. Free format starts IDENTIFICATION DIVISION at column 1."""
    for raw in text.splitlines():
        m = _ID_DIV.match(raw.expandtabs(8))
        if m:
            return len(m.group(1)) >= 6
    # No IDENTIFICATION line (a copybook): look for the column-7 indicator area instead.
    sample = [l.expandtabs(8) for l in text.splitlines() if l.strip()]
    fixedish = sum(1 for l in sample if len(l) > 7 and l[:6].strip() in ("",) or (len(l) > 7 and l[:6].isdigit()))
    return bool(sample) and fixedish >= max(1, int(0.8 * len(sample))) and all(len(l) < 7 or l[6] in " *-/D" for l in sample)


def normalize(text: str, fixed: bool | None = None) -> list[Line]:
    """Return code and comment lines. Fixed format: columns 1-6 and 73+ are ignored, column 7 is the indicator."""
    fixed = detect_fixed(text) if fixed is None else fixed
    out: list[Line] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        raw = raw.expandtabs(8).rstrip()
        if not raw.strip():
            continue
        if fixed:
            indicator = raw[6] if len(raw) > 6 else " "
            body = raw[7:72] if len(raw) > 7 else ""
            if indicator in "*/":
                out.append(Line(i, raw[7:].strip(), True))
            elif indicator == "-":
                if out and not out[-1].comment:
                    prev = out[-1]
                    out[-1] = Line(prev.number, prev.text + body.strip().lstrip("\"'"))
            elif indicator in "dD":
                continue  # debugging line
            elif body.strip():
                out.append(Line(i, body.rstrip()))
        else:
            stripped = raw.strip()
            if stripped.startswith("*>"):
                out.append(Line(i, stripped[2:].strip(), True))
                continue
            code = _strip_inline_comment(raw)
            if code.strip():
                out.append(Line(i, code.rstrip()))
    return out


def _strip_inline_comment(line: str) -> str:
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "*" and line[i : i + 2] == "*>":
            return line[:i]
    return line


def sentences(lines: list[Line]) -> list[tuple[int, str]]:
    """Split code into sentences (text up to a period followed by space or end of line, outside quotes)."""
    result: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    quote = ""
    for line in lines:
        if line.comment:
            continue
        text = line.text.strip()
        if not current:
            start = line.number
        i = 0
        while i < len(text):
            ch = text[i]
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "." and (i + 1 == len(text) or text[i + 1] == " "):
                current.append(text[: i])
                result.append((start, " ".join(p for p in current if p).strip()))
                current = []
                text = text[i + 1 :].lstrip()
                i = 0
                start = line.number
                continue
            i += 1
        if text:
            current.append(text)
    if any(current):
        result.append((start, " ".join(current).strip()))
    return [(n, s) for n, s in result if s]
