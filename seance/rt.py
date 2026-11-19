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
from .cobol_num import deedit, size_error

D = Decimal


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

    def write_records(self, name: str, rows: list[str], size: int) -> None:
        self.outputs[name] = "".join(r.ljust(size)[:size] for r in rows).encode(ENC)

    def print(self, *parts) -> None:
        self.stdout += "".join(str(p) for p in parts) + "\n"


# ------------------------------------------------------------------- the program

class Program:
    SPACE, ZERO, HIGH, LOW, QUOTE = SPACE, ZERO, HIGH, LOW, QUOTE
    LOOP_LIMIT = 2_000_000

    def __init__(self, items: dict, records: dict, values: list, conds: dict, files: list, indexes: list, aliases: dict | None = None,
                 linkage: list | None = None, initial: bool = False):
        # items: name -> [record, offset, size, kind, usage, digits, scale, signed, sign, pic, dims, children, justified, blank_zero]
        self.items = items
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
        if spec[3] in ("group", "alpha"):
            return encode(("alpha", "display", 0, 0, False, "none", "", size, spec[12], False), str(value) if not isinstance(value, Decimal) else str(value))
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
        return deedit(val) if val.strip() else Decimal(0)

    def idx_value(self, name: str) -> int:
        return self.idx[name]

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
            if src.start is not None or spec[3] in ("group", "alpha"):
                return "alpha", raw, None
            if spec[3] == "edited":
                return "edited", raw, None
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
                        text = _digits_text(value, sspec)
                    elif kind == "lit":
                        text = _lit_text(num).lstrip("+-")
                    else:
                        text = raw.decode(ENC)
                    data = encode(("alpha", "display", 0, 0, False, "none", "", size, spec[12], False), text)
                buf[off:off + size] = data
            elif tkind == "edited":
                if kind in ("num", "lit"):
                    value = num[0] if kind == "num" else num
                    buf[off:off + size] = encode(self._cspec(spec), value)
                elif kind == "fig":
                    buf[off:off + size] = encode(self._cspec(spec), Decimal(0)) if raw is ZERO else raw.fill(size)
                else:
                    buf[off:off + size] = raw[:size].ljust(size, b" ")
            else:  # numeric
                if kind == "num":
                    value = num[0]
                elif kind == "lit":
                    value = num
                elif kind == "fig":
                    value = Decimal(0)
                elif kind == "edited":
                    value = deedit(raw.decode(ENC))
                else:
                    value = _alpha_to_number(raw.decode(ENC))
                buf[off:off + size] = self._encode_value(spec, value)

    def initialize(self, *targets) -> None:
        for t in targets:
            ref = t if isinstance(t, Ref) else Ref(self.resolve(t))
            spec = self.items[ref.name]
            if spec[3] == "group":
                rec, base, size, _ = self._addr(ref)
                for leaf_name in self._leaves(ref.name):
                    lspec = self.items[leaf_name]
                    if leaf_name.startswith("FILLER#"):
                        continue
                    rel = lspec[1] - spec[1]
                    inner = [(c, s) for c, s in lspec[10][len(spec[10]):]]
                    offs = [base + rel]
                    for count, stride in inner:
                        offs = [o + k * stride for o in offs for k in range(count)]
                    for o in offs:
                        self.mem[rec][o:o + lspec[2]] = zero(self._cspec(lspec))
            else:
                rec, off, size, _ = self._addr(ref)
                self.mem[rec][off:off + size] = zero(self._cspec(spec))

    def _leaves(self, name: str) -> list[str]:
        out = []
        for c in self.items[name][11]:
            out += self._leaves(c) if self.items[c][3] == "group" else [c]
        return out

    # ---------------------------------------------------------- arithmetic
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
            if spec[3] == "num":
                digits = spec[5] if spec[4] not in ("native", "index") else 38
                over = size_error(value, digits, spec[6], spec[7], rounded)
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
                self.mem[rec][off:off + size] = encode(cs, store(value, ints + decs, decs, True, rounded))
            else:
                self.move(Decimal(int(value)), ref)
        return not error

    # ---------------------------------------------------------- conditions
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
            return Decimal(x), _lit_text(Decimal(x))
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
        return sa, sb

    def cond(self, name: str, *subs) -> bool:
        target, choices = self.conds[name]
        value = Ref(target, subs)
        for lo, hi in choices:
            if hi is None and self.cmp(value, "==", lo):
                return True
            if hi is not None and self.cmp(value, ">=", lo) and self.cmp(value, "<=", hi):
                return True
        return False

    def set_true(self, name: str, *subs) -> None:
        target, choices = self.conds[name]
        self.move(choices[0][0], Ref(target, subs))

    def is_numeric(self, ref) -> bool:
        val = self.v(ref)
        if isinstance(val, Decimal):
            raw = self._bytes(ref)
            spec = self.items[ref.name if isinstance(ref, Ref) else self.resolve(ref)]
            if spec[4] == "display":
                text = raw.decode(ENC)
                return all(c.isdigit() or c in "+-pqrstuvwxy" for c in text)
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
    def open(self, name: str, mode: str) -> None:
        f = self.files[name]
        if f.organization in ("indexed", "relative"):
            return self._k_open(f, mode)
        f.mode = mode
        f.last_pos = -1
        f.at_end = False
        if mode in ("input", "io"):
            if f.assign not in self.io.inputs:
                if f.extra.get("optional"):
                    f.data, f.pos = b"", 0
                    self._status(f, "05")
                    if mode == "io":
                        f.out = bytearray()
                    return
                self._status(f, "35")
                f.mode = None
                if not f.status:
                    raise CobolError(f"OPEN INPUT {name}: file {f.assign} does not exist")
                return
            f.data, f.pos = self.io.inputs[f.assign], 0
        if mode in ("output", "extend", "io"):
            f.out = bytearray(self.io.inputs.get(f.assign, b"")) if mode in ("extend", "io") else bytearray()
        self._status(f, "00")

    def close(self, name: str) -> None:
        f = self.files[name]
        if f.organization in ("indexed", "relative"):
            if f.mode in ("output", "extend", "io"):
                self.io.outputs[f.assign] = self._k_dump(f)
        elif f.mode in ("output", "extend", "io"):
            self.io.outputs[f.assign] = bytes(f.out)
        f.mode = None
        self._status(f, "00")

    def _status(self, f: FileState, code: str) -> None:
        if f.status:
            self.move(code, f.status)

    def read(self, name: str, into=None, key=None) -> bool:
        """READ: True when a record was read, False at end of file (or INVALID KEY for a keyed READ)."""
        f = self.files[name]
        if f.organization in ("indexed", "relative"):
            ok = self._k_read(f, key)
        else:
            ok = self._seq_read(f)
        if ok and into is not None:
            self.move(Ref(f.record), into)
        return ok

    def read_next(self, name: str, into=None) -> bool:
        f = self.files[name]
        ok = self._k_next(f) if f.organization in ("indexed", "relative") else self._seq_read(f)
        if ok and into is not None:
            self.move(Ref(f.record), into)
        return ok

    def _seq_read(self, f: FileState) -> bool:
        if f.mode not in ("input", "io"):
            self._status(f, "47")
            raise CobolError(f"READ {f.name}: the file is not open for input")
        buf = self.mem[f.record]
        if f.pos >= len(f.data):
            if f.at_end:  # reading again after the end was reported (measured: status 46, fatal without FILE STATUS)
                self._status(f, "46")
                if not f.status:
                    raise CobolError(f"READ after unsuccessful READ/START (status = 46) for file {f.name}")
                return False
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
            buf[0:f.size] = chunk[:f.size].ljust(f.size, b" ")
            self._status(f, "00")
        else:
            chunk = f.data[f.pos:f.pos + f.size]
            f.pos += f.size
            buf[0:len(chunk)] = chunk
            self._status(f, "00" if len(chunk) == f.size else "04")
        return True

    def _file_of(self, record: str) -> tuple[FileState, str]:
        key = self.resolve(record)
        buffer = self.items[key][0]
        f = next((x for x in self.files.values() if x.record == buffer), None)
        if f is None:
            raise CobolError(f"{record}: no file has this record")
        return f, key

    def write(self, record: str, src=None, advancing=None) -> bool:
        """WRITE. advancing: None, ("before" | "after", n) or ("before" | "after", "page"). False on INVALID KEY."""
        f, record = self._file_of(record)
        if src is not None:
            self.move(src, record)
        if f.organization in ("indexed", "relative"):
            return self._k_write(f, record)
        if f.mode not in ("output", "extend", "io"):
            self._status(f, "48")
            raise CobolError(f"WRITE {record}: the file is not open for output")
        size = self.items[record][2] if record in self.items else f.size
        data = bytes(self.mem[f.record][0:size])
        if f.organization == "line":
            data = data.rstrip(b" ")
        elif f.extra.get("variable"):
            data = len(data).to_bytes(2, "big") + b"\x00\x00" + data
        nl = b"\n"
        pre = post = b""
        if advancing:
            when, amount = advancing
            gap = b"\f" if amount == "page" else nl * int(amount)
            if when == "after":
                pre = gap
            else:
                post = gap
        elif f.organization == "line":
            post = nl
        f.out += pre + data + post
        self._status(f, "00")
        return True

    def rewrite(self, record: str, src=None) -> bool:
        f, record = self._file_of(record)
        if src is not None:
            self.move(src, record)
        if f.organization in ("indexed", "relative"):
            return self._k_rewrite(f, record)
        if f.mode != "io" or f.last_pos < 0:
            self._status(f, "43" if f.mode == "io" else "49")
            raise CobolError(f"REWRITE {record}: no record was read first, or the file is not open I-O")
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

    def delete(self, name: str) -> bool:
        f = self.files[name]
        if f.organization not in ("indexed", "relative"):
            raise CobolError(f"DELETE {name}: only indexed and relative files can delete records")
        return self._k_delete(f)

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
            if f.assign not in self.io.inputs:
                if f.extra.get("optional") or mode == "extend":
                    self._status(f, "05")
                    return
                f.mode = None
                self._status(f, "35")
                if not f.status:
                    raise CobolError(f"OPEN {mode.upper()} {f.name}: file {f.assign} does not exist")
                return
            data = self.io.inputs[f.assign]
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
            return b"".join(b"%09d" % slot + f.table[slot][1] for slot in sorted(f.table))
        return b"".join(f.table[k][1] for k in sorted(f.table))

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
        if f.organization == "relative" and f.extra.get("relkey"):
            self.move(Decimal(pk), f.extra["relkey"])
        f.last = self._pos_of(f, pk)

    def _k_next(self, f: FileState) -> bool:
        if f.mode not in ("input", "io"):
            self._status(f, "47")
            raise CobolError(f"READ {f.name}: the file is not open for input")
        import bisect

        order = self._positions(f)
        keys = [p for p, _ in order]
        if f.pending is not None:
            pos, inclusive = f.pending
            i = bisect.bisect_left(keys, pos) if inclusive else bisect.bisect_right(keys, pos)
            f.pending = None
        elif f.last is None:
            i = 0
        else:
            i = bisect.bisect_right(keys, f.last)
        if i >= len(order):
            self._status(f, "10")
            return False
        pk = order[i][1]
        self._deliver(f, pk)
        self._status(f, "00")  # GnuCOBOL (BDB) reports 00 even when more records share the alternate key (measured)
        return True

    def _k_read(self, f: FileState, key=None) -> bool:
        """A READ of a keyed file: by key when access is RANDOM, or DYNAMIC without NEXT."""
        if f.extra.get("access", "sequential") == "sequential":
            return self._k_next(f)
        if f.mode not in ("input", "io"):
            self._status(f, "47")
            raise CobolError(f"READ {f.name}: the file is not open for input")
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
        if f.mode not in ("output", "extend", "io"):
            self._status(f, "48")
            raise CobolError(f"WRITE {record}: the file is not open for output")
        rec = bytes(self.mem[f.record][0:f.size])
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
            self._status(f, "49")
            raise CobolError(f"REWRITE {record}: the file is not open I-O")
        rec = bytes(self.mem[f.record][0:f.size])
        pk = self._primary(f, rec)
        if f.extra.get("access", "sequential") == "sequential":
            if f.last is None or self._pos_of(f, pk) != f.last if pk in f.table else True:
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
            self._status(f, "49")
            raise CobolError(f"DELETE {f.name}: the file is not open I-O")
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

    def start(self, name: str, op: str = ">=", key=None) -> bool:
        """START: position the file so the next READ NEXT returns the first record whose key satisfies op."""
        f = self.files[name]
        if f.mode not in ("input", "io"):
            self._status(f, "47")
            raise CobolError(f"START {name}: the file is not open for input")
        if op == "first":
            f.keyref, f.cache, f.last, f.pending = f.extra.get("key"), None, None, None
            self._status(f, "00" if f.table else "23")
            return bool(f.table)
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
    def _sort_cmp(self, keys):
        def value(name, rec):
            spec = self.items[name]
            raw = rec[spec[1]:spec[1] + spec[2]]
            return decode(self._cspec(spec), raw) if spec[3] == "num" else raw

        def cmp(a, b):
            for ascending, name in keys:
                x, y = value(name, a), value(name, b)
                if x != y:
                    return (-1 if x < y else 1) * (1 if ascending else -1)
            return 0
        return cmp

    def sort(self, sd: str, keys: list, using=None, giving=None, input_proc=None, output_proc=None) -> None:
        """SORT or MERGE: keys is [(ascending, item)]. GnuCOBOL's sort is stable (measured)."""
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
        records = sorted(records, key=cmp_to_key(self._sort_cmp(keys)))
        if giving:
            for name in giving:
                gf = self.files[name]
                self.open(name, "output")
                for rec in records:
                    self.mem[gf.record][0:gf.size] = rec[:gf.size].ljust(gf.size, b" ")
                    self.write(gf.record)
                self.close(name)
        else:
            f.returning = list(records)
            self.perform(*output_proc)
        if "SORT-RETURN" in self.items:
            self.move(Decimal(0), "SORT-RETURN")

    def sort_table(self, table: str, keys: list) -> None:
        """SORT of an OCCURS table in storage: reorder its occurrences by the keys (stable)."""
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
            return decode(self._cspec(ks), raw) if ks[3] == "num" else raw

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
                        sub.mem[lname] = bytearray(bytes(buf[off:]).ljust(size, b"\x00"))
            else:
                data = self._bytes(arg) if isinstance(arg, (Ref, str)) else self._text(arg).encode(ENC)
                sub.mem[lname] = bytearray(data[:size].ljust(size, b" "))
        if "RETURN-CODE" in sub.items:
            sub.move(Decimal(0), "RETURN-CODE")
        sub._enter(paras, secs)
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
            self._execute(0, len(paras) - 1)
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
            return display_text(self._cspec(spec), raw)
        if isinstance(p, Figurative):
            return p.text[:1] if p.text else ""
        if isinstance(p, Decimal):
            return _lit_text(p)
        return str(p)

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
        clock = {"date": "261031", "date-yyyymmdd": "20261031", "day": "26304", "day-yyyyddd": "2026304",
                 "time": "23595800", "day-of-week": "6"}[source]
        self.move(clock if self.kind(target) != "num" else Decimal(clock), target)

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
        pos = int(self.n(pointer)) - 1 if pointer is not None else 0
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
            if best is None:
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
            return self.v(x) if not isinstance(self.v(x), Decimal) else _digits_text(self.v(x), self.items[x.name])
        if isinstance(x, Figurative):
            return x.text[:1]
        if isinstance(x, Decimal):
            return _lit_text(x)
        return str(x)

    def _region(self, ref, before=None, after=None) -> tuple[int, int]:
        text = self._text(ref)
        lo, hi = 0, len(text)
        if after is not None:
            k = text.find(self._text(after))
            lo = hi if k < 0 else k + len(self._text(after))
        if before is not None:
            k = text.find(self._text(before), lo)
            hi = hi if k < 0 else k
        return lo, hi

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
        text = self._text(ref)
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
        self.move(text[:lo] + "".join(region) + text[hi:], ref)

    def inspect_convert(self, ref, src, dst, before=None, after=None) -> None:
        text = self._text(ref)
        lo, hi = self._region(ref, before, after)
        a, b = self._text(src), self._text(dst)
        table = {ch: b[i] if i < len(b) else ch for i, ch in enumerate(a)}
        self.move(text[:lo] + "".join(table.get(c, c) for c in text[lo:hi]) + text[hi:], ref)

    # ---------------------------------------------------------- program flow
    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.LOOP_LIMIT:
            raise CobolError(f"the program ran more than {self.LOOP_LIMIT} loop steps; a loop probably never ends")

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
            self._execute(0, len(paragraphs) - 1)
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
        i = a
        while i <= b and i < len(self._paras):
            self.tick()
            nxt = self._paras[i][1]()
            if nxt is None:
                i += 1
            elif nxt == "__exit_section__":
                name = self._paras[i][0]
                sec = next((s for s, (f, l) in self._sections.items() if self._index[f] <= i <= self._index[l]), None)
                i = self._index[self._sections[sec][1]] + 1 if sec else i + 1
            else:
                i = self._range(nxt)[0]  # GO TO
                if i > b:  # a GO TO out of the performed range keeps running from there to the program's end
                    b = len(self._paras) - 1


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



def _lit_text(d: Decimal) -> str:
    """A numeric literal as written: 12.50 stays 12.50, -3 stays -3."""
    return format(d, "f")


def _digits_text(value: Decimal, spec) -> str:
    """A numeric item moved to text: its digits (no sign, no point), zero-padded to the PIC's digits."""
    digits, scale = spec[5], spec[6]
    n = int((abs(value) * (Decimal(10) ** scale)).to_integral_value())
    if spec[4] in ("native", "index"):
        return str(n)
    return str(n % (10**digits)).zfill(digits)


def _alpha_to_number(text: str, lenient_sign: bool = False) -> Decimal:
    """Text moved into a number. GnuCOBOL reads the leading number in the text; ACCEPT reads a signed decimal."""
    s = text.strip()
    if lenient_sign:
        try:
            return Decimal(s) if s else Decimal(0)
        except InvalidOperation:
            pass
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
        else:
            break
    return Decimal(digits) if digits else Decimal(0)


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


def run_cli(main, files) -> int:
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
    stdin = [] if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read().splitlines()
    io = main(IO(inputs, stdin))
    for assign, data in io.outputs.items():
        with open(path(assign), "wb") as fh:
            fh.write(data)
    sys.stdout.write(io.stdout)
    sys.stderr.write(io.stderr)
    return io.return_code
