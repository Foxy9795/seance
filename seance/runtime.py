"""Runtime for translated COBOL: data items with COBOL storage rules, conditions, and record I/O.

Drafts written by seance.translate call into this module, so the generated Python stays short:
one line per COBOL statement, each tagged with the COBOL line it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .cobol_num import edited_digits, edited_has_sign, format_numeric, parse_numeric, size_error, store

D = Decimal


class Figurative:
    def __init__(self, name: str, char: str):
        self.name, self.char = name, char

    def __repr__(self) -> str:
        return f"S.{self.name}"


SPACE = Figurative("SPACE", " ")
ZERO = Figurative("ZERO", "0")
HIGH = Figurative("HIGH", "\xff")
LOW = Figurative("LOW", "\x00")
QUOTE = Figurative("QUOTE", '"')


@dataclass
class Item:
    kind: str  # num, alpha, edited, group
    digits: int = 0
    scale: int = 0
    signed: bool = False
    width: int = 0
    pic: str = ""
    initial: object = None
    children: list[str] = field(default_factory=list)


class Store:
    SPACE, ZERO, HIGH, LOW, QUOTE = SPACE, ZERO, HIGH, LOW, QUOTE

    def __init__(self, items: dict[str, tuple], conds: dict[str, tuple[str, list]] | None = None):
        self.items = {name: Item(*spec) for name, spec in items.items()}
        self.conds = conds or {}
        self.values: dict[str, object] = {}
        self.written: list[dict[str, object]] = []
        self.started = False
        self.reset()

    # ------------------------------------------------------------ state
    def reset(self) -> None:
        self.values = {}
        for name, it in self.items.items():
            if it.kind == "group":
                continue
            self.values[name] = self._coerce(it.initial if it.initial is not None else (ZERO if it.kind in ("num", "edited") else SPACE), it)
        self.written = []

    def __getitem__(self, name: str):
        it = self.items[name]
        if it.kind == "group":
            return self.group_text(name)
        return self.values[name]

    def n(self, name: str) -> Decimal:
        """Numeric value of a data item (alphanumeric digits are read as a number)."""
        v = self[name]
        if isinstance(v, Decimal):
            return v
        s = str(v).strip()
        try:
            return Decimal(s) if s else Decimal(0)
        except InvalidOperation:
            return Decimal(0)

    def group_text(self, name: str) -> str:
        out = []
        for child in self.items[name].children:
            it = self.items[child]
            if it.kind == "group":
                out.append(self.group_text(child))
            elif it.kind == "alpha":
                out.append(str(self.values[child]).ljust(it.width)[: it.width])
            elif it.kind == "num":
                out.append(format_numeric(self.values[child], it.digits, it.scale, it.signed, "trailing_over" if it.signed else "none"))
            else:
                from .cobol_num import format_edited

                out.append(format_edited(self.values[child], it.pic).ljust(it.width)[: it.width])
        return "".join(out)

    # ------------------------------------------------------------ storing
    def _coerce(self, value, it: Item):
        if it.kind == "alpha":
            if isinstance(value, Figurative):
                return value.char * it.width
            if isinstance(value, Decimal):
                text = str(abs(value)).replace(".", "")
                return text.ljust(it.width)[: it.width]
            return str(value).ljust(it.width)[: it.width]
        if isinstance(value, Figurative):
            value = Decimal(0)
        if isinstance(value, str):
            try:
                value = Decimal(value.strip() or "0")
            except InvalidOperation:
                value = Decimal(0)
        if it.kind == "edited":
            return Decimal(value)
        return store(Decimal(value), it.digits, it.scale, it.signed, move=True)

    def move(self, value, *targets: str) -> None:
        for t in targets:
            it = self.items[t]
            if it.kind == "group":
                self._move_group(value, t)
            else:
                self.values[t] = self._coerce(value, it)

    def _move_group(self, value, name: str) -> None:
        """A group move is a character move into the group's storage, then each field is read back."""
        it = self.items[name]
        text = value.char * 10_000 if isinstance(value, Figurative) else str(value)
        pos = 0
        for child in self._leaves(name):
            c = self.items[child]
            width = c.width
            piece = text[pos : pos + width].ljust(width)
            pos += width
            if isinstance(value, Figurative) and c.kind != "alpha":
                self.values[child] = self._coerce(value, c)
            elif c.kind == "alpha":
                self.values[child] = piece
            elif c.kind == "num":
                try:
                    self.values[child] = parse_numeric(piece, c.digits, c.scale, c.signed, "trailing_over" if c.signed else "none")
                except ValueError:
                    self.values[child] = Decimal(0)
            else:
                self.values[child] = Decimal(0)

    def _leaves(self, name: str) -> list[str]:
        out = []
        for child in self.items[name].children:
            out += self._leaves(child) if self.items[child].kind == "group" else [child]
        return out

    def compute(self, specs: list[tuple], guarded: bool = False) -> bool:
        """Evaluate every target first, then store, like COBOL. Returns False on a size error.

        specs: (target, callable producing the value, rounded).
        With ON SIZE ERROR (guarded=True), targets that overflow or divide by zero are left unchanged.
        Without it, overflowing values lose their high-order digits; a division by zero leaves the target unchanged.
        """
        error = False
        results = []
        for name, fn, rounded in specs:
            try:
                value = Decimal(fn())
            except (ArithmeticError, InvalidOperation, ZeroDivisionError):
                error = True
                results.append((name, None, rounded, True))
                continue
            it = self.items[name]
            digits, scale, signed = self._numeric_shape(it)
            over = size_error(value, digits, scale, signed, rounded)
            error = error or over
            results.append((name, value, rounded, over))
        for name, value, rounded, over in results:
            if value is None or (over and guarded):
                continue
            it = self.items[name]
            if it.kind == "edited":
                digits, scale, _ = self._numeric_shape(it)
                self.values[name] = store(value, digits, scale, True, rounded)
            elif it.kind == "alpha":
                self.values[name] = self._coerce(store(value, 18, 0, False, rounded), it)
            else:
                self.values[name] = store(value, it.digits, it.scale, it.signed, rounded)
        return not error

    def _numeric_shape(self, it: Item) -> tuple[int, int, bool]:
        if it.kind == "edited":
            ints, decs = edited_digits(it.pic)
            return ints + decs, decs, edited_has_sign(it.pic)
        if it.kind == "alpha":
            return it.width, 0, False
        return it.digits, it.scale, it.signed

    def initialize(self, *names: str) -> None:
        for name in names:
            it = self.items[name]
            if it.kind == "group":
                self.initialize(*it.children)
            else:
                self.values[name] = self._coerce(SPACE if it.kind == "alpha" else ZERO, it)

    # ------------------------------------------------------------ conditions
    def cmp(self, a, op: str, b) -> bool:
        a, b = self._comparable(a, b)
        return {"==": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]

    def _comparable(self, a, b):
        def num(x):
            if isinstance(x, Decimal):
                return x
            if isinstance(x, Figurative):
                return Decimal(0) if x is ZERO else None
            try:
                return Decimal(str(x).strip())
            except InvalidOperation:
                return None

        if isinstance(a, Decimal) or isinstance(b, Decimal):
            na, nb = num(a), num(b)
            if na is not None and nb is not None:
                return na, nb
        sa = a.char * 1 if isinstance(a, Figurative) else (str(abs(a)).replace(".", "") if isinstance(a, Decimal) else str(a))
        sb = b.char * 1 if isinstance(b, Figurative) else (str(abs(b)).replace(".", "") if isinstance(b, Decimal) else str(b))
        width = max(len(sa), len(sb), 1)
        if isinstance(a, Figurative):
            sa = a.char * width
        if isinstance(b, Figurative):
            sb = b.char * width
        return sa.ljust(width), sb.ljust(width)

    def cond(self, name: str) -> bool:
        var, choices = self.conds[name]
        value = self[var]
        for lo, hi in choices:
            if hi is None and self.cmp(value, "==", lo):
                return True
            if hi is not None and self.cmp(value, ">=", lo) and self.cmp(value, "<=", hi):
                return True
        return False

    def set_true(self, name: str) -> None:
        var, choices = self.conds[name]
        self.move(choices[0][0], var)

    def is_numeric(self, name: str) -> bool:
        v = self[name]
        return isinstance(v, Decimal) or str(v).isdigit()

    # ------------------------------------------------------------ records
    def load(self, rec, mapping: list[tuple[str, str]]) -> None:
        for py, cobol in mapping:
            it = self.items.get(cobol)
            value = getattr(rec, py)
            self.values[cobol] = self._coerce(value, it) if it and it.kind == "alpha" else value

    def write(self, record: str) -> None:
        self.written.append({name: self.values[name] for name in self._leaves(record)})

    def output(self, cls, mapping: list[tuple[str, str]]):
        if len(self.written) != 1:
            raise ValueError(f"the translated code wrote {len(self.written)} records for one input record")
        snap = self.written[0]
        kwargs = {}
        for py, cobol in mapping:
            v = snap.get(cobol, Decimal(0))
            kwargs[py] = v.rstrip() if isinstance(v, str) else v
        return cls(**kwargs)

    @staticmethod
    def loop(limit: int = 1_000_000):
        """Iterations for a translated PERFORM loop, with a guard so a wrong condition cannot hang a check."""
        for i in range(limit):
            yield i
        raise RuntimeError(f"a loop ran {limit} times; the UNTIL condition is probably never true")

    @staticmethod
    def unsupported(where: str) -> None:
        raise NotImplementedError(f"Séance could not translate {where}. Write this part by hand.")
