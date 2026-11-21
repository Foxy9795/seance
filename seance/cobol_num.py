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
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal, getcontext

# ROUNDED MODE: ROUNDED alone is NEAREST-AWAY-FROM-ZERO; no ROUNDED truncates
ROUND_MODES = {
    "NEAREST-AWAY-FROM-ZERO": ROUND_HALF_UP, "AWAY-FROM-ZERO": ROUND_UP, "NEAREST-EVEN": ROUND_HALF_EVEN,
    "NEAREST-TOWARD-ZERO": ROUND_HALF_DOWN, "TOWARD-GREATER": ROUND_CEILING, "TOWARD-LESSER": ROUND_FLOOR, "TRUNCATION": ROUND_DOWN,
}


def rounding_of(rounded: bool | str):
    """The Decimal rounding mode for a ROUNDED flag: False, True, or the name given after ROUNDED MODE."""
    if isinstance(rounded, str):
        return ROUND_MODES[rounded]
    return ROUND_HALF_UP if rounded else ROUND_DOWN

# Wide enough that intermediate results behave like COBOL's arbitrary-precision
# intermediates for the program sizes we handle.
getcontext().prec = 60

NEG_DIGITS = "pqrstuvwxy"


def store(
    value: Decimal | int | str,
    digits: int,
    scale: int,
    signed: bool = True,
    rounded: bool | str = False,
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
    mode = rounding_of(rounded)
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
    mode = rounding_of(rounded)
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
# Edited pictures live in seance/editing.py, measured against GnuCOBOL by scripts/fuzz_editing.py. These names are
# kept for the code and the translated programs that use them.

def edited_supported(pic: str) -> bool:
    from .editing import numeric_edited_ok

    return numeric_edited_ok(pic)


def edited_digits(pic: str) -> tuple[int, int]:
    """(integer digits, decimal digits) the field can show: its capacity, for ON SIZE ERROR and arithmetic."""
    from .editing import capacity

    return capacity(pic)


def edited_has_sign(pic: str) -> bool:
    from .editing import parse_numeric

    return parse_numeric(pic).signed


def format_edited(value: Decimal | int | str, pic: str, currency: str = "$", blank_zero: bool = False) -> str:
    """Apply a numeric-edited PICTURE to a value, the way GnuCOBOL does on a MOVE."""
    from .editing import format_numeric

    return format_numeric(value, pic, currency, blank_zero)


def deedit(text: str) -> Decimal:
    """Read a number back out of an edited field (drops currency, commas, blanks, and reads the sign)."""
    s = text.strip().upper()
    negative = s.endswith(("CR", "DB")) or "-" in s
    digits = re.sub(r"[^0-9.]", "", s)
    if not digits or digits == ".":
        return Decimal(0)
    value = Decimal(digits)
    return -value if negative and value != 0 else value

