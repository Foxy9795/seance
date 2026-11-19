"""Byte-accurate COBOL data layout: every 01 record is a block of bytes, every item a typed view into it.

Sizes and encodings follow GnuCOBOL's defaults, measured with probe programs:
  DISPLAY numeric   one byte per digit, sign overpunched in the last digit unless SIGN ... SEPARATE
  COMP-3            packed decimal, digits//2 + 1 bytes, sign nibble C (+), D (-), F (unsigned)
  COMP, BINARY,     big-endian two's complement; 1, 2, 4 or 8 bytes for 1-2, 3-4, 5-9, 10-18 digits
  COMP-4
  COMP-5            the same sizes, little-endian (native)
  INDEX             4 bytes
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .cobol_num import edited_supported

_PIC_REPEAT = re.compile(r"([9XSVAPZB0*$+\-,./CRDN])\((\d+)\)")
_ITEM = re.compile(r"^(\d{1,2})\s+([A-Z0-9][A-Z0-9-]*)(?:\s+(.*))?$", re.S | re.I)


class LayoutError(ValueError):
    pass


def expand_pic(pic: str) -> str:
    return _PIC_REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), pic.upper())


def binary_size(digits: int) -> int:
    return 1 if digits <= 2 else 2 if digits <= 4 else 4 if digits <= 9 else 8


@dataclass
class Item:
    name: str
    level: int
    record: str = ""
    parent: "Item | None" = field(default=None, repr=False)
    children: list["Item"] = field(default_factory=list, repr=False)
    offset: int = 0  # bytes from the start of the 01 record, first occurrence
    size: int = 0  # bytes of one occurrence
    occurs: int = 0  # 0 when not a table
    depending: str | None = None
    usage: str = "display"  # display, packed, binary, native, index
    kind: str = "group"  # group, alpha, num, edited
    digits: int = 0
    scale: int = 0
    signed: bool = False
    sign: str = "none"  # none, trailing_over, leading_over, trailing_sep, leading_sep
    pic: str = ""
    justified: bool = False
    blank_zero: bool = False
    value: object = None  # initial value (literal or figurative name)
    value_all: bool = False
    redefines: str | None = None
    conds: list[tuple[str, list]] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)

    @property
    def is_table(self) -> bool:
        return self.occurs > 0

    def dims(self) -> list[tuple[int, int]]:
        """(count, stride) for each OCCURS on this item and its ancestors, outermost first."""
        out, node = [], self
        while node is not None:
            if node.occurs:
                out.append((node.occurs, node.size))
            node = node.parent
        return list(reversed(out))

    @property
    def max_value(self) -> Decimal:
        return Decimal(10**self.digits - 1).scaleb(-self.scale)

    def spec(self) -> list:
        """Compact form for the runtime (see seance.runtime.Program)."""
        return [self.record, self.offset, self.size, self.kind, self.usage, self.digits, self.scale, self.signed, self.sign,
                self.pic, self.dims(), [c.name for c in self.children], self.justified, self.blank_zero]


def _tokens(text: str) -> list[str]:
    return re.findall(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[^\s]+", text)


def parse_literal(tok: str):
    t = tok.strip()
    u = t.upper()
    if u in ("SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES", "QUOTE", "QUOTES", "NULL", "NULLS"):
        return {"SPACES": "SPACE", "ZEROS": "ZERO", "ZEROES": "ZERO", "HIGH-VALUES": "HIGH", "HIGH-VALUE": "HIGH",
                "LOW-VALUES": "LOW", "LOW-VALUE": "LOW", "QUOTES": "QUOTE", "NULL": "LOW", "NULLS": "LOW"}.get(u, u)
    if len(t) >= 2 and t[0] in "\"'" and t[-1] == t[0]:
        return t[1:-1].replace(t[0] * 2, t[0])
    if len(t) >= 3 and t[0] in "xX" and t[1] in "\"'":
        return bytes.fromhex(t[2:-1]).decode("latin-1")
    try:
        return Decimal(t)
    except Exception:
        return None


def _numeric_from_pic(item: Item, p: str, tail: str) -> None:
    lead = re.fullmatch(r"(S?)V?(P+)(9+)", p)  # PPP99: the digits sit below the decimal point, after P zeros
    trail = re.fullmatch(r"(S?)(9+)(P+)V?", p)  # 999PP: the digits sit above P zeros
    m = re.fullmatch(r"(S?)(9*)(?:V(9*))?", p)
    if lead:
        item.signed = bool(lead.group(1))
        item.kind, item.digits, item.scale = "num", len(lead.group(3)), len(lead.group(2)) + len(lead.group(3))
    elif trail:
        item.signed = bool(trail.group(1))
        item.kind, item.digits, item.scale = "num", len(trail.group(2)), -len(trail.group(3))
    elif m:
        item.signed = bool(m.group(1))
        ints, decs = len(m.group(2)), len(m.group(3) or "")
        item.kind, item.digits, item.scale = "num", ints + decs, decs
    else:
        raise LayoutError(f"{item.name}: the picture {p} is not supported yet.")
    if item.signed and item.usage == "display":
        sm = re.search(r"SIGN\s+(?:IS\s+)?(LEADING|TRAILING)(\s+SEPARATE(?:\s+CHARACTER)?)?", tail, re.I)
        item.sign = "trailing_over" if not sm else f"{sm.group(1).lower()}_{'sep' if sm.group(2) else 'over'}"
    if item.usage == "display":
        item.size = item.digits + (1 if item.sign.endswith("_sep") else 0)
    elif item.usage == "packed":
        item.size = item.digits // 2 + 1
    elif item.usage in ("binary", "native"):
        item.size = binary_size(item.digits)


def parse_entries(entries: list[tuple[int, str]]) -> list[Item]:
    """Level-numbered data descriptions -> 01 Items with children, offsets and sizes."""
    roots: list[Item] = []
    stack: list[Item] = []
    last: Item | None = None
    fillers = 0
    for line, text in entries:
        text = re.sub(r"\.\s*$", "", text.strip())
        m = _ITEM.match(text)
        if not m:
            raise LayoutError(f"line {line}: cannot read this data description: {text[:70]!r}")
        level, name, rest = int(m.group(1)), m.group(2).upper(), (m.group(3) or "").strip()
        if level == 88:
            if last is None:
                continue
            vm = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(.*)$", rest, re.I | re.S)
            toks = _tokens(vm.group(1)) if vm else []
            choices, i = [], 0
            while i < len(toks):
                if toks[i].upper() in ("FALSE",) or toks[i].upper() == "WHEN":
                    break
                lo = parse_literal(toks[i])
                hi = None
                if i + 2 < len(toks) and toks[i + 1].upper() in ("THRU", "THROUGH"):
                    hi = parse_literal(toks[i + 2])
                    i += 2
                if lo is not None:
                    choices.append((lo, hi))
                i += 1
            last.conds.append((name, choices))
            continue
        if level == 66:
            raise LayoutError(f"line {line}: level 66 RENAMES is not supported yet.")
        if level == 78:
            raise LayoutError(f"line {line}: level 78 constants are not supported yet.")
        if level == 77:
            level = 1
        if name == "FILLER":
            fillers += 1
            name = f"FILLER#{line}-{fillers}"
        it = Item(name, level)
        upper = rest.upper()
        rm = re.search(r"\bREDEFINES\s+([A-Z0-9-]+)", upper)
        it.redefines = rm.group(1) if rm else None
        om = re.search(r"\bOCCURS\s+(\d+)(?:\s+TO\s+(\d+))?(?:\s+TIMES)?", upper)
        if om:
            it.occurs = int(om.group(2) or om.group(1))
            dm = re.search(r"\bDEPENDING\s+ON\s+([A-Z0-9-]+)", upper)
            it.depending = dm.group(1) if dm else None
            im = re.search(r"\bINDEXED\s+BY\s+([A-Z0-9-]+(?:\s*,?\s*[A-Z0-9-]+)*)", upper)
            if im:
                stop = {"ASCENDING", "DESCENDING", "KEY", "VALUE", "PIC", "PICTURE", "USAGE", "COMP", "COMP-3"}
                for w in re.split(r"[\s,]+", im.group(1)):
                    if w in stop:
                        break
                    it.indexes.append(w)
        if re.search(r"\bCOMP(?:UTATIONAL)?-3\b|\bPACKED-DECIMAL\b", upper):
            it.usage = "packed"
        elif re.search(r"\bCOMP(?:UTATIONAL)?-5\b", upper):
            it.usage = "native"
        elif re.search(r"\bCOMP(?:UTATIONAL)?-1\b|\bFLOAT-SHORT\b", upper):
            it.usage, it.kind, it.size, it.digits, it.scale, it.signed = "float", "num", 4, 16, 4, True
        elif re.search(r"\bCOMP(?:UTATIONAL)?-2\b|\bFLOAT-LONG\b", upper):
            it.usage, it.kind, it.size, it.digits, it.scale, it.signed = "double", "num", 8, 18, 6, True
        elif re.search(r"\bUSAGE\s+(?:IS\s+)?INDEX\b|(?<![A-Z-])INDEX(?![A-Z-])", upper) and "INDEXED" not in upper:
            it.usage, it.kind, it.size, it.digits = "index", "num", 4, 9
        elif re.search(r"\bPOINTER\b", upper):
            raise LayoutError(f"{name}: POINTER items are not supported.")
        elif re.search(r"\b(?:COMP(?:UTATIONAL)?(?:-4)?|BINARY)\b", upper):
            it.usage = "binary"
        it.justified = bool(re.search(r"\bJUST(?:IFIED)?(?:\s+RIGHT)?\b", upper))
        it.blank_zero = bool(re.search(r"\bBLANK\s+(?:WHEN\s+)?ZERO(?:S|ES)?\b", upper))
        vm = re.search(r"\bVALUES?\s+(?:IS\s+)?(ALL\s+)?(\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[xX]['\"][0-9A-Fa-f]*['\"]|[^\s]+)", rest, re.I)
        if vm:
            it.value = parse_literal(vm.group(2))
            it.value_all = bool(vm.group(1))
        pm = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest, re.I)
        if pm and it.usage != "index":
            p = expand_pic(pm.group(1).rstrip("."))
            tail = rest[pm.end():]
            if re.fullmatch(r"[XA9]+", p) and re.search(r"[XA]", p):
                it.kind, it.size, it.pic = "alpha", len(p), p
            elif re.fullmatch(r"N+", p):
                raise LayoutError(f"{name}: national (PIC N) fields are not supported yet.")
            elif re.fullmatch(r"S?[9PV]+", p) and "9" in p and p.count("V") <= 1:
                it.pic = p
                _numeric_from_pic(it, p, tail)
            elif edited_supported(p):
                if it.usage != "display":
                    raise LayoutError(f"{name}: an edited picture must be USAGE DISPLAY.")
                it.kind, it.size, it.pic = "edited", len(p) - p.count("V"), p
            else:
                raise LayoutError(f"{name}: the picture {pm.group(1)} is not supported yet.")
            if it.kind == "num" and it.usage == "display" and it.digits > 38:
                raise LayoutError(f"{name}: more than 38 digits.")
        elif it.usage in ("float", "double"):
            pass  # floating point has no PIC
        elif it.usage in ("packed", "binary", "native") and not pm:
            raise LayoutError(f"{name}: a {it.usage} item needs a PIC clause.")

        while stack and stack[-1].level >= level:
            stack.pop()
        if level == 1 or not stack:
            if level != 1 and not stack:
                raise LayoutError(f"line {line}: {name} appears before a 01 level record.")
            roots.append(it)
            it.record = it.name
        else:
            it.parent = stack[-1]
            it.parent.children.append(it)
            it.record = stack[0].record
        stack.append(it)
        last = it
    for r in roots:
        _place(r, 0)
    return roots


def _place(it: Item, offset: int) -> int:
    """Assign offsets and sizes; returns the size of one occurrence of `it`."""
    it.offset = offset
    if it.kind == "group" and it.children:
        pos = offset
        by_name = {}
        end = offset
        for c in it.children:
            if c.redefines:
                base = by_name.get(c.redefines)
                if base is None:
                    raise LayoutError(f"{c.name} REDEFINES {c.redefines}, which is not an earlier sibling.")
                size = _place(c, base.offset)
                end = max(end, base.offset + size * max(c.occurs, 1))
                continue
            size = _place(c, pos)
            by_name[c.name] = c
            pos += size * max(c.occurs, 1)
            end = max(end, pos)
        it.size = end - offset
    elif it.kind == "group":
        it.kind = "alpha"  # a group with no children and no PIC: treat as text of size 0
        it.size = 0
    return it.size


def walk(it: Item):
    yield it
    for c in it.children:
        yield from walk(c)


@dataclass
class Leaf:
    """An elementary field at a fixed byte position, for generating and decoding records."""
    name: str
    item: Item
    offset: int
    width: int


def leaves(record: Item) -> list[Leaf]:
    """Elementary fields of a record in byte order, tables expanded, REDEFINES overlays skipped.

    Offsets stored on items are for the first occurrence; `delta` adds the shift of enclosing occurrences.
    A field inside a table is labelled with its subscripts, e.g. AMOUNT(3).
    """
    out: list[Leaf] = []

    def visit(it: Item, delta: int, subs: list[int]) -> None:
        if it.redefines:
            return
        for k in range(max(it.occurs, 1)):
            d = delta + k * it.size
            s = subs + ([k + 1] if it.occurs else [])
            if it.kind == "group" and it.children:
                for c in it.children:
                    visit(c, d, s)
            else:
                label = "FILLER" if it.name.startswith("FILLER#") else it.name
                if s:
                    label += "(" + ",".join(map(str, s)) + ")"
                out.append(Leaf(label, it, it.offset + d - record.offset, it.size))  # relative to the item asked about

    if record.children:
        for c in record.children:
            visit(c, 0, [])
    else:
        out.append(Leaf(record.name, record, 0, record.size))
    return out
