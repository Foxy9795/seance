"""Edited pictures: what a MOVE writes into a numeric-edited or alphanumeric-edited field, and what it reads back.

Numeric-edited pictures may use digit positions (9, Z, *), simple insertion (B 0 / ,), the decimal point (. or V),
fixed and floating insertion (the currency sign, + and -), CR and DB, P scaling and BLANK WHEN ZERO. Alphanumeric-edited
pictures mix X, A and 9 with B, 0 and /.

Pictures here are in standard form: the decimal point is "." even under DECIMAL-POINT IS COMMA (the precompiler swaps
the two in the source, and the runtime swaps them back on display).

The rules are the standard's, adjusted where GnuCOBOL 3.1.2 does otherwise, because the compiled program is the judge:
a sign or currency symbol that comes before every 9, Z and * takes a digit of the value (a value one digit too big
for the picture therefore keeps its sign and ends zero suppression early), and its digit is never printed.
scripts/fuzz_editing.py measures this module against the compiler on thousands of random pictures and values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache

_REPEAT = re.compile(r"(.)\((\d+)\)")
_B = "\x01"  # a B insertion after suppression has ended: a space in the end, but not a blank a floating symbol may take


class EditError(ValueError):
    pass


def expand(pic: str) -> str:
    """X(3)B9(2) -> XXXB99, upper case."""
    return _REPEAT.sub(lambda m: m.group(1) * int(m.group(2)), pic.upper())


@dataclass(frozen=True)
class Cell:
    sym: str  # the picture symbol: 9 Z * + - B 0 / , . CR DB, or the currency sign
    role: str  # digit (9 Z *), lead (a sign or currency sign before every digit position), ins (B 0 / ,), point, trail, crdb
    takes: bool  # it takes a digit of the value
    dec: bool  # it is right of the decimal point


@dataclass(frozen=True)
class NumericEdited:
    pic: str
    cells: tuple[Cell, ...]
    currency: str
    size: int  # bytes in the field
    int_takes: int  # digits of the value taken left of the decimal point
    dec_takes: int  # and right of it
    p_left: int  # P symbols before every digit position: the digits start that many places right of the point
    p_right: int  # P symbols after them: the value is that many places bigger than its digits
    signed: bool
    v_after: int | None = None  # output characters before an assumed decimal point V

    @property
    def digits(self) -> int:
        """How many digits of the value the field can show (for ON SIZE ERROR and the capacity of the field)."""
        lead = sum(1 for c in self.cells if c.role == "lead" and not c.dec)
        return max(self.int_takes - (1 if lead else 0), 0) + self.dec_takes

    @property
    def scale(self) -> int:
        return self.dec_takes + self.p_left - self.p_right


def _symbols(pic: str) -> list[str]:
    out, i = [], 0
    while i < len(pic):
        if pic[i:i + 2] in ("CR", "DB"):
            out.append(pic[i:i + 2])
            i += 2
        else:
            out.append(pic[i])
            i += 1
    return out


@lru_cache(maxsize=4096)
def parse_numeric(pic: str, currency: str = "$") -> NumericEdited:
    p = expand(pic)
    cur = currency.upper()
    cells: list[Cell] = []
    point = seen_digit = False
    p_left = p_right = 0
    v_after = None
    for s in _symbols(p):
        if s == "V":
            if point:
                raise EditError(f"the picture {pic} has two decimal points")
            point = True
            v_after = sum(2 if c.role == "crdb" else 1 for c in cells)
        elif s == "P":
            if any(c.takes for c in cells):
                p_right += 1
            else:
                p_left += 1
        elif s in ("9", "Z", "*"):
            cells.append(Cell(s, "digit", True, point))
            seen_digit = True
        elif s in ("+", "-") or s == cur:
            if not seen_digit and s in ("+", "-") and any(c.role == "lead" and c.sym == cur for c in cells):
                # $$$$+: GnuCOBOL takes the sign as a digit position and moves the currency sign about
                raise EditError(f"the picture {pic} puts a sign right after the currency signs with no digit between; "
                                "GnuCOBOL edits it its own way, which Séance does not copy yet")
            cells.append(Cell(s, "trail", False, point) if seen_digit else Cell(s, "lead", True, point))
        elif s in ("B", "0", "/", ","):
            cells.append(Cell(s, "ins", False, point))
        elif s == ".":
            if point:
                raise EditError(f"the picture {pic} has two decimal points")
            cells.append(Cell(".", "point", False, False))
            point = True
        elif s in ("CR", "DB"):
            cells.append(Cell(s, "crdb", False, point))
        else:
            raise EditError(f"the picture {pic} has {s!r}, which a numeric-edited picture cannot use")
    if not any(c.takes for c in cells):
        raise EditError(f"the picture {pic} has no digit position")
    int_takes = sum(1 for c in cells if c.takes and not c.dec)
    dec_takes = sum(1 for c in cells if c.takes and c.dec)
    if p_left:  # PPP99 or VPP99: every digit position is below the decimal point
        int_takes, dec_takes = 0, int_takes + dec_takes
        cells = [Cell(c.sym, c.role, c.takes, True) if c.takes else c for c in cells]
    size = sum(2 if c.role == "crdb" else 1 for c in cells)
    signed = any(c.sym in ("+", "-", "CR", "DB") for c in cells)
    return NumericEdited(p, tuple(cells), cur, size, int_takes, dec_takes, p_left, p_right, signed, v_after)


def numeric_edited_ok(pic: str, currency: str = "$") -> bool:
    try:
        parse_numeric(pic, currency)
    except EditError:
        return False
    return True


def capacity(pic: str, currency: str = "$") -> tuple[int, int]:
    """(integer digits, decimal places) a numeric-edited field can show. Each kind of leading symbol (sign, currency)
    keeps one cell for itself, whose digit is never shown."""
    e = parse_numeric(pic, currency)
    kinds = {c.sym == e.currency for c in e.cells if c.role == "lead" and not c.dec}
    return max(e.int_takes - len(kinds), 0) + e.p_right, e.dec_takes + e.p_left


def _digits(value: Decimal, e: NumericEdited, extra: int = 0) -> str:
    """The digits of |value| the picture's digit positions take, high order first, truncated at both ends, then
    `extra` more digits below them (a trailing sign takes one)."""
    v = abs(value)
    if e.p_right:
        v = v.scaleb(-e.p_right)
    places = e.dec_takes + e.p_left + extra
    whole = int((v * (Decimal(10) ** places)).to_integral_value(rounding=ROUND_DOWN))
    n = e.int_takes + e.dec_takes + extra
    return str(whole % (10 ** n)).zfill(n) if n else ""


def format_numeric(value: Decimal | int | str, pic: str, currency: str = "$", blank_zero: bool = False) -> str:
    """What MOVE writes into a numeric-edited field.

    Measured rules (GnuCOBOL 3.1.2): every sign or currency symbol before the first 9, Z or * takes a digit. The first
    cell of the field never shows its digit, nor does a single (fixed) symbol; the cells of a floating string after the
    first show theirs once it is not zero. A floating symbol goes in the rightmost blank cell of its string, left of the
    first digit shown. A trailing + or - takes the next digit too, which only decides whether the value is zero.
    """
    e = parse_numeric(pic, currency)
    d = Decimal(value)
    trailing_signs = sum(1 for c in e.cells if c.role == "trail" and c.sym in ("+", "-"))
    digits = _digits(d, e, min(trailing_signs, 1))
    nonzero = any(x != "0" for x in digits)
    negative = d < 0 and nonzero
    cur = e.currency
    n_cur = sum(1 for c in e.cells if c.role == "lead" and c.sym == cur)
    n_sign = sum(1 for c in e.cells if c.role == "lead" and c.sym in ("+", "-"))
    out: list[str] = []
    pad = " "
    sig = False  # zero suppression has ended
    taken = 0
    sign_at = cur_at = first_float = trail_from = None
    sign_sym = ""
    cur_digit_zero = True
    point_at = e.v_after - 1 if e.v_after is not None else None
    later: list[tuple[int, str]] = []  # trailing signs, CR and DB: decided once the whole value is known
    for c in e.cells:
        x = "0"
        if c.takes:
            x = digits[taken]
            taken += 1
        if c.role == "digit":
            if c.sym == "9":
                out.append(x)
                sig = True
            else:
                pad = "*" if c.sym == "*" else " "
                if x != "0":
                    sig = True
                out.append(x if sig else pad)
        elif c.role == "lead":
            floating = (n_cur if c.sym == cur else n_sign) > 1
            mine = cur_at is None and c.sym == cur
            if c.sym == cur:
                if cur_at is None:
                    cur_at = len(out)
            elif sign_at is None:
                sign_at, sign_sym = len(out), c.sym
            if floating and first_float is None:
                first_float = len(out)
            if not out or not floating:
                out.append(pad)  # reserved for the symbol: its digit is never shown
            else:
                if x != "0":
                    sig = True
                out.append(x if sig else pad)
            if x != "0":
                sig = True
            if mine:
                cur_digit_zero = not sig  # every digit so far, its own included, was zero
        elif c.role == "ins":
            if c.sym in ("0", "/"):
                out.append(c.sym)
            elif c.sym == "B":
                out.append(_B if sig else pad)
            else:
                out.append("," if sig else pad)
        elif c.role == "point":
            out.append(".")
            point_at = len(out) - 1
        else:  # a trailing sign or currency sign, CR or DB
            if trail_from is None:
                trail_from = len(out)
            if c.sym == cur:
                out.append(cur)
            else:
                if c.role == "trail" and digits[-1:] not in ("", "0") and len(digits) > e.int_takes + e.dec_takes:
                    sig = True  # the digit a trailing sign takes ends zero suppression too
                later.append((len(out), c.sym))
                out.extend(" " * (2 if c.role == "crdb" else 1))
    for k, sym in later:
        if sym in ("CR", "DB"):
            out[k:k + 2] = list(sym) if negative else [" ", " "]
        else:
            out[k] = "-" if negative else ("+" if sym == "+" else " ")
    if not sig or (blank_zero and not nonzero):
        if pad == " " or blank_zero:
            return " " * len(out)
        return "".join("." if ch == "." else pad for ch in out)
    end = trail_from if trail_from is not None else len(out)
    if point_at is not None:  # a digit position right of the point that suppression blanked shows its zero
        for k in range(point_at + 1, end):
            if not out[k].isdigit() and out[k] not in (",", "+", "-", "/", _B):
                out[k] = "0"

    def float_spot() -> int | None:
        """The rightmost blank cell from the start of the floating string to the first digit shown."""
        if first_float is None:
            return None
        for k in range(end - 1, first_float - 1, -1):
            if out[k] == " ":
                return k
        return None

    sign_mark = "-" if negative else ("+" if sign_sym == "+" else " ")
    sign_then_cur = sign_at is not None and cur_at is not None and sign_at + 1 == cur_at
    cur_placed = False
    if cur_at is not None:
        if n_cur > 1:
            spot = float_spot()
            if spot is not None:
                out[spot] = cur
                cur_placed = True
        elif not sign_then_cur or cur_digit_zero:
            out[cur_at] = cur
            cur_placed = True
        else:
            out[cur_at] = "\x00"  # GnuCOBOL leaves a NUL in a currency cell the value ran into
    if sign_at is not None:
        if n_sign > 1:
            spot = float_spot()
            if spot is not None:
                out[spot] = sign_mark
        elif sign_then_cur and (cur_placed or n_cur == 1):
            out[sign_at] = sign_sym  # a sign written just before the currency sign stands as written
        else:
            out[sign_at] = sign_mark
    return "".join(" " if ch == _B else ch for ch in out)


def deedit_numeric(text: str, pic: str, currency: str = "$") -> Decimal:
    """What MOVE reads from a numeric-edited field into a number (measured on GnuCOBOL 3.1.2): every digit in the
    field, inserted zeros included; the decimal point where the field has one (or where V falls); a minus sign or CR
    anywhere makes it negative. DB does not."""
    e = parse_numeric(pic, currency)
    roles: list[str] = []  # the role of the picture cell behind each character of the field
    for c in e.cells:
        roles.extend([c.role] * (2 if c.role == "crdb" else 1))
    digits: list[str] = []
    scale = 0
    after = False
    neg = False
    for k, ch in enumerate(text):
        if e.v_after is not None and k == e.v_after:
            after = True
        if ch.isdigit():
            digits.append(ch)
            # right of an assumed point V, a digit in a floating sign or currency position is not a decimal place
            scale += after and (e.v_after is None or k >= len(roles) or roles[k] != "lead")
        elif ch == ".":
            after = True
        elif ch == "-" or (ch == "C" and text[k + 1:k + 2] == "R"):
            neg = True
    has_digit_cells = any(c.role == "digit" for c in e.cells)
    # P on the right scales the value up, except that GnuCOBOL 3.1.2 scales it down when the picture has no 9, Z or *
    places = scale + e.p_left + (e.p_right if not has_digit_cells else -e.p_right)
    value = Decimal(int("".join(digits) or "0")).scaleb(-places)
    return -value if neg and value else value


# ---------------------------------------------------------------- alphanumeric edited

def alpha_edited_ok(pic: str) -> bool:
    p = expand(pic)
    return bool(re.fullmatch(r"[XA9B0/]+", p)) and bool(re.search(r"[XA]", p)) and bool(re.search(r"[B0/]", p))


def format_alpha(text: str, pic: str) -> str:
    """What MOVE writes into an alphanumeric-edited field: the characters fill X, A and 9 from the left, B is a space,
    0 and / stand as written, and missing characters are spaces."""
    p = expand(pic)
    out, k = [], 0
    for c in p:
        if c in "XA9":
            out.append(text[k] if k < len(text) else " ")
            k += 1
        elif c == "B":
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)
