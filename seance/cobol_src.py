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


def normalize(text: str, fixed: bool | None = None, copy_dirs: list | None = None) -> list[Line]:
    """Return code and comment lines. Fixed format: columns 1-6 and 73+ are ignored, column 7 is the indicator.
    copy_dirs: where COPY looks for copybooks. Given, every COPY statement is replaced by its copybook's text, as
    the compiler reads it; left out, COPY statements stay as written. REPLACE is always done (seance.copybook)."""
    from .copybook import expand
    from .precompile import apply

    fixed = detect_fixed(text) if fixed is None else fixed
    debugging = bool(re.search(r"WITH\s+DEBUGGING\s+MODE", text, re.I))
    out = expand(read_lines(text, fixed, debugging), list(copy_dirs) if copy_dirs is not None else None, debugging)
    return apply(out, Line, debugging)[0]


_ENTRY = re.compile(r"(AUTHOR|DATE-WRITTEN|DATE-MODIFIED|DATE-COMPILED|INSTALLATION|REMARKS|SECURITY)(?![A-Za-z0-9_-])", re.I)
_DIVISION = re.compile(r"(?<![A-Za-z0-9_-])(?:(ID|IDENTIFICATION)[ ,;]+DIVISION|(PROGRAM-ID)|DIVISION|SECTION)(?![A-Za-z0-9_-])", re.I)
_LITERALS = re.compile(r"\"[^\"]*\"|'[^']*'")


def read_lines(text: str, fixed: bool, debugging: bool, entries: bool = True) -> list[Line]:
    """The code and comment lines of one file, before COPY and the compiler directives: continuation lines joined,
    debugging lines kept only WITH DEBUGGING MODE, inline comments cut, and the comment entries of the
    IDENTIFICATION DIVISION (AUTHOR. and the like, to the next line with something in area A) left out as cobc
    leaves them out: even a COPY there is not read. entries: whether the file may start with them (not a copybook)."""
    out: list[Line] = []
    allowed, within = entries, False

    def comment_entry(code: str, area_a_blank: bool) -> bool:
        """cobc's ppinput: a line that starts AUTHOR, SECURITY ... while comments are allowed is skipped, and in
        fixed format so is every line after it with columns 8-11 blank. ID DIVISION and PROGRAM-ID allow them,
        any other DIVISION or SECTION ends that."""
        nonlocal allowed, within
        if within:
            if area_a_blank:
                return True
            within = False
        if allowed and _ENTRY.match(code.lstrip()):
            within = fixed
            return True
        for m in _DIVISION.finditer(_LITERALS.sub(" ", code)):
            allowed = bool(m.group(1) or m.group(2))
        return False

    # the last code line as written out to column 72, while a literal on it is still open: a continued literal keeps
    # every character up to column 72, trailing spaces included, which the stripped text of the line has lost
    open_tail: str | None = None
    for i, raw in enumerate(text.splitlines(), start=1):
        raw = raw.expandtabs(8).rstrip()
        if not raw.strip():
            continue
        probe = (raw[6:] if fixed and len(raw) > 6 else raw).strip()
        src = re.match(r">>\s*SOURCE\s+(?:FORMAT\s+)?(?:IS\s+)?(FREE|FIXED)\b", probe, re.I)
        if src:  # the rest of the file is in the other format
            fixed = src.group(1).upper() == "FIXED"
            continue
        if fixed:
            indicator = raw[6] if len(raw) > 6 else " "
            body = raw[7:72] if len(raw) > 7 else ""
            if raw[6:8] == ">>":  # a directive that starts in the indicator column
                out.append(Line(i, raw[6:].strip()))
                open_tail = None
            elif indicator == "$":
                open_tail = None
                continue  # a Micro Focus compiler directive ($SET ...)
            elif indicator in "*/":
                out.append(Line(i, raw[7:].strip(), True))
            elif indicator == "-":
                at = next((k for k in range(len(out) - 1, -1, -1) if not out[k].comment), None)  # comment lines may come between
                if at is not None:
                    prev = out[at]
                    full = body.ljust(65)
                    first = len(full) - len(full.lstrip())
                    if open_tail is not None:
                        # a continued literal goes on after the quote that opens the continuation line, to column 72
                        joined = open_tail + (full[first + 1:] if full[first:first + 1] in "\"'" else full[first:])
                    else:
                        # a continued word or number: the first character of the line follows the last one before it
                        joined = prev.text.rstrip() + full[first:]
                    open_tail = joined if _open_quote(joined, len(joined) - 1) else None
                    out[at] = Line(prev.number, joined if open_tail is not None else _strip_inline_comment(joined).rstrip())
                continue
            elif indicator in "dD":
                if debugging and body.strip():  # WITH DEBUGGING MODE compiles debugging lines
                    out.append(Line(i, _strip_inline_comment(body).rstrip()))
                open_tail = None
                continue
            elif body.strip():
                code = _strip_inline_comment(body)  # GnuCOBOL accepts *> after column 7 in fixed format too
                if code.strip() and not comment_entry(code, not body[:4].strip()):
                    out.append(Line(i, code.rstrip()))
                    open_tail = body.ljust(65) if code == body and _open_quote(body.ljust(65), 64) else None
                continue
        else:
            stripped = raw.strip()
            if stripped.startswith("*>"):
                out.append(Line(i, stripped[2:].strip(), True))
                continue
            code = _strip_inline_comment(raw)
            if code.strip() and not comment_entry(code, False):
                out.append(Line(i, code.rstrip()))
    return out


_PROGRAM_ID = re.compile(r"^(?P<head>\s*PROGRAM-ID\.?\s+['\"]?[A-Za-z0-9-]+['\"]?)(?P<tail>\s*)$", re.I)


def source_fixes(text: str, fixed: bool) -> tuple[str, list[str]]:
    """Dialect fixes GnuCOBOL needs to compile IBM Enterprise COBOL that IBM accepts as written.

    Only changes that cannot alter behavior are made, line numbers never move, and each one is reported.
    Today: a PROGRAM-ID name without its closing period (IBM allows it, GnuCOBOL stops with a syntax error).
    """
    notes: list[str] = []
    out = []
    for no, raw in enumerate(text.splitlines(keepends=True), start=1):
        end = raw[len(raw.rstrip("\r\n")):]
        line = raw[: len(raw) - len(end)]
        exp = line.expandtabs(8)
        if fixed and len(exp) > 7 and exp[6] == " ":
            body = exp[7:72]
            m = _PROGRAM_ID.match(body)
            if m and len(exp[:7] + m.group("head")) < 72:
                code = m.group("head") + "."
                line = exp[:7] + (code.ljust(65) + exp[72:] if len(exp) > 72 else code)
                notes.append(f"line {no}: added the period after the PROGRAM-ID name, which IBM COBOL lets you leave out.")
        elif not fixed:
            m = _PROGRAM_ID.match(exp)
            if m:
                line = m.group("head") + "."
                notes.append(f"line {no}: added the period after the PROGRAM-ID name, which IBM COBOL lets you leave out.")
        out.append(line + end)
    return "".join(out), notes


def _open_quote(text: str, last: int | None = None) -> bool:
    """Whether a literal is still open at the end of the text (a doubled quote inside a literal is one quote).
    last: the index of column 72. A literal that closes exactly there stays open, as cobc reads it: its quote may
    be the first of a doubled quote that a continuation line starting with two quotes completes."""
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                if text[i + 1:i + 2] == quote:
                    i += 2
                    continue
                if i == last:
                    return True
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif text.startswith("*>", i):
            break
        i += 1
    return bool(quote)


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
