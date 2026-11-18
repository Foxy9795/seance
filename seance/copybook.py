"""Turn COBOL data descriptions (copybooks or an FD) into fixed-width record layouts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .cobol_src import normalize, sentences


class CopybookError(ValueError):
    """Raised when a record description uses something Séance does not support. The message says what to do."""


@dataclass(frozen=True)
class Field:
    name: str  # COBOL name, e.g. IN-ACCT-ID
    py_name: str  # python attribute, e.g. acct_id
    kind: str  # "alpha", "numeric" or "edited"
    digits: int  # alpha/edited: width; numeric: total digits (integer + decimals)
    scale: int  # decimal digits (numeric only)
    signed: bool
    offset: int
    width: int  # characters in the file
    sign: str = "none"  # leading_sep, trailing_sep, leading_over, trailing_over, or none
    pic: str = ""

    @property
    def max_value(self) -> Decimal:
        return Decimal(10**self.digits - 1).scaleb(-self.scale)


@dataclass(frozen=True)
class Layout:
    record_name: str
    fields: tuple[Field, ...]

    @property
    def width(self) -> int:
        return sum(f.width for f in self.fields)

    def slices(self) -> list[tuple[Field, int, int]]:
        return [(f, f.offset, f.offset + f.width) for f in self.fields]


_PIC_REPEAT = re.compile(r"([9XSVAZB0*$+\-,./])\((\d+)\)")
_ITEM = re.compile(r"^(\d{1,2})\s+([A-Z][A-Z0-9-]*)(?:\s+(.*))?$", re.S | re.I)
_PICK = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", re.I)
_PACKED = re.compile(r"\b(COMP-3|COMPUTATIONAL-3|PACKED-DECIMAL)\b", re.I)
_BINARY = re.compile(r"\b(COMP|COMP-[1245X]|COMPUTATIONAL(?:-[1245X])?|BINARY|INDEX|POINTER)\b", re.I)


def _expand_pic(pic: str) -> str:
    return _PIC_REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), pic)


def _py_name(cobol_name: str, prefix: str) -> str:
    stripped = cobol_name[len(prefix):] if prefix and cobol_name.startswith(prefix) and len(cobol_name) > len(prefix) else cobol_name
    return stripped.lower().replace("-", "_")


def _sign_mode(tail: str) -> str:
    m = re.search(r"SIGN\s+(?:IS\s+)?(LEADING|TRAILING)(\s+SEPARATE(?:\s+CHARACTER)?)?", tail, re.I)
    if not m:
        return "trailing_over"  # the COBOL default
    where = m.group(1).lower()
    return f"{where}_{'sep' if m.group(2) else 'over'}"


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def _clean(rest: str) -> str:
    rest = re.sub(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(?:\"[^\"]*\"|'[^']*'|\S+)(?:\s+THRU\s+\S+)?", " ", rest, flags=re.I)
    rest = re.sub(r"\bUSAGE\s+(?:IS\s+)?DISPLAY\b", " ", rest, flags=re.I)
    return rest


def parse_items(items: list[tuple[int, str]]) -> list[Layout]:
    """Parse level-numbered data descriptions into one Layout per 01 record. Groups are flattened."""
    records: list[tuple[str, list[tuple[str, str]]]] = []
    for line_no, text in items:
        m = _ITEM.match(text.strip())
        if not m:
            raise CopybookError(f"line {line_no}: cannot read this data description: {text.strip()[:80]!r}")
        level, name, rest = int(m.group(1)), m.group(2).upper(), (m.group(3) or "").strip()
        if level == 88:
            continue  # condition names carry no data
        if level in (66, 77, 78):
            raise CopybookError(f"line {line_no}: level {level} items are not supported.")
        if level == 1:
            records.append((name, []))
            continue
        if not records:
            raise CopybookError(f"line {line_no}: {name} appears before a 01 level record.")
        records[-1][1].append((name, _clean(rest)))

    layouts = []
    for record_name, fields in records:
        raw = []
        for name, rest in fields:
            if re.search(r"\bOCCURS\b", rest, re.I):
                raise CopybookError(f"{name}: OCCURS (tables) is not supported yet. Flatten the table into separate fields to use Séance.")
            if re.search(r"\bREDEFINES\b", rest, re.I):
                raise CopybookError(f"{name}: REDEFINES is not supported yet.")
            if re.search(r"\b(BLANK\s+WHEN\s+ZERO|JUSTIFIED|JUST|SYNC(?:HRONIZED)?)\b", rest, re.I):
                raise CopybookError(f"{name}: BLANK WHEN ZERO, JUSTIFIED and SYNCHRONIZED are not supported yet.")
            if _PACKED.search(rest):
                raise CopybookError(
                    f"{name} is COMP-3 (packed decimal). Séance reads text records only, so packed fields in a record are not supported yet. "
                    "Workaround: have the program read and write DISPLAY numbers, or unpack the file first. COMP-3 in WORKING-STORAGE is fine."
                )
            if _BINARY.search(rest):
                raise CopybookError(f"{name} is a binary (COMP) field in a record, which is not supported yet. COMP in WORKING-STORAGE is fine.")
            pic = _PICK.search(rest)
            if not pic:
                if rest.strip():
                    raise CopybookError(f"{name}: no PIC clause in {rest.strip()[:60]!r}")
                continue  # a group item: its children carry the data
            raw.append((name, pic.group(1), rest[pic.end():]))
        if not raw:
            raise CopybookError(f"{record_name}: no fields found.")

        prefix = ""
        if "-" in record_name:
            candidate = record_name.rsplit("-", 1)[0] + "-"
            if all(n.startswith(candidate) for n, _, _ in raw if n != "FILLER"):
                prefix = candidate
        py_names = _unique([_py_name(n, prefix) if n != "FILLER" else "filler" for n, _, _ in raw])

        built: list[Field] = []
        offset = 0
        for (name, pic_text, tail), py in zip(raw, py_names):
            pic_u = _expand_pic(pic_text.upper().rstrip("."))
            if re.fullmatch(r"[XA9]+", pic_u) and re.search(r"[XA]", pic_u):
                field = Field(name, py, "alpha", len(pic_u), 0, False, offset, len(pic_u), pic=pic_u)
            elif re.fullmatch(r"(S?)(9*)(?:V(9+))?", pic_u) and re.search(r"9", pic_u):
                nm = re.fullmatch(r"(S?)(9*)(?:V(9+))?", pic_u)
                signed, ints, decs = bool(nm.group(1)), len(nm.group(2)), len(nm.group(3) or "")
                sign = _sign_mode(tail) if signed else "none"
                width = ints + decs + (1 if sign.endswith("_sep") else 0)
                field = Field(name, py, "numeric", ints + decs, decs, signed, offset, width, sign, pic_u)
            elif re.fullmatch(r"[9ZB0/,.*$+\-CRDBV]+", pic_u) and not pic_u.startswith("S"):
                width = len(pic_u) - pic_u.count("V")
                field = Field(name, py, "edited", width, 0, False, offset, width, pic=pic_u)
            else:
                raise CopybookError(f"{name}: the picture {pic_text!r} is not supported yet.")
            built.append(field)
            offset += field.width
        layouts.append(Layout(record_name, tuple(built)))
    return layouts


def parse_copybook(text: str) -> Layout:
    """Parse a copybook that holds one 01 record (or a bare list of fields)."""
    sents = sentences(normalize(text))
    if sents and not re.match(r"^\s*01\b", sents[0][1]):
        sents = [(sents[0][0], "01 RECORD")] + sents
    layouts = parse_items(sents)
    if not layouts:
        raise CopybookError("no record found")
    return layouts[0]


def parse_copybook_file(path) -> Layout:
    from pathlib import Path

    return parse_copybook(Path(path).read_text(encoding="utf-8", errors="replace"))

