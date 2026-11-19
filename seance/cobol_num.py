"""COBOL numeric semantics for DISPLAY fields, on top of decimal.Decimal.

COBOL stores a value into a PIC field by truncating extra decimals (or rounding
half away from zero when ROUNDED is given) and then dropping high-order digits
that do not fit (when ON SIZE ERROR is not specified).

Sign storage in DISPLAY fields (GnuCOBOL, ASCII):
  leading_sep / trailing_sep   a separate '+' or '-' character before / after the digits
  trailing_over / leading_over the sign is folded into the last / first digit: positive is the
                               plain digit, negative is 'p'..'y' for 0..9 (the COBOL default is trailing_over)
"""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, getcontext

# Wide enough that intermediate results behave like COBOL's arbitrary-precision
# intermediates for the program sizes we handle.
getcontext().prec = 60

NEG_DIGITS = "pqrstuvwxy"


def store(
    value: Decimal | int | str,
    digits: int,
    scale: int,
    signed: bool = True,
    rounded: bool = False,
    move: bool = False,
) -> Decimal:
    """Return `value` as it would be after being stored in PIC S9(digits-scale)V9(scale).

    Sign rules, checked against GnuCOBOL (tests/test_numbers_vs_cobol.py):
      * COMPUTE / ADD / ...  (move=False): a result that rounds or truncates to zero is +0.
      * MOVE                 (move=True):  a negative sender keeps its sign even when everything truncates away,
                                           so MOVE -0.001 TO PIC S9V99 stores a negative zero.
      * A negative value whose high-order digits overflow keeps its sign, so it can store a negative zero.
    A negative zero is returned as Decimal('-0.00'); test it with `.is_signed()`.
    """
    d = Decimal(value)
    quantum = Decimal(1).scaleb(-scale)
    mode = ROUND_HALF_UP if rounded else ROUND_DOWN
    q = d.quantize(quantum, rounding=mode)
    scaled = int(abs(q).scaleb(scale).to_integral_value()) % 10**digits  # scale < 0 for P scaling (PIC 99PPP)
    result = Decimal(scaled).scaleb(-scale)
    negative = signed and (q < 0 or (move and (d < 0 or (d.is_zero() and d.is_signed()))))
    return result.copy_negate() if negative else result  # copy_negate keeps -0; unary minus would drop it


def size_error(
    value: Decimal | int | str,
    digits: int,
    scale: int,
    signed: bool = True,
    rounded: bool = False,
) -> bool:
    """True when COBOL would raise ON SIZE ERROR storing `value` in this PIC.

    The check happens after rounding, so 99999.995 into PIC 9(5)V99 ROUNDED overflows.
    """
    d = Decimal(value)
    mode = ROUND_HALF_UP if rounded else ROUND_DOWN
    q = d.quantize(Decimal(1).scaleb(-scale), rounding=mode)
    # A negative value stored into an unsigned field is not a size error: COBOL stores its absolute value.
    return abs(q) >= Decimal(10) ** (digits - scale)


def _mode(signed: bool, sign: str | None) -> str:
    return sign if sign else ("leading_sep" if signed else "none")


def parse_numeric(text: str, digits: int, scale: int, signed: bool, sign: str | None = None) -> Decimal:
    """Parse a DISPLAY numeric field written with the given sign storage."""
    mode = _mode(signed, sign)
    negative = False
    body = text
    if mode == "leading_sep":
        if text[:1] not in "+-":
            raise ValueError(f"missing sign in {text!r}")
        negative, body = text[0] == "-", text[1:]
    elif mode == "trailing_sep":
        if text[-1:] not in "+-":
            raise ValueError(f"missing sign in {text!r}")
        negative, body = text[-1] == "-", text[:-1]
    elif mode in ("trailing_over", "leading_over"):
        i = len(text) - 1 if mode == "trailing_over" else 0
        ch = text[i]
        if ch in NEG_DIGITS:
            negative = True
            body = text[:i] + str(NEG_DIGITS.index(ch)) + text[i + 1:]
    if len(body) != digits or not body.isdigit():
        raise ValueError(f"bad numeric field {text!r}")
    value = Decimal(int(body)).scaleb(-scale)
    return value.copy_negate() if negative else value


def format_numeric(value: Decimal | int, digits: int, scale: int, signed: bool, sign: str | None = None) -> str:
    """Format as a COBOL DISPLAY field, truncating the way a MOVE does."""
    mode = _mode(signed, sign)
    stored = store(value, digits, scale, signed, move=True)  # the caller already applied COMPUTE rules via store(); keep its sign
    body = str(int(abs(stored).scaleb(scale))).zfill(digits)
    negative = signed and stored.is_signed()
    if mode == "none":
        return body
    if mode == "leading_sep":
        return ("-" if negative else "+") + body
    if mode == "trailing_sep":
        return body + ("-" if negative else "+")
    if negative:
        if mode == "trailing_over":
            return body[:-1] + NEG_DIGITS[int(body[-1])]
        return NEG_DIGITS[int(body[0])] + body[1:]
    return body


def format_alpha(value: str, width: int) -> str:
    return value[:width].ljust(width)


# ---------------------------------------------------------------- edited pictures
#
# Supported grammar (checked against GnuCOBOL output in tests/test_edited.py):
#   [floating or fixed $ + - ] [Z * 9 , B 0 /]* [. 9*] [+ - CR DB]
# Anything else is rejected when the copybook is read.

_SYMBOLS = "$+-"


def split_edited(pic: str) -> tuple[str, str, bool, str]:
    """-> (integer part, decimal part, has point, trailer). Trailer is '', '+', '-', 'CR' or 'DB'."""
    pic = pic.upper()
    trailer = ""
    for t in ("CR", "DB"):
        if pic.endswith(t):
            pic, trailer = pic[:-2], t
    int_pic, point, dec_pic = pic.partition(".")
    tail = dec_pic if point else int_pic
    if not trailer and len(tail) > 1 and tail[-1] in "+-" and tail[-2] not in "+-":
        trailer = tail[-1]
        if point:
            dec_pic = dec_pic[:-1]
        else:
            int_pic = int_pic[:-1]
    return int_pic, dec_pic, bool(point), trailer


def edited_supported(pic: str) -> bool:
    int_pic, dec_pic, point, trailer = split_edited(pic)
    if not re.fullmatch(r"([$+\-][$+\-,]*)?[ZB*9,0/]*", int_pic) or not re.fullmatch(r"[9]*", dec_pic):
        return False
    if len({c for c in int_pic if c in _SYMBOLS}) > 1 or (trailer in "+-" and trailer and int_pic[:1] in "+-" ):
        return False
    return any(c in "9Z*" or c in _SYMBOLS for c in int_pic + dec_pic)


def _run_length(int_pic: str) -> int:
    """How many $, + or - symbols start the picture (commas inside the run are insertions, not symbols)."""
    m = re.match(r"[$+\-][$+\-,]*", int_pic)
    return sum(1 for c in m.group() if c in _SYMBOLS) if m else 0


def edited_digits(pic: str) -> tuple[int, int]:
    """(integer digit positions, decimal digit positions). The first symbol of a floating run holds no digit."""
    int_pic, dec_pic, _, _ = split_edited(pic)
    run = _run_length(int_pic)
    ints = sum(1 for c in int_pic if c in "9Z*") + max(run - 1, 0)
    return ints, len(dec_pic)


def edited_has_sign(pic: str) -> bool:
    int_pic, _, _, trailer = split_edited(pic)
    return bool(trailer) or any(c in "+-" for c in int_pic)


def _symbol(c: str, negative: bool) -> str:
    if c == "$":
        return "$"
    if c == "+":
        return "-" if negative else "+"
    return "-" if negative else " "


def format_edited(value: Decimal | int | str, pic: str) -> str:
    """Apply a numeric-edited PICTURE to a value, the way GnuCOBOL does on a MOVE.

    Values that fit the picture match GnuCOBOL exactly (see tests). When a value is too big for the picture,
    GnuCOBOL's display of the leftover digits is inconsistent between picture shapes, so it is not emulated:
    Séance will report such a field as a difference instead of guessing.
    """
    int_pic, dec_pic, point, trailer = split_edited(pic)
    n_int, n_dec = edited_digits(pic)
    d = Decimal(value)
    quantum = Decimal(1).scaleb(-n_dec)
    full = int((abs(d).quantize(quantum, rounding=ROUND_DOWN) * 10**n_dec).to_integral_value())
    scaled = full % 10 ** (n_int + n_dec)
    digits = str(scaled).zfill(n_int + n_dec)
    int_digits, dec_digits = digits[:n_int], digits[n_int:]
    negative = d < 0 and scaled != 0
    fill = "*" if "*" in int_pic else " "

    run = _run_length(int_pic)
    floating = run > 1
    symbol = int_pic[0] if run else ""
    cells: list[str] = []
    suppressing = True
    placed = False
    di = 0
    seen_symbols = 0

    def end_suppression() -> None:
        """Called when the first digit is printed: the floating symbol goes in the cell just left of it."""
        nonlocal suppressing, placed
        if floating and not placed and cells:
            cells[-1] = _symbol(symbol, negative)
            placed = True
        suppressing = False

    for ch in int_pic:
        if ch in _SYMBOLS and ch == symbol and seen_symbols < run:
            seen_symbols += 1
            if not floating:
                cells.append(_symbol(ch, negative))
            elif seen_symbols == 1:
                cells.append(" ")  # holds the symbol only, never a digit
            else:
                digit = int_digits[di]; di += 1
                if suppressing and digit == "0":
                    cells.append(" ")
                else:
                    end_suppression(); cells.append(digit)
        elif ch in "Z*":
            digit = int_digits[di]; di += 1
            if suppressing and digit == "0":
                cells.append(fill)
            else:
                end_suppression(); cells.append(digit)
        elif ch == "9":
            digit = int_digits[di]; di += 1
            end_suppression(); cells.append(digit)
        elif ch == ",":
            cells.append(fill if suppressing else ",")
        elif ch == "B":
            cells.append(" ")
        else:
            cells.append(ch)  # '0' and '/' are inserted as written
    if floating and not placed:
        end_suppression()

    out = "".join(cells)
    if point:
        out += "." + dec_digits
    if trailer in ("+", "-"):
        out += _symbol(trailer, negative)
    elif trailer:
        out += trailer if negative else "  "
    return out


def deedit(text: str) -> Decimal:
    """Read a number back out of an edited field (drops currency, commas, blanks, and reads the sign)."""
    s = text.strip().upper()
    negative = s.endswith(("CR", "DB")) or "-" in s
    digits = re.sub(r"[^0-9.]", "", s)
    if not digits or digits == ".":
        return Decimal(0)
    value = Decimal(digits)
    return -value if negative and value != 0 else value

