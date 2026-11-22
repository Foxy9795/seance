"""Runtime for translated COBOL programs.

COBOL data lives in byte buffers, one per 01 record, exactly as GnuCOBOL lays it out (seance.layout).
Every data item is a typed view into its record, so REDEFINES, group moves, tables, packed decimal and
binary behave the way they do in COBOL. Files, the console, string verbs and paragraph flow (PERFORM,
GO TO, fall-through, STOP RUN) are here too. Behavior was measured against GnuCOBOL with probe programs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .codec import ENC, decode, display_text, encode, store_into, zero
from .cobol_num import NEG_DIGITS, deedit, size_error

D = Decimal


class IdxValue(Decimal):
    """An index name used as a value: DISPLAY shows it as libcob does, with its sign and nine digits."""


class Expr(Decimal):
    """The value of an arithmetic expression given as a function argument (cobc keeps it in a temporary field)."""


class Figurative:
    def __init__(self, name: str, text: str):
        self.name, self.text = name, text

    def fill(self, size: int) -> bytes:
        if not self.text:
            return b""
        raw = self.text.encode(ENC)
        return (raw * (size // len(raw) + 1))[:size]

    def __repr__(self) -> str:
        return self.name


SPACE, ZERO = Figurative("SPACE", " "), Figurative("ZERO", "0")
HIGH, LOW, QUOTE = Figurative("HIGH", "\xff"), Figurative("LOW", "\x00"), Figurative("QUOTE", '"')


def ALL(text: str) -> Figurative:
    return Figurative(f"ALL {text!r}", text)


class StopRun(Exception):
    pass


class NextSentence(Exception):
    """NEXT SENTENCE: carry on after the period that ends the current sentence."""


class GoBack(StopRun):
    pass


class CobolError(RuntimeError):
    """A runtime error that the real program would also hit (bad subscript, missing file)."""


# ------------------------------------------------------------------- references

@dataclass
class Ref:
    name: str
    subs: tuple = ()
    start: int | None = None  # reference modification, 1-based
    length: int | None = None

    def sub(self, start, length=None) -> "Ref":
        return Ref(self.name, self.subs, int(start), None if length is None else int(length))


@dataclass
class FileState:
    name: str
    assign: str
    organization: str  # "line", "sequential", "indexed", "relative" or "sort"
    record: str  # name of the record area (first 01)
    size: int
    status: str | None  # FILE STATUS item
    extra: dict = field(default_factory=dict)  # access, key, alt [(name, dups)], relkey, optional
    mode: str | None = None
    data: bytes = b""
    pos: int = 0
    out: bytearray = field(default_factory=bytearray)
    last_pos: int = -1  # start of the last record read (REWRITE of a sequential file)
    at_end: bool = False  # the last READ reported end of file
    table: dict = field(default_factory=dict)  # keyed files: primary key (bytes, or slot number) -> [seq, record]
    seq: int = 0
    extent: int = 0  # relative: the highest slot the file has ever held (deleting does not shrink it)
    keyref: str | None = None  # the key of reference for sequential reads (START / READ KEY IS)
    last: tuple | None = None  # position of the last record read, in key-of-reference order
    pending: tuple | None = None  # set by START: (position, inclusive)
    cache: list | None = None  # sorted positions for the key of reference
    released: list = field(default_factory=list)  # SORT: records RELEASEd by an input procedure
    returning: list = field(default_factory=list)  # SORT: records left for RETURN
    code: str = "00"  # the last I-O status, FILE STATUS or not
    last_mode: str | None = None  # the mode of the last OPEN (tried): which USE ... ON INPUT / OUTPUT applies
    lin: list = field(default_factory=lambda: [0, 0, 0, 0])  # LINAGE: lines, footing, top, bottom as last checked
    lin_top_due: bool = False  # LINAGE: the top lines have not been written yet
    needs_nl: bool = False  # the last line written AFTER ADVANCING has no line end yet
    locked: bool = False  # CLOSE ... WITH LOCK: no OPEN again in this run (status 38)


class IO:
    """What a run reads and writes: input files by name, console input lines, and everything produced."""

    def __init__(self, files: dict[str, bytes] | None = None, stdin: list[str] | None = None):
        self.inputs = dict(files or {})
        self.stdin = list(stdin or [])
        self.outputs: dict[str, bytes] = {}
        self.stdout = ""
        self.stderr = ""
        self.return_code = 0

    # Helpers for hand-written migrations, which work with text instead of COBOL memory.
    def lines(self, name: str) -> list[str]:
        """The lines of a text (LINE SEQUENTIAL) input file. A missing file reads as empty."""
        rows = self.inputs.get(name, b"").decode(ENC).replace("\r\n", "\n").split("\n")
        return rows[:-1] if rows and rows[-1] == "" else rows

    def records(self, name: str, size: int) -> list[str]:
        """The fixed-length records of an input file, as text."""
        data = self.inputs.get(name, b"").decode(ENC)
        return [data[i:i + size] for i in range(0, len(data), size)]

    def write_lines(self, name: str, rows: list[str]) -> None:
        """Write a text output file the way GnuCOBOL does: trailing spaces dropped, one line per row."""
        self.outputs[name] = "".join(r.rstrip(" ") + "\n" for r in rows).encode(ENC)

    def print(self, *parts) -> None:
        self.stdout += "".join(str(p) for p in parts) + "\n"


# ------------------------------------------------------------------- the program

class Program:
    SPACE, ZERO, HIGH, LOW, QUOTE = SPACE, ZERO, HIGH, LOW, QUOTE
    LOOP_LIMIT = 2_000_000

    def __init__(self, items: dict, records: dict, values: list, conds: dict, files: list, indexes: list, aliases: dict | None = None,
                 linkage: list | None = None, initial: bool = False):
        # items: name -> [record, offset, size, kind, usage, digits, scale, signed, sign, pic, dims, children, justified, blank_zero]
        self.items = dict(items)  # a run adds temporary items (function results): they are not the program's
        self.records = records  # record name -> size
        self.values = values  # [(name, value, all)] initial VALUE clauses, in order
        self.conds = conds  # condition name -> (item name, [(lo, hi)])
        self.file_defs = files  # [name, assign, organization, record, size, status]
        self.index_names = indexes  # index name -> (table item)
        self.aliases = aliases or {}
        self.linkage = linkage or []  # LINKAGE records in PROCEDURE DIVISION USING order
        self.initial = initial
        self.registry: dict = {}
        self._active = False
        self._called = False
        self.io = IO()
        self.reset()

    # ---------------------------------------------------------- state
    def reset(self) -> None:
        for k in [k for k in self.items if k not in self.records and self.items[k][0] == k]:
            del self.items[k]  # temporary function results of the run before
        self.mem = {r: bytearray(size) for r, size in self.records.items()}
        done = {r: bytearray(size) for r, size in self.records.items()}  # bytes already given their first value
        fd_buffers = {f[3] for f in self.file_defs}  # GnuCOBOL starts file record areas as binary zeros (measured)
        for name, spec in self.items.items():
            if not spec[11] and spec[3] != "group" and spec[0] not in fd_buffers:  # elementary
                for off in self._all_offsets(spec):
                    # a REDEFINES overlay comes after the item it redefines; storage starts as the first definition says
                    if any(done[spec[0]][off:off + spec[2]]):
                        continue
                    self.mem[spec[0]][off:off + spec[2]] = zero(self._cspec(spec))
                    done[spec[0]][off:off + spec[2]] = b"\x01" * spec[2]
        for name, value, is_all in self.values:
            spec = self.items[name]
            for off in self._all_offsets(spec):
                self._set_bytes(spec, off, self._initial_bytes(spec, value, is_all))
        self.idx = {n: 1 for n in self.index_names}
        self.files = {f[0]: FileState(*f) for f in self.file_defs}
        self.steps = 0
        # a program that loops over its input takes a step per record or more: the guard grows with the input
        self.loop_limit = max(self.LOOP_LIMIT, 8 * sum(len(v) for v in self.io.inputs.values()))
        self._alters: dict[str, str] = {}  # ALTER: paragraph -> where its GO TO goes now
        self._switches: dict[int, bool] = {}  # SWITCH-n, read from the environment on first use
        self._written: dict[str, bytes] = {}  # files this run wrote and closed, by name: a later OPEN reads these
        self._in_decl: set[str] = set()  # files whose declarative is running: an error in the same file inside it does not nest

    def _all_offsets(self, spec) -> list[int]:
        offs = [spec[1]]
        for count, stride in spec[10]:
            offs = [o + k * stride for o in offs for k in range(count)]
        return offs

    def _initial_bytes(self, spec, value, is_all) -> bytes:
        size = spec[2]
        if isinstance(value, Figurative) or is_all:
            fig = value if isinstance(value, Figurative) else ALL(str(value))
            if spec[3] == "num" and fig is ZERO:
                return zero(self._cspec(spec))
            return fig.fill(size)
        if spec[3] in ("group", "alpha") or (spec[3] == "edited" and isinstance(value, str)):
            # an edited field given a text VALUE holds that text as written (VALUE " <1,111.11")
            return encode(("alpha", "display", 0, 0, False, "none", "", size, spec[12], False), str(value) if not isinstance(value, Decimal) else str(value))
        if spec[3] == "edited":
            return self._shown(encode(self._cspec(spec), Decimal(value)))
        return self._encode_value(spec, value)

    @staticmethod
    def _cspec(spec):
        return (spec[3], spec[4], spec[5], spec[6], spec[7], spec[8], spec[9], spec[2], spec[12], spec[13])

    def resolve(self, name: str) -> str:
        return self.aliases.get(name, name)

    def r(self, name: str, *subs) -> Ref:
        return Ref(self.resolve(name), tuple(subs))

    def _addr(self, ref) -> tuple[str, int, int, list]:
        if isinstance(ref, str):
            ref = Ref(self.resolve(ref))
        spec = self.items[ref.name]
        off = spec[1]
        dims = spec[10]
        subs = list(ref.subs)
        if subs and len(subs) != len(dims):
            raise CobolError(f"{ref.name} needs {len(dims)} subscript(s), got {len(subs)}")
        for (count, stride), s in zip(dims, subs):
            k = int(s)
            if k < 1 or k > count:
                raise CobolError(f"subscript {k} is out of range for {ref.name} (1 to {count})")
            off += (k - 1) * stride
        size = spec[2]
        if ref.start is not None:
            if ref.start < 1 or ref.start > size:
                raise CobolError(f"reference modification ({ref.start}:{ref.length}) is outside {ref.name}")
            off += ref.start - 1
            size = (size - ref.start + 1) if ref.length is None else ref.length
        return spec[0], off, size, spec

    def _bytes(self, ref) -> bytes:
        rec, off, size, _ = self._addr(ref)
        return bytes(self.mem[rec][off:off + size])

    def _set_bytes(self, spec, off, data: bytes) -> None:
        self.mem[spec[0]][off:off + len(data)] = data

    def _is_modified(self, ref) -> bool:
        return isinstance(ref, Ref) and ref.start is not None

    def kind(self, ref) -> str:
        name = ref.name if isinstance(ref, Ref) else self.resolve(ref)
        return "alpha" if self._is_modified(ref) else self.items[name][3]

    # ---------------------------------------------------------- reading values
    def v(self, ref, *subs):
        """The value of a data item: a Decimal for numbers, text otherwise."""
        if isinstance(ref, str):
            ref = Ref(self.resolve(ref), subs)
        rec, off, size, spec = self._addr(ref)
        data = bytes(self.mem[rec][off:off + size])
        if ref.start is not None or spec[3] in ("group", "alpha", "edited"):
            return data.decode(ENC)
        return decode(self._cspec(spec), data)

    def n(self, ref, *subs) -> Decimal:
        """Numeric value. Text is read the way COBOL de-edits it."""
        val = self.v(ref, *subs)
        if isinstance(val, Decimal):
            return val
        if isinstance(ref, str):
            ref = Ref(self.resolve(ref), subs)
        spec = self.items.get(ref.name) if ref.start is None else None
        if spec is not None and spec[3] == "edited":
            from .editing import deedit_numeric

            return deedit_numeric(self._std(val), spec[9])
        return deedit(self._std(val)) if val.strip() else Decimal(0)

    def idx_value(self, name: str) -> int:
        return self.idx[name]

    def idxv(self, name: str) -> Decimal:
        return IdxValue(self.idx[name])

    # ---------------------------------------------------------- MOVE
    def _encode_value(self, spec, value: Decimal) -> bytes:
        cs = self._cspec(spec)
        return encode(cs, store_into(cs, Decimal(value), move=True))

    def _source(self, src):
        """(kind, text_bytes, number) for a MOVE source."""
        if isinstance(src, Figurative):
            return "fig", src, None
        if isinstance(src, Ref):
            rec, off, size, spec = self._addr(src)
            raw = bytes(self.mem[rec][off:off + size])
            if spec[3] == "group" and src.start is None:
                return "group", raw, None  # a group move copies bytes, whatever the receiving item is
            if src.start is not None or spec[3] == "alpha":
                return "alpha", raw, None
            if spec[3] == "edited":
                return "edited", raw, spec
            value = decode(self._cspec(spec), raw)
            return "num", raw, (value, spec)
        if isinstance(src, Decimal):
            return "lit", None, src
        if isinstance(src, int):
            return "lit", None, Decimal(src)
        return "alpha", str(src).encode(ENC), None

    def move(self, src, *targets) -> None:
        kind, raw, num = self._source(src)
        for t in targets:
            ref = t if isinstance(t, Ref) else Ref(self.resolve(t))
            rec, off, size, spec = self._addr(ref)
            buf = self.mem[rec]
            tkind = "alpha" if ref.start is not None else spec[3]
            if tkind == "group" or (tkind == "alpha" and ref.start is not None):
                if kind == "fig":
                    data = raw.fill(size)
                elif kind == "lit":
                    data = _lit_text(num).encode(ENC)[:size].ljust(size, b" ")
                else:
                    data = raw[:size].ljust(size, b" ")
                buf[off:off + size] = data
            elif tkind == "alpha":
                if kind == "fig":
                    data = raw.fill(size)
                else:
                    if kind == "num":
                        value, sspec = num
                        # a DISPLAY number gives its bytes as they are (junk included), without the sign
                        text = _display_digits(sspec, raw) if sspec[4] == "display" else _digits_text(value, sspec)
                    elif kind == "lit":
                        text = _lit_text(num).lstrip("+-")
                    else:
                        text = raw.decode(ENC)
                    data = encode(("alpha", "display", 0, 0, False, "none", spec[9] or "", size, spec[12], False), text)
                buf[off:off + size] = data
            elif tkind == "edited":
                if kind in ("num", "lit"):
                    value = num[0] if kind == "num" else num
                    buf[off:off + size] = self._shown(encode(self._cspec(spec), value))
                elif kind == "fig":
                    buf[off:off + size] = self._shown(encode(self._cspec(spec), Decimal(0))) if raw is ZERO else raw.fill(size)
                elif kind == "alpha":  # alphanumeric to numeric-edited: the text is read as an unsigned integer, then edited
                    buf[off:off + size] = self._shown(encode(self._cspec(spec), _alpha_to_number(raw.decode(ENC))))
                elif kind == "edited":  # edited to edited: de-edited by its own picture, then edited again
                    from .editing import deedit_numeric

                    value = deedit_numeric(self._std(raw.decode(ENC)), num[9])
                    buf[off:off + size] = self._shown(encode(self._cspec(spec), value))
                else:
                    buf[off:off + size] = raw[:size].ljust(size, b" ")
            elif kind == "group":  # a group sent to an elementary number: the bytes, left-justified and padded with spaces
                buf[off:off + size] = raw[:size].ljust(size, b" ")
            else:  # numeric
                if kind == "num":
                    value = num[0]
                elif kind == "lit":
                    value = num
                elif kind == "fig":
                    value = Decimal(0)
                elif kind == "edited":
                    from .editing import deedit_numeric

                    value = deedit_numeric(self._std(raw.decode(ENC)), num[9])
                else:
                    value = _alpha_to_number(raw.decode(ENC))
                buf[off:off + size] = self._encode_value(spec, value)

    @staticmethod
    def _category(spec) -> str:
        if spec[3] == "num":
            return "NUMERIC"
        if spec[3] == "edited":
            return "NUMERIC-EDITED"
        pic = spec[9] or ""
        if pic and any(c in "B0/" for c in pic):
            return "ALPHANUMERIC-EDITED"
        if pic and set(pic) == {"A"}:
            return "ALPHABETIC"
        return "ALPHANUMERIC"

    def initialize(self, *targets, filler: bool = False, to_value: str | None = None, replacing=None, default: bool = False) -> None:
        """INITIALIZE: spaces for text and zeros for numbers by default. With REPLACING only the categories it names
        change (to the value given); ALL TO VALUE gives items their VALUE clause; TO DEFAULT covers the rest."""
        values = None
        if to_value:
            values = {name: (value, is_all) for name, value, is_all in self.values}
        plain = not replacing and not to_value
        for t in targets:
            ref = t if isinstance(t, Ref) else Ref(self.resolve(t))
            spec = self.items[ref.name]
            rec, base, size, _ = self._addr(ref)
            leaves = [(n, self.items[n]) for n in self._leaves(ref.name)] if spec[3] == "group" else [(ref.name, spec)]
            for leaf_name, lspec in leaves:
                if leaf_name.startswith("FILLER#") and not filler:
                    continue
                rel = lspec[1] - spec[1]
                inner = [(c, s) for c, s in lspec[10][len(spec[10]):]]
                offs = [base + rel]
                for count, stride in inner:
                    offs = [o + k * stride for o in offs for k in range(count)]
                cat = self._category(lspec)
                data = None
                if to_value and leaf_name in values:
                    # GnuCOBOL 3.1.2 gives every item with a VALUE its value, whichever category the TO VALUE names
                    data = self._initial_bytes(lspec, *values[leaf_name])
                elif replacing and any(c == cat for c, _ in replacing):
                    src = next(v for c, v in replacing if c == cat)
                    for o in offs:
                        self._move_to_offset(src, lspec, rec, o)
                    continue
                elif plain or default:
                    data = zero(self._cspec(lspec))
                if data is not None:
                    for o in offs:
                        self.mem[rec][o:o + lspec[2]] = data

    def _move_to_offset(self, src, spec, rec: str, off: int) -> None:
        """MOVE src into the item described by spec at a given byte offset (one occurrence of a table entry)."""
        tmp = "__init_target__"
        self.items[tmp] = [rec, off, *spec[2:10], [], [], *spec[12:]]
        try:
            self.move(src, Ref(tmp))
        finally:
            del self.items[tmp]

    def _leaves(self, name: str) -> list[str]:
        out = []
        for c in self.items[name][11]:
            out += self._leaves(c) if self.items[c][3] == "group" else [c]
        return out

    # ---------------------------------------------------------- arithmetic
    @staticmethod
    def pow(a, b) -> Decimal:
        """a ** b as libcob's cob_decimal_pow does it: x ** 0 is 1 (even 0 ** 0), 0 ** y is 0, and a negative base with a fraction
        for an exponent is the one case that is an error."""
        from .intrinsics import Dec, power

        r = power(Dec.of(Decimal(a)), Dec.of(Decimal(b)))
        if r.nan:
            raise InvalidOperation("negative base to a fractional power")
        return r.decimal()

    @staticmethod
    def trunc(x, scale: int) -> Decimal:
        """x cut (not rounded) to `scale` decimals: the quotient a REMAINDER is worked from."""
        return Decimal(x).quantize(Decimal(1).scaleb(-scale), rounding="ROUND_DOWN")

    def compute(self, specs: list, guarded: bool = False) -> bool:
        """Evaluate every target first, then store. Returns False on a size error.

        With ON SIZE ERROR (guarded), targets that overflow or divide by zero are left unchanged.
        Without it, overflowing values lose their high-order digits; a division by zero leaves the target unchanged.
        """
        error = False
        results = []
        for target, fn, rounded in specs:
            ref = target if isinstance(target, Ref) else Ref(self.resolve(target))
            try:
                value = Decimal(fn())
            except (ArithmeticError, InvalidOperation, ZeroDivisionError):
                error = True
                continue
            spec = self.items[ref.name]
            if spec[3] == "num" and spec[4] in ("native", "index"):
                bits = 8 * spec[2]
                lo, hi = (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if spec[7] else (0, 2 ** bits - 1)
                scaled = value.scaleb(spec[6]).to_integral_value(rounding="ROUND_HALF_UP" if rounded else "ROUND_DOWN")
                over = not (lo <= scaled <= hi) if spec[7] else abs(scaled) > hi  # an unsigned item keeps the magnitude of a negative value
            elif spec[3] == "num" and spec[4] in ("float", "double"):
                # no digits to run out of, but the range of the format
                over = abs(value) > (Decimal("3.4028234663852886e38") if spec[4] == "float" else Decimal("1.7976931348623157e308"))
            elif spec[3] == "num":
                over = size_error(value, spec[5], spec[6], spec[7], rounded)
            elif spec[3] == "edited":
                from .cobol_num import edited_digits, edited_has_sign

                ints, decs = edited_digits(spec[9])
                over = size_error(value, ints + decs, decs, edited_has_sign(spec[9]), rounded)
            else:
                over = False
            error = error or over
            results.append((ref, spec, value, rounded, over))
        for ref, spec, value, rounded, over in results:
            if over and guarded:
                continue
            rec, off, size, _ = self._addr(ref)
            cs = self._cspec(spec)
            if spec[3] == "num":
                self.mem[rec][off:off + size] = encode(cs, store_into(cs, value, rounded))
            elif spec[3] == "edited":
                from .cobol_num import edited_digits, store

                ints, decs = edited_digits(spec[9])
                self.mem[rec][off:off + size] = self._shown(encode(cs, store(value, ints + decs, decs, True, rounded)))
            else:
                self.move(Decimal(int(value)), ref)
        return not error

    # ---------------------------------------------------------- conditions
    def c3(self, a, b) -> int:
        """cob_cmp as SEARCH ALL uses it: negative, zero or positive."""
        return -1 if self.cmp(a, "<", b) else (1 if self.cmp(a, ">", b) else 0)

    def cmp(self, a, op: str, b) -> bool:
        a, b = self._comparable(a, b)
        return {"==": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]

    def _operand(self, x):
        """A comparison operand as (number or None, text)."""
        if isinstance(x, Ref):
            val = self.v(x)
            if isinstance(val, Decimal):
                spec = self.items[x.name]
                return val, _digits_text(val, spec)
            return None, val
        if isinstance(x, Figurative):
            return (Decimal(0) if x is ZERO else None), x
        if isinstance(x, (Decimal, int)):
            return Decimal(x), _lit_text(x if isinstance(x, Decimal) else Decimal(x))
        return None, str(x)

    def _comparable(self, a, b):
        na, ta = self._operand(a)
        nb, tb = self._operand(b)
        if na is not None and nb is not None:
            return na, nb
        if isinstance(ta, Figurative) and isinstance(tb, Figurative):
            return ta.text, tb.text
        width = max(len(ta) if isinstance(ta, str) else 0, len(tb) if isinstance(tb, str) else 0, 1)
        sa = ta.fill(width).decode(ENC) if isinstance(ta, Figurative) else ta.ljust(width)
        sb = tb.fill(width).decode(ENC) if isinstance(tb, Figurative) else tb.ljust(width)
        if self.collating is not None and (isinstance(a, Ref) or isinstance(b, Ref)):
            # PROGRAM COLLATING SEQUENCE: cobc applies it when data takes part; two literals compare natively
            if self._coll_map is None:
                self._coll_map = {c: self.collating[c] for c in range(256)}
            sa, sb = sa.translate(self._coll_map), sb.translate(self._coll_map)
        return sa, sb

    def cond(self, name: str, *subs) -> bool:
        target, choices = self.conds[name][:2]
        value = Ref(target, subs)
        for lo, hi in choices:
            if hi is None and self.cmp(value, "==", lo):
                return True
            if hi is not None and self.cmp(value, ">=", lo) and self.cmp(value, "<=", hi):
                return True
        return False

    def set_true(self, name: str, *subs) -> None:
        target, choices = self.conds[name][:2]
        self.move(choices[0][0], Ref(target, subs))

    def switch(self, n: int) -> bool:
        """SWITCH-n: GnuCOBOL reads COB_SWITCH_n (ON or OFF) when the program starts; SET can change it."""
        if n not in self._switches:
            import os

            self._switches[n] = os.environ.get(f"COB_SWITCH_{n}", "OFF").strip().upper() == "ON"
        return self._switches[n]

    def set_switch(self, n: int, on: bool) -> None:
        self._switches[n] = on

    def in_class(self, x, chars: str) -> bool:
        """A CLASS test: every character of the item is one the class allows."""
        text = self._text(x)
        return all(c in chars for c in text)

    def alter(self, para: str, target: str) -> None:
        """ALTER para TO PROCEED TO target."""
        self._alters[para] = target

    def altered(self, para: str, target: str | None) -> str:
        """Where the GO TO of an ALTERed paragraph goes now."""
        where = self._alters.get(para, target)
        if where is None:
            raise CobolError(f"GO TO in {para} was never pointed anywhere by an ALTER")
        return where

    def set_false(self, name: str, *subs) -> None:
        """SET condition TO FALSE: the value its 88 level names after FALSE IS."""
        entry = self.conds[name]
        self.move(entry[2], Ref(entry[0], subs))

    def is_numeric(self, ref) -> bool:
        val = self.v(ref)
        if isinstance(val, Decimal):
            raw = self._bytes(ref)
            spec = self.items[ref.name if isinstance(ref, Ref) else self.resolve(ref)]
            if spec[4] == "display":
                text = raw.decode(ENC)
                return all(c.isdigit() or c in "+-pqrstuvwxy" for c in text)
            if spec[4] == "packed":  # every digit nibble 0-9; the sign nibble is C or D when signed, F when not
                nibbles = raw.hex()
                return all(c in "0123456789" for c in nibbles[:-1]) and nibbles[-1] in ("cd" if spec[7] else "f")
            return True
        return val != "" and val.isdigit()

    def is_alphabetic(self, ref) -> bool:
        return all(c.isalpha() or c == " " for c in str(self.v(ref)))

    # ---------------------------------------------------------- indexes
    def set_index(self, name: str, value) -> None:
        if name in self.idx:
            self.idx[name] = int(value)
        else:
            self.move(Decimal(int(value)), name)

    def occurs(self, name: str) -> int:
        spec = self.items[self.resolve(name)]
        return spec[10][-1][0] if spec[10] else 1

    # ---------------------------------------------------------- files
    def fn_uint(self, n) -> "Ref":
        from . import intrinsics

        return self._fn_store(intrinsics.Result("uint", n=int(n)))

    def length_dyn(self, ref, occurs: int, elem: int, dep: str) -> int:
        """LENGTH of a group with an OCCURS DEPENDING ON table: the maximum less the entries beyond the DEPENDING ON item."""
        n = max(0, min(int(self.n(dep)), occurs))
        return self._addr(ref)[2] - (occurs - n) * elem

    def length_of(self, ref) -> int:
        """LENGTH OF: the bytes of an item (one occurrence of a table entry)."""
        ref = ref if isinstance(ref, Ref) else Ref(self.resolve(ref))
        return self._addr(ref)[2]

    def delete_file(self, *names: str) -> bool:
        """DELETE FILE: the files are gone afterwards, for this run and for any later OPEN. Status 00, or 41 when open."""
        ok = True
        for name in names:
            f = self.files[name]
            if f.mode:
                self._status(f, "41")
                ok = False
                continue
            if self._file_data(f.assign) is None and f.assign not in self.io.outputs:
                self._fail(f, "35", f"DELETE FILE {f.name}: file {f.assign} does not exist")
                ok = False
                continue
            self.io.inputs.pop(f.assign, None)
            self.io.outputs.pop(f.assign, None)
            self._written.pop(f.assign, None)
            self._status(f, "00")
        return ok

    def open(self, name: str, mode: str) -> None:
        f = self.files[name]
        if f.mode:
            f.last_mode = f.mode
            self._fail(f, "41", f"OPEN {name}: the file is already open")
            return
        f.last_mode = mode
        if f.locked:
            self._fail(f, "38", f"OPEN {name}: the file was closed WITH LOCK")
            return
        if f.organization in ("indexed", "relative"):
            return self._k_open(f, mode)
        f.mode = mode
        f.last_pos = -1
        f.at_end = False
        if mode in ("input", "io"):
            if self._file_data(f.assign) is None:
                if f.extra.get("optional"):
                    f.data, f.pos = b"", 0
                    self._status(f, "05")
                    if mode == "io":
                        f.out = bytearray()
                    return
                f.mode = None
                self._fail(f, "35", f"OPEN INPUT {name}: file {f.assign} does not exist")
                return
            f.data, f.pos = self._file_data(f.assign), 0
        absent_extend = False
        if mode == "extend" and self._file_data(f.assign) is None:
            if not f.extra.get("optional"):
                f.mode = None
                self._fail(f, "35", f"OPEN EXTEND {name}: file {f.assign} does not exist")  # measured: 35, not created
                return
            absent_extend = True
        if mode in ("output", "extend", "io"):
            f.out = bytearray(self._file_data(f.assign) or b"") if mode in ("extend", "io") else bytearray()
        if absent_extend:
            self._status(f, "05")
            return
        if f.extra.get("linage") and mode in ("output", "extend"):
            if not self._lin_check(f):
                f.mode = None
                self._fail(f, "57", f"OPEN {name}: the LINAGE values are not usable")
                return
            f.lin_top_due = True
            self.move(Decimal(1), f.extra["linage"]["counter"])
        self._status(f, "00")

    def _file_data(self, assign: str) -> bytes | None:
        """What a file holds now: what this run last wrote to it, or else the input the run was given."""
        if assign in self._written:
            return self._written[assign]
        return self.io.inputs.get(assign)

    def close(self, name: str, how: str = "") -> None:
        """how: "" ; "reel" (REEL or UNIT: a disk file stays open, status 07, except an indexed one, which closes);
        "norewind" (WITH NO REWIND: closes, 07 for a sequential or relative file); "lock" (WITH LOCK: closes, and
        any later OPEN fails with 38). Measured on GnuCOBOL 3.1.2."""
        f = self.files[name]
        if not f.mode:
            self._fail(f, "42", f"CLOSE {name}: the file is not open")
            return
        if how == "reel" and f.organization != "indexed":
            self._status(f, "07")
            return
        f.locked = f.locked or how == "lock"
        if f.organization in ("indexed", "relative"):
            if f.mode in ("output", "extend", "io"):
                self.io.outputs[f.assign] = self._written[f.assign] = self._k_dump(f)
        elif f.mode in ("output", "extend", "io"):
            if f.needs_nl:
                f.needs_nl = False
                f.out += b"\n"
            self.io.outputs[f.assign] = self._written[f.assign] = bytes(f.out)
        f.mode = None
        self._status(f, "07" if how == "norewind" and f.organization in ("sequential", "line", "relative") else "00")

    declaratives: list = []  # [(section, [file names or INPUT | OUTPUT | I-O | EXTEND])], set by the translated program

    def _status(self, f: FileState, code: str) -> None:
        f.code = code
        if f.status:
            self.move(code, f.status)

    def _declarative(self, f: FileState) -> str | None:
        """The USE AFTER ERROR section for a file: one that names it, else one for the mode it was last opened in."""
        mode = {"input": "INPUT", "output": "OUTPUT", "io": "I-O", "extend": "EXTEND"}.get(getattr(f, "last_mode", None) or "")
        named = None
        for section, targets in self.declaratives:
            if f.name in targets:
                return section
            if named is None and mode and mode in targets:
                named = section
        return named

    def _run_declarative(self, f: FileState) -> bool:
        section = self._declarative(f)
        if section is None or f.name in self._in_decl:
            return False
        self._in_decl.add(f.name)
        try:
            self.perform(section)
        finally:
            self._in_decl.discard(f.name)
        return True

    def _fail(self, f: FileState, code: str, message: str) -> bool:
        """A file error (3x, 4x): set the status; then the declarative runs, or with a FILE STATUS the program goes
        on; with neither the run stops, as GnuCOBOL's does."""
        self._status(f, code)
        if self._run_declarative(f) or f.status:
            return None  # a hard error: not False, so neither AT END / INVALID KEY nor their NOT branches run
        raise CobolError(f"{message} (status = {code})")

    def _done(self, f: FileState, ok: bool, phrase: bool) -> bool:
        """After a READ, WRITE, REWRITE, DELETE or START: at end or invalid key with no phrase for it runs the declarative."""
        if not ok and not phrase and getattr(f, "code", "00")[:1] in ("1", "2"):
            self._run_declarative(f)
        return ok

    def read(self, name: str, into=None, key=None, phrase: bool = False) -> bool:
        """READ: True when a record was read, False at end of file (or INVALID KEY for a keyed READ)."""
        f = self.files[name]
        if f.organization in ("indexed", "relative"):
            ok = self._k_read(f, key)
        else:
            ok = self._seq_read(f)
        if ok and into is not None:
            self.move(Ref(f.record), into)
        return self._done(f, ok, phrase)

    def read_next(self, name: str, into=None, phrase: bool = False, previous: bool = False) -> bool:
        """READ NEXT, or READ PREVIOUS (a keyed file: the record before the one last read, in key order)."""
        f = self.files[name]
        ok = self._k_next(f, previous) if f.organization in ("indexed", "relative") else self._seq_read(f)
        if ok and into is not None:
            self.move(Ref(f.record), into)
        return self._done(f, ok, phrase)

    def _seq_read(self, f: FileState) -> bool:
        f.last_pos = -1  # no record is current until this READ delivers one (REWRITE after a failed READ: status 43)
        if f.mode not in ("input", "io"):
            return self._fail(f, "47", f"READ {f.name}: the file is not open for input")
        buf = self.mem[f.record]
        if f.pos >= len(f.data):
            if f.at_end:  # reading again after the end was reported (measured: status 46, fatal without FILE STATUS)
                return self._fail(f, "46", f"READ after unsuccessful READ/START for file {f.name}")
            f.at_end = True
            self._status(f, "10")
            return False
        f.last_pos = f.pos
        if f.organization == "line":
            end = f.data.find(b"\n", f.pos)
            line = f.data[f.pos:] if end < 0 else f.data[f.pos:end]
            f.pos = len(f.data) if end < 0 else end + 1
            line = line.rstrip(b"\r")
            buf[0:f.size] = line[:f.size].ljust(f.size, b" ")
            self._set_depending(f, min(len(line), f.size))
            self._status(f, "00")
        elif f.extra.get("variable"):  # 4-byte header: 2-byte big-endian length, 2 zero bytes
            while f.pos < len(f.data) and f.data[f.pos:f.pos + 1] in (b"\n", b"\r", b"\f"):
                f.pos += 1
            if f.pos + 4 > len(f.data):
                f.at_end = True
                self._status(f, "10")
                return False
            n = int.from_bytes(f.data[f.pos:f.pos + 2], "big")
            chunk = f.data[f.pos + 4:f.pos + 4 + n]
            f.pos += 4 + n
            buf[0:min(len(chunk), f.size)] = chunk[:f.size]  # the bytes after a short record stay as they were (measured)
            self._set_depending(f, min(len(chunk), f.size))
            self._status(f, "00")
        else:
            chunk = f.data[f.pos:f.pos + f.size]
            f.pos += f.size
            buf[0:len(chunk)] = chunk
            self._set_depending(f, len(chunk))
            self._status(f, "00" if len(chunk) == f.size else "04")
        return True

    # ---------------------------------------------------------- LINAGE
    def _lin_check(self, f: FileState) -> bool:
        """file_linage_check: read the LINAGE values; False (and the counter set to 0) when they are not usable."""
        lin = f.extra["linage"]

        def val(x):
            return 0 if x is None else int(x) if isinstance(x, int) else int(self.n(x))
        lines, foot, top, bot = val(lin["lines"]), val(lin["foot"]), val(lin["top"]), val(lin["bottom"])
        f.lin = [lines, foot, top, bot]
        if lines < 1 or (lin["foot"] is not None and not 1 <= foot <= lines) or top < 0 or bot < 0:
            self.move(Decimal(0), lin["counter"])
            return False
        return True

    def _linage_write(self, f: FileState, record: str, advancing, eop: bool) -> bool:
        """WRITE on a file with a LINAGE clause (libcob's cob_linage_write_opt, measured on 3.1.2): the top lines come
        before the first record, a WRITE with no ADVANCING is AFTER ADVANCING 1, the counter starts at 1, and a page
        that overflows is padded to its length, closed by the bottom lines and opened with the top lines."""
        import sys

        lin = f.extra["linage"]
        counter = lin["counter"]
        # a LINAGE file is written as text: on Windows GnuCOBOL's C library turns each \n into \r\n (a LINE SEQUENTIAL
        # file's lines are compared without the CR, so it keeps \n)
        nl = b"\r\n" if sys.platform == "win32" and f.organization != "line" else b"\n"
        size = self.items[record][2] if record in self.items else f.size
        data = bytes(self.mem[f.record][0:size]).rstrip(b" ")
        out = bytearray()
        if f.lin_top_due:
            f.lin_top_due = False
            out += nl * f.lin[2]
        when, amount = advancing if advancing else ("after", 1)
        end_of_page = False
        failed = False

        def advance() -> None:
            nonlocal end_of_page, failed
            lines, foot, top, bot = f.lin
            ctr = int(self.n(counter))
            if ctr == 0:
                failed = True
                return
            if amount == "page":
                out.extend(nl * max(0, lines - ctr) + nl * bot)
                if not self._lin_check(f):
                    failed = True
                    return
                out.extend(nl * f.lin[2])
                self.move(Decimal(1), counter)
                return
            self.move(Decimal(ctr + int(amount)), counter)
            now = ctr + int(amount)
            if eop and foot and now >= foot:
                end_of_page = True
            if now > lines:
                if eop:
                    end_of_page = True
                out.extend(nl * max(0, lines - ctr) + nl * bot)
                if not self._lin_check(f):
                    failed = True
                    return
                self.move(Decimal(1), counter)
                out.extend(nl * f.lin[2])
            else:
                out.extend(nl * max(0, int(amount) - 1))

        if when == "after":
            advance()
            out += data + nl
        else:
            out += data + nl
            advance()
        if failed:
            return self._fail(f, "57", f"WRITE {f.name}: the LINAGE values are not usable")
        f.out += out
        self._status(f, "00")
        return not end_of_page if eop else True

    def _dep_len(self, f: FileState) -> int:
        """The record length the DEPENDING ON item holds now. The item may sit inside the record area (and so hold
        record data): cob_get_int reads what digits it finds, and Séance does the same."""
        try:
            return int(self.n(f.extra["depending"]))
        except (ValueError, InvalidOperation):
            raw = bytes(self._bytes(self.r(f.extra["depending"]))).decode(ENC)
            digits = "".join(c if c.isdigit() else str(ord(c) & 0x0F if (ord(c) & 0x0F) < 10 else 0) for c in raw)
            return int(digits or "0")

    def _set_depending(self, f: FileState, n: int) -> None:
        if f.extra.get("depending"):
            self.move(Decimal(n), f.extra["depending"])

    def _file_of(self, record: str) -> tuple[FileState, str]:
        key = self.resolve(record)
        buffer = self.items[key][0]
        owners = [x for x in self.files.values() if x.record == buffer]
        # SAME RECORD AREA: several files share the buffer; the record's own FD says which file it is
        f = next((x for x in owners if key in x.extra.get("records", ())), owners[0] if owners else None)
        if f is None:
            raise CobolError(f"{record}: no file has this record")
        return f, key

    def write(self, record: str, src=None, advancing=None, phrase: bool = False, file: str | None = None, eop: bool = False) -> bool:
        """WRITE. advancing: None, ("before" | "after", n) or ("before" | "after", "page"). False on INVALID KEY.
        file: the file to write, when the record area is shared (SORT ... GIVING writes each output file)."""
        f, record = (self.files[file], self.resolve(record)) if file else self._file_of(record)
        if src is not None:
            self.move(src, record)
        if f.organization in ("indexed", "relative"):
            return self._done(f, self._k_write(f, record), phrase)
        if f.mode not in ("output", "extend"):  # a sequential file opened I-O can be read and rewritten, not written (48)
            return self._fail(f, "48", f"WRITE {record}: the file is not open for output")
        if f.extra.get("linage"):
            return self._linage_write(f, record, advancing, eop)
        size = self.items[record][2] if record in self.items else f.size
        if f.extra.get("depending"):  # RECORD VARYING ... DEPENDING ON: the item gives this record's length
            if f.extra.get("minrec") and self._dep_len(f) < f.extra["minrec"]:
                return self._fail(f, "44", f"WRITE {record}: the record is shorter than the smallest this file allows")
            size = max(0, min(self._dep_len(f), f.size))
        data = bytes(self.mem[f.record][0:size])
        if f.organization == "line":
            data = data.rstrip(b" ")
        elif f.extra.get("variable"):
            data = len(data).to_bytes(2, "big") + b"\x00\x00" + data
        nl = b"\n"
        pre = post = b""
        if advancing:
            when, amount = advancing
            gap = b"\f" if amount == "page" else (nl * int(amount) if int(amount) else b"\r")  # ADVANCING 0 returns to the line start
            if when == "after":
                pre = gap
            else:
                post = gap
        elif f.organization == "line":
            post = nl
        f.out += pre + data + post
        # libcob (flag_needs_nl): a WRITE AFTER ADVANCING leaves the last line unended, and CLOSE ends it; a WRITE BEFORE
        # ADVANCING ends it, and so does a plain WRITE to a LINE SEQUENTIAL file
        if advancing and advancing[0] == "after":
            f.needs_nl = True
        elif advancing or f.organization == "line":
            f.needs_nl = False
        self._status(f, "00")
        return True

    def rewrite(self, record: str, src=None, phrase: bool = False) -> bool:
        f, record = self._file_of(record)
        if src is not None:
            self.move(src, record)
        if f.organization in ("indexed", "relative"):
            return self._done(f, self._k_rewrite(f, record), phrase)
        read_at, f.last_pos = f.last_pos, -1  # a REWRITE (or a failed READ) uses up the READ it follows
        if f.mode != "io":
            return self._fail(f, "49", f"REWRITE {record}: the file is not open I-O")
        if read_at < 0:
            return self._fail(f, "43", f"REWRITE {record}: no record was read first")
        if f.organization == "sequential":  # a record sequential file rewrites a record of exactly the size read (cob_rewrite)
            own = self.items[record][2] if record in self.items else f.size
            if own != f.size or (f.extra.get("depending") and self._dep_len(f) != f.size):
                return self._fail(f, "44", f"REWRITE {record}: the record is not the size of the record read")
        f.last_pos = read_at
        data = bytes(self.mem[f.record][0:f.size])
        if f.organization == "line":
            old_end = f.out.find(b"\n", f.last_pos)
            old_end = len(f.out) if old_end < 0 else old_end
            f.out[f.last_pos:old_end] = data.rstrip(b" ")
        else:
            f.out[f.last_pos:f.last_pos + f.size] = data
        f.last_pos = -1
        self._status(f, "00")
        return True

    def delete(self, name: str, phrase: bool = False) -> bool:
        f = self.files[name]
        if f.organization not in ("indexed", "relative"):
            raise CobolError(f"DELETE {name}: only indexed and relative files can delete records")
        return self._done(f, self._k_delete(f), phrase)

    # -- indexed and relative files (an in-memory copy of what GnuCOBOL keeps in its file)
    def _kspec(self, name):
        spec = self.items[name]
        return spec[1], spec[2]

    def _kval(self, f: FileState, keyname: str, rec: bytes):
        off, size = self._kspec(keyname)
        return bytes(rec[off:off + size])

    def _primary(self, f: FileState, rec: bytes):
        if f.organization == "relative":
            return int(self.n(f.extra["relkey"])) if f.extra.get("relkey") else 0
        return self._kval(f, f.extra["key"], rec)

    def _k_insert(self, f: FileState, rec: bytes, pk) -> str:
        if pk in f.table:
            return "22"
        dup = False
        for name, dups in f.extra.get("alt", []):
            v = self._kval(f, name, rec)
            same = any(self._kval(f, name, r) == v for _, r in f.table.values())
            if same and not dups:
                return "22"
            dup = dup or same
        f.seq += 1
        f.table[pk] = [f.seq, bytes(rec)]
        f.cache = None
        return "02" if dup else "00"

    def _k_open(self, f: FileState, mode: str) -> None:
        f.mode, f.last, f.pending, f.cache = mode, None, None, None
        f.keyref = f.extra.get("key")
        f.table, f.seq, f.extent = {}, 0, 0
        if mode in ("input", "io", "extend"):
            if self._file_data(f.assign) is None:
                if f.extra.get("optional") or (mode == "extend" and f.organization != "indexed"):
                    self._status(f, "05")
                    return
                f.mode = None
                self._fail(f, "35", f"OPEN {mode.upper()} {f.name}: file {f.assign} does not exist")
                return
            data = self._file_data(f.assign)
            step = f.size + (9 if f.organization == "relative" else 0)
            for i in range(0, len(data) - step + 1, step):
                chunk = data[i:i + step]
                if f.organization == "relative":
                    slot, rec = int(chunk[:9] or b"0"), chunk[9:]
                    if slot > 0:
                        f.seq += 1
                        f.table[slot] = [f.seq, bytes(rec)]
                        f.extent = max(f.extent, slot)
                else:
                    self._k_insert(f, chunk, self._kval(f, f.extra["key"], chunk))
        self._status(f, "00")

    def _k_dump(self, f: FileState) -> bytes:
        if f.organization == "relative":
            return b"".join(b"%09d" % slot + f.table[slot][1].ljust(f.size, b" ") for slot in sorted(f.table))
        return b"".join(f.table[k][1].ljust(f.size, b" ") for k in sorted(f.table))  # shorter records (DEPENDING ON) padded

    def _positions(self, f: FileState) -> list:
        """(position, primary key) in the order of the key of reference."""
        if f.cache is None:
            if f.organization == "relative":
                f.cache = [((k,), k) for k in sorted(f.table)]
            elif f.keyref == f.extra.get("key") or f.keyref is None:
                f.cache = [((k,), k) for k in sorted(f.table)]
            else:
                f.cache = sorted(((self._kval(f, f.keyref, r), seq), k) for k, (seq, r) in f.table.items())
        return f.cache

    def _pos_of(self, f: FileState, pk) -> tuple:
        if f.organization == "relative" or f.keyref in (None, f.extra.get("key")):
            return (pk,)
        seq, rec = f.table[pk]
        return (self._kval(f, f.keyref, rec), seq)

    def _deliver(self, f: FileState, pk) -> None:
        rec = f.table[pk][1]
        buf = self.mem[f.record]
        buf[0:len(rec)] = rec
        if f.extra.get("depending"):
            buf[len(rec):f.size] = b" " * (f.size - len(rec))  # the rest of the area after a short record is spaces
        self._set_depending(f, len(rec))
        if f.organization == "relative" and f.extra.get("relkey"):
            self.move(Decimal(pk), f.extra["relkey"])
        f.last = self._pos_of(f, pk)

    def _k_next(self, f: FileState, previous: bool = False) -> bool:
        if f.mode not in ("input", "io"):
            return self._fail(f, "47", f"READ {f.name}: the file is not open for input")
        import bisect

        order = self._positions(f)
        keys = [p for p, _ in order]
        if previous:
            if f.pending is not None:
                pos, inclusive = f.pending
                i = bisect.bisect_right(keys, pos) - 1 if inclusive else bisect.bisect_left(keys, pos) - 1
                f.pending = None
            elif f.last is None:
                i = len(order) - 1
            else:
                i = bisect.bisect_left(keys, f.last) - 1
        elif f.pending is not None:
            pos, inclusive = f.pending
            i = bisect.bisect_left(keys, pos) if inclusive else bisect.bisect_right(keys, pos)
            f.pending = None
        elif f.last is None:
            i = 0
        else:
            i = bisect.bisect_right(keys, f.last)
        if i >= len(order) or i < 0:
            if f.at_end:  # reading again after the end was reported
                return self._fail(f, "46", f"READ after unsuccessful READ/START for file {f.name}")
            f.at_end = True
            self._status(f, "10")
            return False
        f.at_end = False
        pk = order[i][1]
        self._deliver(f, pk)
        self._status(f, "00")  # GnuCOBOL (BDB) reports 00 even when more records share the alternate key (measured)
        return True

    def _k_read(self, f: FileState, key=None) -> bool:
        """A READ of a keyed file: by key when access is RANDOM, or DYNAMIC without NEXT."""
        if f.extra.get("access", "sequential") == "sequential":
            return self._k_next(f)
        if f.mode not in ("input", "io"):
            return self._fail(f, "47", f"READ {f.name}: the file is not open for input")
        if key is not None:
            f.keyref, f.cache = self.resolve(key), None
        rec = bytes(self.mem[f.record][0:f.size])
        if f.organization == "relative":
            pk = self._primary(f, rec)
            found = pk if pk in f.table else None
        elif f.keyref in (None, f.extra.get("key")):
            pk = self._kval(f, f.extra["key"], rec)
            found = pk if pk in f.table else None
        else:
            v = self._kval(f, f.keyref, rec)
            found = next((k for (p, k) in self._positions(f) if p[0] == v), None)
        if found is None:
            self._status(f, "23")
            return False
        self._deliver(f, found)
        self._status(f, "00")
        return True

    def _k_write(self, f: FileState, record: str) -> bool:
        if f.mode not in ("output", "extend", "io") or (f.mode == "io" and f.extra.get("access", "sequential") == "sequential"):
            return self._fail(f, "48", f"WRITE {record}: the file is not open for output")
        rec = bytes(self.mem[f.record][0:f.size])
        if f.extra.get("depending"):
            if f.extra.get("minrec") and self._dep_len(f) < f.extra["minrec"]:
                return self._fail(f, "44", f"WRITE {record}: the record is shorter than the smallest this file allows")
            rec = rec[:max(0, min(self._dep_len(f), f.size))]
        seq_access = f.extra.get("access", "sequential") == "sequential"
        if f.organization == "relative":
            if seq_access and f.mode in ("output", "extend"):
                pk = (max(f.table) if f.table else 0) + 1
                if f.extra.get("relkey"):
                    self.move(Decimal(pk), f.extra["relkey"])
            else:
                pk = self._primary(f, rec)
                if pk < 1:
                    self._status(f, "24")
                    return False
            if pk in f.table:
                self._status(f, "22")
                return False
            f.seq += 1
            f.table[pk] = [f.seq, rec]
            f.extent = max(f.extent, pk)
            f.cache = None
            self._status(f, "00")
            return True
        pk = self._kval(f, f.extra["key"], rec)
        if seq_access and f.mode in ("output", "extend") and f.table and pk <= max(f.table):
            self._status(f, "21")  # sequential access must write in ascending key order
            return False
        code = self._k_insert(f, rec, pk)
        self._status(f, code)
        return code in ("00", "02")

    def _k_rewrite(self, f: FileState, record: str) -> bool:
        if f.mode != "io":
            return self._fail(f, "49", f"REWRITE {record}: the file is not open I-O")  # FILE STATUS and declaratives apply
        rec = bytes(self.mem[f.record][0:f.size])
        pk = self._primary(f, rec)
        if f.extra.get("access", "sequential") == "sequential":
            if f.last is None or f.at_end:
                return self._fail(f, "43", f"REWRITE {f.name}: no successful READ just before")
            if f.organization == "relative":
                # a relative file rewrites the record last read, whatever the relative key item holds now
                pk = next((k for p, k in self._positions(f) if p == f.last), None)
                if pk is None:
                    return self._fail(f, "43", f"REWRITE {f.name}: the record read is gone")
            elif self._pos_of(f, pk) != f.last if pk in f.table else True:
                self._status(f, "21")
                return False
        if pk not in f.table:
            self._status(f, "23")
            return False
        dup = False
        for name, dups in f.extra.get("alt", []):
            v = self._kval(f, name, rec)
            clash = any(k != pk and self._kval(f, name, r) == v for k, (_, r) in f.table.items())
            if clash and not dups:
                self._status(f, "22")
                return False
            dup = dup or clash
        f.table[pk][1] = rec
        f.cache = None
        self._status(f, "02" if dup else "00")
        return True

    def _k_delete(self, f: FileState) -> bool:
        if f.mode != "io":
            return self._fail(f, "49", f"DELETE {f.name}: the file is not open I-O")
        if f.extra.get("access", "sequential") == "sequential":
            if f.last is None:
                self._status(f, "43")
                return False
            pk = next((k for p, k in self._positions(f) if p == f.last), None)
        else:
            pk = self._primary(f, bytes(self.mem[f.record][0:f.size]))
            if f.organization == "relative" and pk < 1:
                self._status(f, "24")  # slot 0 is outside the file (measured)
                return False
            if f.organization == "relative" and pk not in f.table and pk <= f.extent:
                self._status(f, "00")  # an empty slot inside the file deletes without complaint (measured)
                return True
        if pk is None or pk not in f.table:
            self._status(f, "23")
            return False
        del f.table[pk]
        f.cache = None
        self._status(f, "00")
        return True

    def start(self, name: str, op: str = ">=", key=None, phrase: bool = False) -> bool:
        """START: position the file so the next READ NEXT returns the first record whose key satisfies op."""
        f = self.files[name]
        if f.mode not in ("input", "io"):
            return self._fail(f, "47", f"START {name}: the file is not open for input")
        return self._done(f, self._start(f, op, key), phrase)

    def _start(self, f: FileState, op: str, key) -> bool:
        name = f.name
        if op == "first":
            f.keyref, f.cache, f.last, f.pending = f.extra.get("key"), None, None, None
            self._status(f, "00" if f.table else "23")
            return bool(f.table)
        if op == "last":  # START LAST: the next READ PREVIOUS (or READ NEXT) delivers the last record in key order
            f.keyref, f.cache, f.last, f.pending = f.extra.get("key"), None, None, None
            order = self._positions(f)
            if not order:
                self._status(f, "23")
                return False
            f.pending = (order[-1][0], True)
            self._status(f, "00")
            return True
        rec = bytes(self.mem[f.record][0:f.size])
        if f.organization == "relative":
            f.keyref = None
            target = (self._primary(f, rec),)
            width = None
        else:
            keyname = self.resolve(key) if key is not None else f.extra["key"]
            off, width = self._kspec(keyname)
            # a START on a leading part of a key (a group or field at the key's offset) compares that many bytes
            ref = next((k for k in [f.extra["key"]] + [a for a, _ in f.extra.get("alt", [])] if self._kspec(k)[0] == off), f.extra["key"])
            if self._kspec(ref)[1] < width:
                ref = keyname
            f.keyref, f.cache = ref, None
            target = (rec[off:off + width],)
        order = self._positions(f)

        def part(p):
            return p[0] if width is None else p[0][:width]

        tv = target[0]
        tests = {"=": lambda v: v == tv, ">": lambda v: v > tv, ">=": lambda v: v >= tv, "<": lambda v: v < tv, "<=": lambda v: v <= tv}
        hits = [i for i, (p, _) in enumerate(order) if tests[op](part(p))]
        if not hits:
            f.pending = None
            self._status(f, "23")
            return False
        i = hits[-1] if op in ("<", "<=") else hits[0]
        f.pending, f.last = (order[i][0], True), None
        self._status(f, "00")
        return True

    # ---------------------------------------------------------- SORT and MERGE
    collating: bytes | None = None  # PROGRAM COLLATING SEQUENCE: the weight of each byte (None: native order)
    _coll_map: dict | None = None

    def _sort_cmp(self, keys, collating=None):
        def value(name, rec):
            spec = self.items[name]
            raw = rec[spec[1]:spec[1] + spec[2]]
            if spec[3] == "num":
                return decode(self._cspec(spec), raw)
            return raw.translate(collating) if collating is not None else raw

        def cmp(a, b):
            for ascending, name in keys:
                x, y = value(name, a), value(name, b)
                if x != y:
                    return (-1 if x < y else 1) * (1 if ascending else -1)
            return 0
        return cmp

    def sort(self, sd: str, keys: list, using=None, giving=None, input_proc=None, output_proc=None, collating=...) -> None:
        """SORT or MERGE: keys is [(ascending, item)]. GnuCOBOL's sort is stable (measured). collating: the weights
        of the SORT's COLLATING SEQUENCE (None: native); left out, the program collating sequence."""
        if collating is ...:
            collating = self.collating
        from functools import cmp_to_key

        f = self.files[sd]
        if using:
            records = []
            for name in using:
                uf = self.files[name]
                self.open(name, "input")
                while uf.mode and self.read_next(name):
                    rec = bytes(self.mem[uf.record][0:uf.size])
                    records.append(rec[:f.size].ljust(f.size, b" "))
                self.close(name)
        else:
            f.released = []
            self.perform(*input_proc)
            records = f.released
        records = sorted(records, key=cmp_to_key(self._sort_cmp(keys, collating)))
        if giving:
            for name in giving:
                gf = self.files[name]
                self.open(name, "output")
                for rec in records:
                    self.mem[gf.record][0:gf.size] = rec[:gf.size].ljust(gf.size, b" ")
                    self.write(gf.record, file=name)
                self.close(name)
        else:
            f.returning = list(records)
            self.perform(*output_proc)
        if "SORT-RETURN" in self.items:
            self.move(Decimal(0), "SORT-RETURN")

    def sort_table(self, table: str, keys: list, collating=...) -> None:
        """SORT of an OCCURS table in storage: reorder its occurrences by the keys (stable). collating: the weights of the
        COLLATING SEQUENCE phrase (None: native); left out, the program collating sequence."""
        if collating is ...:
            collating = self.collating
        from functools import cmp_to_key

        spec = self.items[self.resolve(table)]
        if not spec[10]:
            raise CobolError(f"SORT {table}: it is not a table")
        count, stride = spec[10][-1]
        rec, base = spec[0], spec[1]
        buf = self.mem[rec]
        rows = [bytes(buf[base + k * stride: base + (k + 1) * stride]) for k in range(count)]
        shifted = [(asc, name) for asc, name in keys]

        def value(name, row):
            ks = self.items[name]
            off = ks[1] - base
            raw = row[off:off + ks[2]]
            if ks[3] == "num":
                return decode(self._cspec(ks), raw)
            return raw.translate(collating) if collating is not None else raw

        def cmp(a, b):
            for ascending, name in shifted:
                x, y = value(name, a), value(name, b)
                if x != y:
                    return (-1 if x < y else 1) * (1 if ascending else -1)
            return 0
        import sys

        if sys.platform == "win32":
            crt_qsort(rows, cmp)
        else:  # glibc's qsort is a merge sort for tables this size: stable
            rows.sort(key=cmp_to_key(cmp))
        buf[base:base + count * stride] = b"".join(rows)

    def release(self, record: str, src=None) -> None:
        f, record = self._file_of(record)
        if src is not None:
            self.move(src, record)
        f.released.append(bytes(self.mem[f.record][0:f.size]))

    def return_(self, sd: str, into=None) -> bool:
        f = self.files[sd]
        if not f.returning:
            return False
        rec = f.returning.pop(0)
        self.mem[f.record][0:f.size] = rec
        if into is not None:
            self.move(Ref(f.record), into)
        return True

    # ---------------------------------------------------------- intrinsic functions
    _fn_n = 0
    when_compiled = "2026103123595800+0000"  # the recorder compiles on the run's fixed clock

    def fn(self, name: str, *args, where: str = "") -> "Ref":
        """FUNCTION name(args): the result as a field of its own, named by a Ref, with the attributes libcob gives it
        (seance.intrinsics). where: LEADING or TRAILING for TRIM."""
        from . import intrinsics

        fargs = []
        for a in args:
            if isinstance(a, list):  # TABLE(ALL): every occurrence
                fargs += [self._fn_arg(x) for x in a]
            else:
                fargs.append(self._fn_arg(a))
        if where:
            fargs.append(where)
        rand = self.io.__dict__.setdefault("rand_state", [1])  # one C library generator per run
        env = intrinsics.Env(cmp=self._fn_cmp, current_date=self._current_date_text(), decimal_point="," if self.comma else ".", currency=self.currency,
                             rand_state=rand, when_compiled=self.when_compiled)
        return self._fn_store(intrinsics.call(name, fargs, env))

    def all_of(self, name: str, subs: list) -> list:
        """TABLE(ALL) in a function argument: a Ref for each occurrence, the ALL subscripts varying fastest last."""
        spec = self.items[self.resolve(name)]
        refs = [[]]
        for (count, _), s in zip(spec[10], subs):
            refs = [r + [k] for r in refs for k in (range(1, count + 1) if s is None else [int(s)])]
        return [Ref(self.resolve(name), tuple(r)) for r in refs]

    @staticmethod
    def _alpha_spec(size: int) -> list:
        return ["_LIT", 0, size, "alpha", "display", 0, 0, False, "none", "", [], [], False, False]

    @staticmethod
    def xdiv(a, b) -> Decimal:
        """cob_decimal_div for an expression inside a function argument."""
        from .intrinsics import Dec, div

        r = div(Dec.of(Decimal(a)), Dec.of(Decimal(b)))
        if r.nan:
            raise ZeroDivisionError("division by zero")
        return r.decimal()

    @staticmethod
    def xarg(value) -> Decimal:
        return Expr(value)

    def _fn_arg(self, x):
        from .intrinsics import Arg, from_float

        if isinstance(x, Expr):  # laid out as cob_alloc_field lays out a computed number: 4 or 8 byte binary, else DISPLAY
            from . import intrinsics

            d = intrinsics.Dec.of(Decimal(x)).trim()
            usage, size, digits, scale, signed = intrinsics.layout(d)
            spec = ["_EXPR", 0, size, "num", usage, digits, scale, signed, "trailing_over" if signed else "none", "", [], [], False, False]
            if usage == "display":
                body = str(abs(d.v) * 10 ** (scale - d.s)).rjust(size, "0")[-size:]
                data = (body[:-1] + NEG_DIGITS[int(body[-1])] if signed else body).encode(ENC)
            else:
                data = (d.v * 10 ** (scale - d.s)).to_bytes(size, "big", signed=signed)
            return Arg(True, d.decimal(), data, spec, x)
        if isinstance(x, Ref):
            rec, off, size, spec = self._addr(x)
            raw = bytes(self.mem[rec][off:off + size])
            if x.start is not None or spec[3] in ("alpha", "group", "edited"):
                return Arg(False, None, raw, spec if x.start is None else self._alpha_spec(size), x)
            val = decode(self._cspec(spec), raw)
            if spec[4] in ("float", "double"):
                val = from_float(val).decimal()
            return Arg(True, val, raw, spec, x)
        if isinstance(x, Figurative):
            raw = x.fill(1) if x.text else b""
            return Arg(False, None, raw, self._alpha_spec(len(raw)), x)
        if isinstance(x, (Decimal, int)):
            d = Decimal(x)
            sign, digits, exp = d.as_tuple()
            text = getattr(x, "text", None)
            scale = max(0, -exp)
            ndig = max(len(text.lstrip("+-").replace(".", "")) if text else len(digits) + max(exp, 0), scale, 1)
            signed = bool(sign)
            spec = ["_LIT", 0, ndig + (1 if signed else 0), "num", "display", ndig, scale, signed,
                    "leading_sep" if signed else "none", "", [], [], False, False]
            return Arg(True, d, encode(self._cspec(spec), d), spec, x)
        raw = str(x).encode(ENC, errors="replace") or b" "  # cobc reads an empty literal as one space
        return Arg(False, None, raw, self._alpha_spec(len(raw)), raw.decode(ENC))

    def _fn_cmp(self, a, b) -> int:
        """cob_cmp of two argument fields: numbers by value, anything else as text (collating sequence and all)."""
        if a.numeric and b.numeric:
            return (a.value > b.value) - (a.value < b.value)
        x, y = self._comparable(a.src, b.src)
        if self.collating is not None and not (isinstance(a.src, Ref) or isinstance(b.src, Ref)):
            # inside the function both are fields, so the program collating sequence applies even to two literals
            if self._coll_map is None:
                self._coll_map = {c: self.collating[c] for c in range(256)}
            x, y = x.translate(self._coll_map), y.translate(self._coll_map)
        return (x > y) - (x < y)

    def _fn_store(self, res) -> "Ref":
        from . import intrinsics

        Program._fn_n = (Program._fn_n + 1) % 64
        key = f"_FN{Program._fn_n}"
        if res.kind == "dec":
            d = intrinsics.Dec.of(res.dec).trim()
            usage, size, digits, scale, signed = intrinsics.layout(d)
            spec = [key, 0, size, "num", usage, digits, scale, signed, "trailing_over" if signed else "none", "", [], [], False,
                    False]
            if usage == "display":  # libcob's DISPLAY field: digits, the last one overpunched when negative
                body = str(abs(d.v) * 10 ** (scale - d.s)).rjust(size, "0")[-size:]
                if signed:
                    body = body[:-1] + NEG_DIGITS[int(body[-1])]
                data = body.encode(ENC)
            else:  # the binary holds the whole value, past its 9 or 20 digits (DISPLAY shows only those)
                data = (d.v * 10 ** (scale - d.s)).to_bytes(size, "big", signed=signed)
        elif res.kind in ("uint", "int"):
            signed = res.kind == "int" and res.n < 0
            spec = [key, 0, 4, "num", "binary", 9, 0, signed, "trailing_over" if signed else "none", "", [], [], False, False]
            data = res.n.to_bytes(4, "big", signed=signed)
        elif res.kind == "num":
            size = len(res.data)
            spec = [key, 0, size, "num", "display", size, 0, False, "none", "", [], [], False, False]
            data = res.data
        elif res.kind == "alpha":
            spec = self._alpha_spec(len(res.data))
            spec[0] = key
            data = res.data
        elif res.kind == "copy":
            src = res.arg
            spec = list(src.spec) if src.spec is not None else self._alpha_spec(src.size)
            spec[0], spec[1], spec[2], spec[10], spec[11] = key, 0, src.size, [], []
            data = res.data or src.data
            if res.value is not None:
                data = encode(self._cspec(spec), store_into(self._cspec(spec), res.value, move=True))
        elif res.kind == "double":
            spec = [key, 0, 8, "num", "double", 18, 6, True, "none", "", [], [], False, False]
            import struct

            data = struct.pack("<d", res.double)
        else:
            raise CobolError(f"intrinsic function result {res.kind}")
        self.items[key] = spec
        self.mem[key] = bytearray(data)
        return Ref(key)

    # ---------------------------------------------------------- CALL
    def link(self, programs: dict) -> None:
        """Make the called programs of this run reachable by CALL (name -> (Program, paragraphs, sections))."""
        self.registry = programs
        for sub, _, _ in programs.values():
            sub.registry = programs

    def call(self, name, args: list, on_exception: bool = False, returning=None) -> bool:
        """CALL name USING args. args: [("reference" | "content" | "value", operand)]. False when not found."""
        target = (name if isinstance(name, str) else self._text(name)).strip().upper()
        entry = getattr(self, "registry", {}).get(target)
        if entry is None and target == "CICSBRIDGE":
            views = []
            for _, arg in args:
                rec, off, size, _ = self._addr(arg)
                views.append(memoryview(self.mem[rec])[off:off + size])
            from . import cicsbridge

            if getattr(self.io, "cics", None) is None:
                import sqlite3

                conn = sqlite3.connect(":memory:", isolation_level=None)
                cicsbridge.seed(conn, self.io.inputs.get("CICSDB", b""))
                self.io.cics = cicsbridge.Bridge(conn)
            self.io.cics.call(*views[:8])
            return True
        if entry is None and target in ("SQLBRIDGE", "DSNTIAR"):
            views = []
            for _, arg in args:
                rec, off, size, _ = self._addr(arg)
                views.append(memoryview(self.mem[rec])[off:off + size])
            from . import sqlbridge

            if target == "DSNTIAR":
                sqlbridge.dsntiar(*views[:3])
            else:
                if getattr(self.io, "sql", None) is None:
                    self.io.sql = sqlbridge.Bridge(self.io.inputs.get("SQLDB"))
                self.io.sql.call(*views[:11])
            return True
        if entry is None:
            if on_exception:
                return False
            raise CobolError(f"CALL {target}: module '{target}' not found")
        sub, paras, secs = entry
        if not sub._active or sub.initial:
            sub.io = self.io
            sub.reset()
            sub._active = True
        sub.io = self.io
        shared = []
        for (mode, arg), lname in zip(args, sub.linkage):
            size = sub.records[lname]
            if mode == "reference" and isinstance(arg, (Ref, str)):
                rec, off, _, _ = self._addr(arg)
                buf = self.mem[rec]
                if len(buf) - off >= size:
                    sub.mem[lname] = memoryview(buf)[off:off + size]
                else:  # the linkage record is longer than what was passed: give it the rest, padded
                    sub.mem[lname] = memoryview(buf)[off:]
                    if len(sub.mem[lname]) < size:
                        passed = len(buf) - off
                        sub.mem[lname] = bytearray(bytes(buf[off:]).ljust(size, b"\x00"))
                        shared.append((buf, off, passed, lname))  # what the callee writes in the part that was passed goes back to the caller
            else:
                data = self._bytes(arg) if isinstance(arg, (Ref, str)) else self._text(arg).encode(ENC)
                sub.mem[lname] = bytearray(data[:size].ljust(size, b" "))
        if "RETURN-CODE" in sub.items:
            sub.move(self.n("RETURN-CODE") if "RETURN-CODE" in self.items else Decimal(0), "RETURN-CODE")
        try:
            sub._enter(paras, secs)
        finally:
            for buf, off, passed, lname in shared:
                buf[off:off + passed] = bytes(sub.mem[lname][:passed])
        rc = Decimal(0) if sub.initial or "RETURN-CODE" not in sub.items else sub.n("RETURN-CODE")
        if returning is not None:  # CALL ... RETURNING x: x gets the RETURN-CODE; the caller's own stays as it was (measured)
            self.move(rc, returning)
        elif "RETURN-CODE" in self.items:
            # an IS INITIAL program hands back RETURN-CODE 0 whatever it set (measured on GnuCOBOL 3.1.2)
            self.move(rc, "RETURN-CODE")
        return True

    def cancel(self, name) -> None:
        target = (name if isinstance(name, str) else self._text(name)).strip().upper()
        entry = getattr(self, "registry", {}).get(target)
        if entry:
            entry[0]._active = False

    def _enter(self, paras, secs) -> None:
        saved = (getattr(self, "_paras", None), getattr(self, "_index", None), getattr(self, "_sections", None))
        self._paras, self._index, self._sections = paras, {n: i for i, (n, _) in enumerate(paras)}, secs
        self._called = True
        try:
            self._execute(self._first_statement(), len(paras) - 1)
        except GoBack:
            pass
        finally:
            if saved[0] is not None:
                self._paras, self._index, self._sections = saved

    def exit_program(self) -> None:
        """EXIT PROGRAM: return to the caller; in the main program it does nothing."""
        if getattr(self, "_called", False):
            raise GoBack()

    @staticmethod
    def unsupported(where: str) -> None:
        raise NotImplementedError(f"Séance could not translate {where}. Write this part by hand.")

    # ---------------------------------------------------------- console
    def display(self, *parts, upon: str = "console", no_advancing: bool = False) -> None:
        text = "".join(self._display_part(p) for p in parts) + ("" if no_advancing else "\n")
        if upon == "syserr":
            self.io.stderr += text
        else:
            self.io.stdout += text

    def _display_part(self, p) -> str:
        if isinstance(p, Ref):
            rec, off, size, spec = self._addr(p)
            raw = bytes(self.mem[rec][off:off + size])
            if p.start is not None:
                return raw.decode(ENC)
            text = display_text(self._cspec(spec), raw)
            return text.replace(".", ",") if self.comma and spec[3] == "num" else text
        if isinstance(p, Figurative):
            return p.text[:1] if p.text else ""
        if isinstance(p, IdxValue):
            return f"{int(p):+010d}"
        if isinstance(p, Decimal):
            return _lit_text(p).replace(".", ",") if self.comma else _lit_text(p)
        return str(p)

    comma = False  # DECIMAL-POINT IS COMMA (set by the translated program)

    currency = "$"  # CURRENCY SIGN IS "W" (set by the translated program)

    def _shown(self, data: bytes) -> bytes:
        """An edited field as the program writes it: with DECIMAL-POINT IS COMMA the . and , trade places, and the
        program's own currency sign stands where the picture has $."""
        if self.comma:
            data = data.translate(bytes.maketrans(b".,", b",."))
        if self.currency != "$":
            data = data.replace(b"$", self.currency.encode("latin-1"))
        return data

    def _std(self, text: str) -> str:
        return text.translate(str.maketrans(".,", ",.")) if self.comma else text

    def accept(self, target, source: str = "console") -> None:
        if source == "console":
            text = self.io.stdin.pop(0) if self.io.stdin else None
            spec = self.items[target.name if isinstance(target, Ref) else self.resolve(target)]
            if text is None:
                self.move(SPACE if spec[3] != "num" else Decimal(0), target)
            elif spec[3] == "num":
                self.move(_alpha_to_number(text, lenient_sign=True), target)
            else:
                self.move(text, target)
            return
        now = self._now()
        clock = {"date": now.strftime("%y%m%d"), "date-yyyymmdd": now.strftime("%Y%m%d"), "day": now.strftime("%y%j"),
                 "day-yyyyddd": now.strftime("%Y%j"), "time": now.strftime("%H%M%S") + f"{now.microsecond // 10000:02d}",
                 "day-of-week": str(now.isoweekday())}[source]
        self.move(clock if self.kind(target) != "num" else Decimal(clock), target)

    def _now(self):
        """The time of the run: the checker pins it (io.clock, or COB_CURRENT_DATE as libcob reads it) so both sides see the same
        moment; a program run on its own sees the real time."""
        import datetime
        import os

        text = getattr(self.io, "clock", None) or os.environ.get("COB_CURRENT_DATE")
        if text:
            try:
                return datetime.datetime.strptime(text.strip(), "%Y/%m/%d %H:%M:%S.%f" if "." in text else "%Y/%m/%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.datetime.now()

    def _current_date_text(self) -> str:
        now = self._now()
        offset = "+0000" if getattr(self.io, "clock", None) else now.astimezone().strftime("%z") or "+0000"
        return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 10000:02d}" + offset

    # ---------------------------------------------------------- string verbs
    def string(self, parts: list, into, pointer=None) -> bool:
        """STRING: parts are (value, delimiter) with delimiter None for SIZE. Returns False on overflow."""
        rec, off, size, _ = self._addr(into)
        pos = int(self.n(pointer)) if pointer is not None else 1
        if pos < 1 or pos > size:
            return False
        ok = True
        for value, delim in parts:
            text = self._text(value)
            if delim is not None:
                d = self._text(delim)
                cut = text.find(d) if d else -1
                if cut >= 0:
                    text = text[:cut]
            for ch in text:
                if pos > size:
                    ok = False
                    break
                self.mem[rec][off + pos - 1] = ch.encode(ENC)[0]
                pos += 1
            if not ok:
                break
        if pointer is not None:
            self.move(Decimal(pos), pointer)
        return ok

    def unstring(self, src, delims: list, targets: list, pointer=None, tallying=None) -> bool:
        """UNSTRING: delims are (text, all); targets are (ref, delimiter_in, count_in)."""
        text = self._text(src)
        pos = 0
        if pointer is not None:
            start = int(self.n(pointer))
            if start < 1 or start > len(text):
                return False  # the pointer is outside the sending item: overflow, and nothing moves
            pos = start - 1
        filled = 0
        for ref, delim_in, count_in in targets:
            if pos >= len(text):
                break
            best = None
            for d, is_all in delims:
                d = self._text(d)
                k = text.find(d, pos)
                if k >= 0 and (best is None or k < best[0]):
                    best = (k, d, is_all)
            if not delims:  # no DELIMITED BY: each target takes as many characters as it holds
                size = self._addr(ref)[2]
                piece, used, pos_next = text[pos:pos + size], "", min(len(text), pos + size)
            elif best is None:
                piece, used, pos_next = text[pos:], "", len(text)
            else:
                k, d, is_all = best
                piece, used, pos_next = text[pos:k], d, k + len(d)
                if is_all:
                    while text.startswith(d, pos_next):
                        pos_next += len(d)
            self.move(piece, ref)
            if delim_in is not None:
                self.move(used, delim_in)
            if count_in is not None:
                self.move(Decimal(len(piece)), count_in)
            filled += 1
            pos = pos_next
        if pointer is not None:
            self.move(Decimal(pos + 1), pointer)
        if tallying is not None:
            self.move(self.n(tallying) + filled, tallying)
        return pos >= len(text)

    def text(self, x) -> str:
        """An operand as COBOL text: a number item gives its digits, a figurative its character."""
        return self._text(x)

    def _text(self, x) -> str:
        if isinstance(x, Ref):
            val = self.v(x)
            if not isinstance(val, Decimal):
                return val
            spec = self.items[x.name]
            if spec[4] == "display":  # a DISPLAY number used as text is its storage: sign character and all
                return self._bytes(x).decode(ENC)
            return _digits_text(val, spec)
        if isinstance(x, Figurative):
            return x.text[:1]
        if isinstance(x, Decimal):
            return _lit_text(x)
        return str(x)

    def _target_text(self, ref) -> str:
        """The characters INSPECT works on. A DISPLAY number is its storage, so a separate sign or an overpunched digit is part of it."""
        if isinstance(ref, Ref) and ref.start is None:
            rec, off, size, spec = self._addr(ref)
            if spec[3] == "num" and spec[4] == "display":
                return bytes(self.mem[rec][off:off + size]).decode(ENC)
        return self._text(ref)
    def _put_target(self, ref, text: str) -> None:
        if isinstance(ref, Ref) and ref.start is None:
            rec, off, size, spec = self._addr(ref)
            if spec[3] == "num" and spec[4] == "display":
                self.mem[rec][off:off + size] = text.encode(ENC)[:size].ljust(size, b"0")
                return
        self.move(text, ref)
    def _region(self, ref, before=None, after=None) -> tuple[int, int]:
        text = self._target_text(ref)
        lo, hi = 0, len(text)
        if after is not None:
            k = text.find(self._text(after))
            lo = hi if k < 0 else k + len(self._text(after))
        if before is not None:
            k = text.find(self._text(before), lo)
            hi = hi if k < 0 else k
        return lo, hi

    def inspect_run(self, ref, phrases: list) -> None:
        """INSPECT TALLYING / REPLACING as libcob does it: one pass, the phrases in order, and a character one phrase has taken is
        not taken by another. phrases: ("t", mode, counter, pattern, before, after) to count, ("r", mode, None-or-pattern, new, before, after)
        to replace; mode is characters, all, leading or first."""
        text = self._target_text(ref)
        marks: dict = {"t": [None] * len(text), "r": [None] * len(text)}  # counting and replacing keep separate marks (measured)
        counts: dict = {}
        for kind, mode, a, b, before, after in phrases:
            counter, pattern, new = (a, b, None) if kind == "t" else (None, a, b)
            lo, hi = self._region(ref, before, after)
            mk = marks[kind]
            if kind == "r":
                new = (self._text(new)[:1] * len(self._text(pattern))) if isinstance(new, Figurative) and pattern is not None else self._text(new)
            if mode == "characters":
                for i in range(lo, hi):
                    if mk[i] is None:
                        mk[i] = True if kind == "t" else (new[:1] or " ")
                        if kind == "t":
                            counts[repr(counter)] = counts.get(repr(counter), [counter, 0])
                            counts[repr(counter)][1] += 1
                continue
            p = self._text(pattern)
            n = len(p)
            if not n:
                continue
            i = lo
            while i <= hi - n:
                if text.startswith(p, i):
                    if all(mk[i + j] is None for j in range(n)):
                        for j in range(n):
                            mk[i + j] = True if kind == "t" else (new[j] if j < len(new) else " ")
                        if kind == "t":
                            counts[repr(counter)] = counts.get(repr(counter), [counter, 0])
                            counts[repr(counter)][1] += 1
                        i += n
                        if mode == "first":
                            break
                        continue
                elif mode == "leading":
                    break
                i += 1
        for counter, k in counts.values():
            self.move(self.n(counter) + k, counter)
        if any(isinstance(m, str) for m in marks["r"]):
            self._put_target(ref, "".join(m if isinstance(m, str) else c for m, c in zip(marks["r"], text)))

    def inspect_tally(self, ref, counter, mode: str, pattern=None, before=None, after=None) -> None:
        text = self._text(ref)
        lo, hi = self._region(ref, before, after)
        region = text[lo:hi]
        if mode == "characters":
            count = len(region)
        else:
            p = self._text(pattern)
            count, i = 0, 0
            while p and i <= len(region) - len(p):
                if region.startswith(p, i):
                    count += 1
                    i += len(p)
                elif mode == "leading":
                    break
                else:
                    i += 1
        self.move(self.n(counter) + count, counter)

    def inspect_replace(self, ref, mode: str, pattern, replacement, before=None, after=None) -> None:
        text = self._target_text(ref)
        lo, hi = self._region(ref, before, after)
        region = list(text[lo:hi])
        new = self._text(replacement)
        if mode == "characters":
            region = [new[:1] or " "] * len(region)
        else:
            p = self._text(pattern)
            i, s = 0, "".join(region)
            out = []
            replaced_first = False
            while i < len(s):
                if p and s.startswith(p, i) and not (mode == "first" and replaced_first):
                    out.append(new[: len(p)].ljust(len(p)))
                    i += len(p)
                    replaced_first = True
                    continue
                if mode == "leading" and p and not s.startswith(p, i):
                    out.append(s[i:])
                    break
                out.append(s[i])
                i += 1
            region = list("".join(out))
        self._put_target(ref, text[:lo] + "".join(region) + text[hi:])

    def inspect_convert(self, ref, src, dst, before=None, after=None) -> None:
        text = self._target_text(ref)
        lo, hi = self._region(ref, before, after)
        a, b = self._text(src), self._text(dst)
        if isinstance(dst, Figurative):
            b = b[:1] * len(a)  # TO ZEROES: every character converts to a zero
        table: dict = {}
        for i, ch in enumerate(a):
            table.setdefault(ch, b[i] if i < len(b) else ch)  # a character listed twice converts by its first place (libcob)
        self._put_target(ref, text[:lo] + "".join(table.get(c, c) for c in text[lo:hi]) + text[hi:])

    # ---------------------------------------------------------- program flow
    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.loop_limit:
            raise CobolError(f"the program ran more than {self.loop_limit} loop steps; a loop probably never ends")

    def loop(self):
        while True:
            self.tick()
            yield

    def run(self, io: IO, paragraphs: list, sections: dict) -> IO:
        """Run the whole program: start at the first paragraph and fall through, like COBOL."""
        self.io = io
        self.reset()
        for sub, _, _ in self.registry.values():
            sub._active = False
        self._paras = paragraphs
        self._index = {name: i for i, (name, _) in enumerate(paragraphs)}
        self._sections = sections
        try:
            self._execute(self._first_statement(), len(paragraphs) - 1)
        except StopRun:
            pass
        finally:
            if "SQLDB" in io.inputs or getattr(io, "sql", None) is not None:  # the database as it is at the end of the run
                from . import sqlbridge

                if getattr(io, "sql", None) is None:
                    io.sql = sqlbridge.Bridge(io.inputs.get("SQLDB"))
                io.outputs["SQLDB"] = io.sql.finish()
                io.sql = None
            for prog in [self] + [sub for sub, _, _ in self.registry.values()]:
                for f in prog.files.values():  # files left open are closed, as the runtime does at exit, even after an error
                    if f.mode and f.organization != "sort":
                        prog.close(f.name)
        rc = self.items.get("RETURN-CODE")
        io.return_code = int(self.n("RETURN-CODE")) if rc else 0
        return io

    def _first_statement(self) -> int:
        """Where a run begins: the first paragraph that is not part of the DECLARATIVES."""
        inside = set()
        for section, _ in self.declaratives:
            if section in self._sections:
                a, b = self._range(section)
                inside.update(range(a, b + 1))
        return next((i for i in range(len(self._paras)) if i not in inside), 0)

    def _range(self, name: str) -> tuple[int, int]:
        if name in self._sections:
            first, last = self._sections[name]
            return self._index[first], self._index[last]
        i = self._index[name]
        return i, i

    def perform(self, first: str, last: str | None = None) -> None:
        a, b = self._range(first)
        if last is not None:
            b = self._range(last)[1]
        self._execute(a, b)

    def _execute(self, a: int, b: int) -> None:
        """Run from paragraph a until control falls out of the end of paragraph b, however it got there: through the
        paragraphs in order or by GO TO, even when b comes before a. A range whose end is never reached runs on."""
        i = a
        escaped = False
        while i < len(self._paras):
            self.tick()
            nxt = self._paras[i][1]()
            if nxt is None:
                if i == b:
                    return
                i += 1
            elif nxt == "__exit_section__":
                sec = next((s for s, (f, l) in self._sections.items() if self._index[f] <= i <= self._index[l]), None)
                end = self._index[self._sections[sec][1]] if sec else i
                if end == b:
                    return
                i = end + 1
            else:
                i = self._range(nxt)[0]  # GO TO
                if not min(a, b) <= i <= max(a, b):
                    escaped = True
        if escaped:  # a GO TO left the range and the run reached the end of the program: the run ends, it does not return to the PERFORM
            raise GoBack()


# ------------------------------------------------------------------- helpers

_CUTOFF = 8


def _shortsort(a, lo, hi, cmp):
    while hi > lo:
        mx = lo
        for p in range(lo + 1, hi + 1):
            if cmp(a[p], a[mx]) > 0:
                mx = p
        a[mx], a[hi] = a[hi], a[mx]
        hi -= 1


def crt_qsort(a: list, cmp) -> None:
    """The C runtime's qsort, step for step (Microsoft CRT, which the Windows GnuCOBOL build uses for SORT of a
    table). It is not stable, so records with equal keys come out in this exact order; measured against GnuCOBOL."""
    n = len(a)
    if n < 2:
        return
    stack = []
    lo, hi = 0, n - 1
    while True:
        size = hi - lo + 1
        if size <= _CUTOFF:
            _shortsort(a, lo, hi, cmp)
        else:
            mid = lo + size // 2
            if cmp(a[lo], a[mid]) > 0:
                a[lo], a[mid] = a[mid], a[lo]
            if cmp(a[lo], a[hi]) > 0:
                a[lo], a[hi] = a[hi], a[lo]
            if cmp(a[mid], a[hi]) > 0:
                a[mid], a[hi] = a[hi], a[mid]
            loguy, higuy = lo, hi
            while True:
                if mid > loguy:
                    loguy += 1
                    while loguy < mid and cmp(a[loguy], a[mid]) <= 0:
                        loguy += 1
                if mid <= loguy:
                    loguy += 1
                    while loguy <= hi and cmp(a[loguy], a[mid]) <= 0:
                        loguy += 1
                higuy -= 1
                while higuy > mid and cmp(a[higuy], a[mid]) > 0:
                    higuy -= 1
                if higuy < loguy:
                    break
                a[loguy], a[higuy] = a[higuy], a[loguy]
                if mid == higuy:
                    mid = loguy
            higuy += 1
            if mid < higuy:
                higuy -= 1
                while higuy > mid and cmp(a[higuy], a[mid]) == 0:
                    higuy -= 1
            if mid >= higuy:
                higuy -= 1
                while higuy > lo and cmp(a[higuy], a[mid]) == 0:
                    higuy -= 1
            if higuy - lo >= hi - loguy:
                if lo < higuy:
                    stack.append((lo, higuy))
                if loguy < hi:
                    lo = loguy
                    continue
            else:
                if loguy < hi:
                    stack.append((loguy, hi))
                if lo < higuy:
                    hi = higuy
                    continue
        if not stack:
            return
        lo, hi = stack.pop()



class Lit(Decimal):
    """A numeric literal that keeps how it was written: 012345 compared with text is "012345", leading zero and all."""

    def __new__(cls, text: str):
        obj = super().__new__(cls, text)
        obj.text = text.lstrip("+")
        return obj


def _lit_text(d: Decimal) -> str:
    """A numeric literal as written: 12.50 stays 12.50, -3 stays -3, 007 stays 007."""
    return getattr(d, "text", None) or format(d, "f")


def _display_digits(spec, raw: bytes) -> str:
    """The digits of a USAGE DISPLAY number as stored, for a MOVE to text: a separate sign is dropped, an overpunched
    one is taken off its digit (one that is not a sign counts as 0), and P positions are zeros."""
    text = raw.decode(ENC)
    signed, sign, scale = spec[7], spec[8], spec[6]
    if signed:
        if sign == "leading_sep":
            text = text[1:]
        elif sign == "trailing_sep":
            text = text[:-1]
        elif text:
            k = 0 if sign == "leading_over" else len(text) - 1
            ch = text[k]
            ch = str(NEG_DIGITS.index(ch)) if ch in NEG_DIGITS else ch if ch.isdigit() else "0"
            text = text[:k] + ch + text[k + 1:]
    return text + "0" * -scale if scale < 0 else text


def _digits_text(value: Decimal, spec) -> str:
    """A numeric item moved to text: its digits (no sign, no point), zero-padded to the PIC's digits."""
    digits, scale = spec[5], spec[6]
    n = int((abs(value) * (Decimal(10) ** scale)).to_integral_value())
    if spec[4] == "index":
        return str(n)
    text = str(n).zfill(digits) if spec[4] == "native" else str(n % (10**digits)).zfill(digits)  # COMP-5 keeps what fits in its bytes
    return text + "0" * -scale if scale < 0 else text  # PIC 9(4)PP: the P positions are zeros in the text


def _alpha_to_number(text: str, lenient_sign: bool = False) -> Decimal:
    """Text moved into a number. GnuCOBOL reads the leading number in the text; ACCEPT reads a signed decimal."""
    s = text.strip()
    if lenient_sign:
        try:
            return Decimal(s) if s else Decimal(0)
        except InvalidOperation:
            pass
    # MOVE of text to a number, as libcob does it: blanks, then one optional sign, then digits with at most one decimal point.
    # Blanks and commas inside are skipped; any other character makes the whole value zero.
    negative = s[:1] == "-"
    if s[:1] in ("+", "-"):
        s = s[1:]
    whole, frac, seen_point = "", "", False
    for ch in s:
        if ch in "0123456789":
            if seen_point:
                frac += ch
            else:
                whole += ch
        elif ch == "." and not seen_point:
            seen_point = True
        elif ch.isspace() or ch == ",":
            continue
        else:
            return Decimal(0)
    value = Decimal((whole or "0") + "." + (frac or "0"))
    return value.copy_negate() if negative and value else value


# intrinsic functions -----------------------------------------------------------

class F:
    """FUNCTION name(args): the common intrinsic functions."""

    @staticmethod
    def UPPER_CASE(s):
        return str(s).upper()

    @staticmethod
    def LOWER_CASE(s):
        return str(s).lower()

    @staticmethod
    def REVERSE(s):
        return str(s)[::-1]

    @staticmethod
    def TRIM(s, where=None):
        s = str(s)
        return s.lstrip(" ") if where == "LEADING" else s.rstrip(" ") if where == "TRAILING" else s.strip(" ")

    @staticmethod
    def LENGTH(s):
        return Decimal(len(str(s)))

    @staticmethod
    def NUMVAL(s):
        t = str(s).strip().replace(" ", "")
        neg = t.endswith(("-", "CR", "DB")) or t.startswith("-")
        t = t.strip("+-").removesuffix("CR").removesuffix("DB")
        try:
            v = Decimal(t or "0")
        except InvalidOperation:
            v = Decimal(0)
        return -v if neg else v

    @staticmethod
    def NUMVAL_C(s, currency="$"):
        return F.NUMVAL(str(s).replace(currency, "").replace(",", ""))

    @staticmethod
    def INTEGER(x):
        return Decimal(x).to_integral_value(rounding="ROUND_FLOOR")

    @staticmethod
    def INTEGER_PART(x):
        return Decimal(x).to_integral_value(rounding="ROUND_DOWN")

    @staticmethod
    def MOD(a, b):
        a, b = Decimal(a), Decimal(b)
        return a - b * (a / b).to_integral_value(rounding="ROUND_FLOOR")

    @staticmethod
    def REM(a, b):
        a, b = Decimal(a), Decimal(b)
        return a - b * (a / b).to_integral_value(rounding="ROUND_DOWN")

    @staticmethod
    def ABS(x):
        return abs(Decimal(x))

    @staticmethod
    def MAX(*xs):
        return max(Decimal(x) for x in xs)

    @staticmethod
    def MIN(*xs):
        return min(Decimal(x) for x in xs)

    @staticmethod
    def SUM(*xs):
        return sum((Decimal(x) for x in xs), Decimal(0))

    @staticmethod
    def SQRT(x):
        return Decimal(x).sqrt()

    @staticmethod
    def CURRENT_DATE():
        return "2026103123595800+0000"

    @staticmethod
    def ORD(s):
        return Decimal(ord(str(s)[:1] or " ") + 1)

    @staticmethod
    def CHAR(n):
        return chr(int(n) - 1)


def run_cli(main, files, console: bool = True) -> int:
    """Run a translated program on real files, the way the batch job ran.

    Input files are read and output files written in the current folder, under the name the COBOL used
    (ASSIGN TO ACCTREC reads ./ACCTREC unless the environment variable DD_ACCTREC points elsewhere).
    Console input comes from stdin and DISPLAY goes to stdout.
    """
    import os
    import sys

    def path(assign: str) -> str:
        return os.environ.get(f"DD_{assign}") or os.environ.get(f"dd_{assign}") or os.environ.get(assign) or assign

    inputs = {}
    for name, assign, *_ in files:
        p = path(assign)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                inputs[assign] = fh.read()
    stdin = [] if (not console or sys.stdin is None or sys.stdin.isatty()) else sys.stdin.read().splitlines()
    io = main(IO(inputs, stdin))
    for assign, data in io.outputs.items():
        with open(path(assign), "wb") as fh:
            fh.write(data)
    sys.stdout.write(io.stdout)
    sys.stderr.write(io.stderr)
    return io.return_code
