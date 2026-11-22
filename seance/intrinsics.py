"""COBOL intrinsic functions as GnuCOBOL 3.1.2 computes them: a port of libcob/intrinsic.c and of the decimal
arithmetic in libcob/numeric.c.

A function takes argument fields and gives a result field with the attributes libcob gives it, so that DISPLAY,
MOVE, comparisons and arithmetic on FUNCTION X(...) see what the compiled program sees:

- a computed number is a 4-byte binary of 9 digits when it fits in 32 bits with fewer than 10 decimals, an 8-byte
  binary of 20 digits when it fits in 64 bits with fewer than 19, otherwise a DISPLAY number as long as its digits;
  trailing decimal zeros go first (cob_alloc_field);
- counts and positions (ORD, LENGTH, INTEGER-OF-DATE, TEST-NUMVAL ...) are 4-byte binaries of 9 digits;
- MAX, MIN, ABS, MEAN of one argument, MEDIAN of an odd count and the case functions give a copy of an argument
  field, attributes and all;
- SQRT, EXP, LOG, LOG10, the trigonometric functions, PI, E and fractional powers keep 96 significant digits,
  rounded half up, as libcob keeps its GMP floats (the work is done here with 200 digits);
- a division keeps 38 decimal places more than the dividend had and truncates (cob_decimal_div);
- RANDOM is rand() / RAND_MAX as a double: on Windows the Microsoft C library's generator (seed 1 until a seed is
  given) with RAND_MAX 32767.
A function given an argument it cannot take returns 0, as libcob does after setting EC-ARGUMENT-FUNCTION.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

MAX_DIGITS = 38  # COB_MAX_DIGITS
FLOAT_DIGITS = 96  # the significant digits libcob keeps of a GMP float (mpf_get_str with 96 digits)
WORK = 200  # digits the floating functions are worked out to here
RAND_MAX = 32767


class Dec:
    """cob_decimal: an integer and a scale (the value is v / 10**s). nan marks a division by zero."""

    __slots__ = ("v", "s", "nan")

    def __init__(self, v: int = 0, s: int = 0, nan: bool = False):
        self.v, self.s, self.nan = v, s, nan

    @classmethod
    def of(cls, x) -> "Dec":
        if isinstance(x, Dec):
            return Dec(x.v, x.s, x.nan)
        x = Decimal(x)
        sign, digits, exp = x.as_tuple()
        v = int("".join(map(str, digits)) or "0")
        return cls(-v if sign else v, -exp)

    def decimal(self) -> Decimal:
        return Decimal(f"{self.v}E{-self.s}")  # exact, whatever the context precision

    def shift(self, n: int) -> None:
        if n > 0:
            self.v *= 10 ** n
        elif n < 0:
            self.v = _tdiv(self.v, 10 ** -n)
        self.s += n

    def trim(self) -> "Dec":
        if self.v == 0:
            self.s = 0
            return self
        while self.s > 0 and self.v % 10 == 0:
            self.v = _tdiv(self.v, 10)
            self.s -= 1
        return self


def _tdiv(a: int, b: int) -> int:
    """C integer division: truncates toward zero (mpz_tdiv_q)."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _align(a: Dec, b: Dec) -> None:
    if a.s < b.s:
        a.shift(b.s - a.s)
    elif a.s > b.s:
        b.shift(a.s - b.s)


def add(a: Dec, b: Dec) -> Dec:
    if a.nan or b.nan:
        return Dec(nan=True)
    a, b = Dec.of(a), Dec.of(b)
    _align(a, b)
    return Dec(a.v + b.v, a.s)


def sub(a: Dec, b: Dec) -> Dec:
    if a.nan or b.nan:
        return Dec(nan=True)
    a, b = Dec.of(a), Dec.of(b)
    _align(a, b)
    return Dec(a.v - b.v, a.s)


def mul(a: Dec, b: Dec) -> Dec:
    if a.nan or b.nan:
        return Dec(nan=True)
    return Dec(a.v * b.v, a.s + b.s)


def div(a: Dec, b: Dec) -> Dec:
    """cob_decimal_div: 38 decimal places more than the dividend, truncated."""
    if a.nan or b.nan or b.v == 0:
        return Dec(nan=True)
    if a.v == 0:
        return Dec(0, 0)
    d = Dec(a.v, a.s - b.s)
    d.shift(MAX_DIGITS + (-d.s if d.s < 0 else 0))
    d.v = _tdiv(d.v, b.v)
    return d


def cmp(a: Dec, b: Dec) -> int:
    a, b = Dec.of(a), Dec.of(b)
    _align(a, b)
    return (a.v > b.v) - (a.v < b.v)


# ---------------------------------------------------------------- GMP floats, worked out with decimal

def from_float(x: Decimal) -> Dec:
    """cob_decimal_set_mpf: 96 significant digits, rounded half up on the next digit."""
    if x == 0:
        return Dec(0, 0)
    with localcontext(Context(prec=WORK + 20)):
        q = Decimal(1).scaleb(x.adjusted() - (FLOAT_DIGITS - 1))
        return Dec.of(x.quantize(q, rounding=ROUND_HALF_UP))


def _ctx_unused():
    return localcontext(Context(prec=WORK))


_PI: Decimal | None = None


def pi() -> Decimal:
    """pi to WORK digits (Machin's formula)."""
    global _PI
    if _PI is None:
        with localcontext(Context(prec=WORK + 10)):
            def arctan_inv(n: int) -> Decimal:
                x = Decimal(1) / n
                x2 = x * x
                term, total, k = x, x, 1
                while True:
                    term *= -x2
                    k += 2
                    nxt = total + term / k
                    if nxt == total:
                        return total
                    total = nxt
            _PI = +(4 * (4 * arctan_inv(5) - arctan_inv(239)))
    return _PI


def _sin(x: Decimal) -> Decimal:
    with localcontext(Context(prec=WORK + 10)):
        p2 = pi() * 2
        x = x - p2 * (x / p2).to_integral_value(rounding="ROUND_FLOOR")
        term, total, k = x, x, 1
        while True:
            term *= -x * x / ((k + 1) * (k + 2))
            k += 2
            nxt = total + term
            if nxt == total:
                return +total
            total = nxt


def _cos(x: Decimal) -> Decimal:
    with localcontext(Context(prec=WORK + 10)):
        return _sin(pi() / 2 - x)  # as libcob: sin(pi/2 - x)


def _atan(x: Decimal) -> Decimal:
    with localcontext(Context(prec=WORK + 10)):
        if x == 0:
            return Decimal(0)
        neg = x < 0
        x = abs(x)
        halvings = 0
        while x > Decimal("0.1"):  # atan(x) = 2 atan(x / (1 + sqrt(1 + x*x)))
            x = x / (1 + (1 + x * x).sqrt())
            halvings += 1
        term, total, k, x2 = x, x, 1, x * x
        while True:
            term *= -x2
            k += 2
            nxt = total + term / k
            if nxt == total:
                break
            total = nxt
        total = total * (2 ** halvings)
        return -total if neg else total


def _float_fn(name: str, x: Decimal) -> Decimal:
    with localcontext(Context(prec=WORK + 10)):
        if name == "EXP":
            return x.exp()
        if name == "LOG":
            return x.ln()
        if name == "LOG10":
            return x.ln() / Decimal(10).ln()  # libcob divides two logarithms
        if name == "SIN":
            return _sin(x)
        if name == "COS":
            return _cos(x)
        if name == "TAN":
            return _sin(x) / _cos(x)
        if name == "ATAN":
            return _atan(x)
        if name == "ASIN":
            if abs(x) == 1:
                return pi() / 2 * (1 if x > 0 else -1)
            return 2 * _atan(x / (1 + (1 - x * x).sqrt()))
        if name == "ACOS":
            if x == 0:
                return pi() / 2
            if x == 1:
                return Decimal(0)
            if x == -1:
                return pi()
            return 2 * _atan((1 - x * x).sqrt() / (1 + x))
        if name == "SQRT":
            return x.sqrt()
    raise KeyError(name)


def power(a: Dec, b: Dec) -> Dec:
    """cob_decimal_pow."""
    if a.nan or b.nan:
        return Dec(nan=True)
    a, b = Dec.of(a), Dec.of(b)
    sign = (a.v > 0) - (a.v < 0)
    if b.v == 0:
        return Dec(1, 0)
    if sign == 0:
        return Dec(0, 0)
    b.trim()
    if sign < 0 and b.s:
        return Dec(nan=True)
    a.trim()
    if not b.s:
        if b.v == 1:
            return a
        if b.v < 0:
            n = -b.v
            p = Dec(a.v ** n, a.s * n).trim() if a.s else Dec(a.v ** n, 0)
            return div(Dec(1, 0), p).trim()
        p = Dec(a.v ** b.v, a.s * b.v)
        return p.trim() if a.s else p
    base = a.decimal().copy_abs()  # abs() would round to the context's precision
    with localcontext(Context(prec=WORK + 10)):
        if b.s == 1 and b.v == 5:
            r = base.sqrt()
        else:
            r = (base.ln() * b.decimal()).exp()
    d = from_float(r)
    if sign < 0:
        d.v = -d.v
    return d


# ---------------------------------------------------------------- arguments and results

@dataclass
class Arg:
    """An argument field. numeric: its value (with the field's scale); data: its bytes; spec: the runtime item
    spec, when the program named a data item or wrote a literal (kept for the functions that copy their argument)."""

    numeric: bool
    value: Decimal | None
    data: bytes
    spec: list | None = None
    src: object = None  # the operand itself, for comparisons through the runtime
    kind: str = "alpha"  # num, alpha, edited, group, double, float, binary-like usage in spec

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def text(self) -> str:
        return self.data.decode("latin-1")

    def dec(self) -> Dec:
        if self.numeric and self.value is not None:
            return Dec.of(self.value)
        return Dec.of(_as_number(self.text))

    def int(self) -> int:
        """cob_get_int: the integer part."""
        d = self.dec()
        if d.nan:
            return 0
        return _tdiv(d.v, 10 ** d.s) if d.s > 0 else d.v * 10 ** -d.s


def _as_number(text: str) -> Decimal:
    """An alphanumeric field moved to a number: its digits (libcob's alnum-to-display move)."""
    digits = "".join(c for c in text if c.isdigit())
    return Decimal(digits or "0")


@dataclass
class Result:
    """What a function gives: kind is "dec" (a computed number), "uint"/"int" (9-digit binary), "num" (an unsigned
    DISPLAY number given as its digits), "alpha" (bytes), "copy" (an argument field, maybe with a new value or new
    bytes) or "double"."""

    kind: str
    dec: Dec | None = None
    n: int = 0
    data: bytes = b""
    arg: Arg | None = None
    value: Decimal | None = None
    double: float = 0.0
    error: bool = False  # EC-ARGUMENT-FUNCTION


def _r_dec(d: Dec) -> Result:
    if d.nan:
        return Result("uint", n=0, error=True)
    if d.s < 0:  # 999PP: the P positions are zeros in the number, not a negative scale in the field
        d = Dec(d.v * 10 ** -d.s, 0)
    return Result("dec", dec=d)


def _bad() -> Result:
    return Result("uint", n=0, error=True)


def layout(d: Dec) -> tuple[str, int, int, int, bool]:
    """cob_alloc_field: (usage, size, digits, scale, signed) of the field a computed number goes in."""
    signed = d.v < 0
    d = Dec.of(d).trim()
    bits = max(1, abs(d.v).bit_length())
    if bits < 33 - signed and d.s < 10:
        return "binary", 4, 9, d.s, signed
    if bits < 65 - signed and d.s < 19:
        return "binary", 8, 20, d.s, signed
    size = _digits_estimate(d.v)
    if d.s > size:
        size = d.s
    return "display", size, size, d.s, signed


_LOG10_2 = 0x4D104D427DE7FBCC  # GMP's mp_bases[10].logb2 for 64-bit limbs


def _digits_estimate(v: int) -> int:
    """mpz_sizeinbase(v, 10) as GMP works it out: from the bit count, so sometimes one digit too many."""
    bits = abs(v).bit_length()
    if bits == 0:
        return 1
    return (((_LOG10_2 + 1) * bits) >> 64) + 1


# ---------------------------------------------------------------- the functions

class Env:
    """What some functions read from the run. The runtime gives its own comparison (cob_cmp, with the program
    collating sequence), its clock and its random generator's state."""

    def __init__(self, cmp=None, current_date: str = "2026103123595800+0000", when_compiled: str = "2026103123595800+0000",
                 decimal_point: str = ".", currency: str = "$", rand_state: list | None = None):
        self._cmp = cmp
        self.current_date = current_date  # FUNCTION CURRENT-DATE (the run's fixed clock)
        self.when_compiled = when_compiled  # the compile time, which the recorder fixes to the same clock
        self.decimal_point = decimal_point
        self.currency = currency
        self.rand_state = rand_state if rand_state is not None else [1]

    def cmp(self, a: Arg, b: Arg) -> int:
        return self._cmp(a, b)


def _limit(a: Arg, highest: bool) -> Result:
    """HIGHEST-ALGEBRAIC and LOWEST-ALGEBRAIC: by the argument's category, digits and scale."""
    spec = a.spec
    if spec is None or spec[3] in ("alpha", "group"):
        return Result("alpha", data=(b"\xff" if highest else b"\x00") * a.size)
    kind, usage, digits, scale, signed, size = spec[3], spec[4], spec[5], spec[6], spec[7], spec[2]
    if kind == "edited":
        if spec[9] and any(c in spec[9].upper() for c in "XA"):  # alphanumeric edited
            return Result("alpha", data=(b"\xff" if highest else b"\x00") * digits)
    if usage in ("float", "double"):
        return _bad()
    if usage in ("native",):  # COMP-5: the storage's range
        bits = size * 8 - (1 if signed else 0)
        if highest:
            return _r_dec(Dec(2 ** bits - 1, scale))
        return _r_dec(Dec(-(2 ** bits), scale)) if signed else Result("uint", n=0)
    if not highest and not signed:
        return Result("uint", n=0)
    top = 10 ** digits - 1
    return _r_dec(Dec(top if highest else -top, scale))


def _numval_check(text: bytes, currency: bytes | None, chkcurr: bool, anycase: bool, dec_pt: int, cur_symb: int) -> int:
    """cob_check_numval: 0 when the text is a valid NUMVAL (or NUMVAL-C) argument, else the 1-based position
    of the first wrong character (one past the end when something is missing)."""
    size = len(text)
    begp: bytes | None = None
    if currency is not None:
        cur = currency
        begin = end = None
        for pos, ch in enumerate(cur):
            if chr(ch) in "0123456789+-.,*":
                return 1
            if ch == 0x20:
                continue
            if pos < len(cur) - 1 and cur[pos:pos + 2] in (b"CR", b"DB"):
                return 1
            if begin is None:
                begin = pos
            end = pos
        if begin is None:
            return 1
        begp = cur[begin:end + 1]
        if len(begp) >= size:
            begp = None
    elif chkcurr:
        begp = bytes([cur_symb])
    if not size:
        return 1
    csize = len(begp) if begp else 0
    plus_minus = digits = dec_seen = space_seen = 0
    n = 0
    while n < size:
        ch = text[n]
        if 0x30 <= ch <= 0x39:
            break
        if ch == 0x20:
            n += 1
            continue
        if ch in (0x2B, 0x2D):
            if plus_minus:
                return n + 1
            plus_minus = 1
            n += 1
            continue
        if ch in (0x2C, 0x2E):
            if ch != dec_pt:
                return n + 1
            break
        if begp and n < size - csize and text[n:n + csize] == begp:
            n += 1  # libcob breaks out of the switch only: the scan goes on one character further
            continue
        return n + 1
    if n == size:
        return n + 1
    while n < size:
        ch = text[n]
        if 0x30 <= ch <= 0x39:
            digits += 1
            if digits > MAX_DIGITS or space_seen:
                return n + 1
        elif ch in (0x2C, 0x2E):
            if dec_seen or space_seen:
                return n + 1
            if ch == dec_pt:
                dec_seen = 1
            elif not chkcurr:
                return n + 1
        elif ch == 0x20:
            space_seen = 1
        elif ch in (0x2B, 0x2D):
            if plus_minus:
                return n + 1
            plus_minus = 1
        elif ch in (0x43, 0x63) or ch in (0x44, 0x64):  # CR or DB
            if ch in (0x63, 0x64) and not anycase:
                return n + 1
            if plus_minus:
                return n + 1
            second = (0x52, 0x72) if ch in (0x43, 0x63) else (0x42, 0x62)
            if n < size - 1 and (text[n + 1] == second[0] or (anycase and text[n + 1] == second[1])):
                plus_minus = 1
                n += 2
                continue
            return n + 2
        else:
            return n + 1
        n += 1
    if not digits:
        return n + 1
    return 0


def _numval_f_check(text: bytes, dec_pt: int) -> int:
    """cob_check_numval_f."""
    size = len(text)
    if not size:
        return 1
    plus_minus = digits = dec_seen = space_seen = e_seen = exponent = e_plus_minus = 0
    n = 0
    while n < size:
        ch = text[n]
        if 0x30 <= ch <= 0x39:
            break
        if ch == 0x20:
            n += 1
            continue
        if ch in (0x2B, 0x2D):
            if plus_minus:
                return n + 1
            plus_minus = 1
            n += 1
            continue
        if ch in (0x2C, 0x2E):
            if ch != dec_pt:
                return n + 1
            break
        return n + 1
    if n == size:
        return n + 1
    while n < size:
        ch = text[n]
        if 0x30 <= ch <= 0x39:
            if e_seen:
                exponent += 1
                if exponent > 4 or not e_plus_minus:
                    return n + 1
            else:
                digits += 1
                if digits > MAX_DIGITS or space_seen:
                    return n + 1
        elif ch in (0x2C, 0x2E):
            if dec_seen or space_seen or e_seen:
                return n + 1
            if ch != dec_pt:
                return n + 1
            dec_seen = 1
        elif ch == 0x20:
            space_seen = 1
        elif ch == 0x45:  # E
            if e_seen:
                return n + 1
            e_seen = 1
        elif ch in (0x2B, 0x2D):
            if e_seen:
                if e_plus_minus:
                    return n + 1
                e_plus_minus = 1
            else:
                if plus_minus:
                    return n + 1
                plus_minus = 1
        else:
            return n + 1
        n += 1
    if not digits or (e_seen and not exponent):
        return n + 1
    return 0


def numval(arg: Arg, currency: Arg | None, kind: str, env) -> Result:
    """NUMVAL, NUMVAL-C."""
    text = arg.data
    dec_pt, cur_symb = ord(env.decimal_point), ord(env.currency[:1] or "$")
    if _numval_check(text, currency.data if currency is not None else None, kind == "C", False, dec_pt, cur_symb):
        return _bad()
    cur = currency.data if currency is not None and currency.size < len(text) else None
    digits: list[str] = []
    dec_digits = sign = dec_seen = 0
    i = 0
    while i < len(text):
        if not (i + 2 >= len(text)) and text[i:i + 2] in (b"CR", b"DB"):
            sign = 1
            break
        ch = text[i]
        if cur is not None:
            if not (i + len(cur) >= len(text)) and text[i:i + len(cur)] == cur:
                i += len(cur)
                continue
        elif kind == "C" and ch == cur_symb:
            i += 1
            continue
        if ch in (0x20, 0x2B):
            i += 1
            continue
        if ch == 0x2D:
            sign = 1
            i += 1
            continue
        if ch == dec_pt:
            dec_seen = 1
            i += 1
            continue
        if 0x30 <= ch <= 0x39:
            if dec_seen:
                dec_digits += 1
            digits.append(chr(ch))
        if len(digits) > MAX_DIGITS:
            break
        i += 1
    v = int("".join(digits) or "0")
    if sign and v:
        v = -v
    return _r_dec(Dec(v, dec_digits))


def numval_f(arg: Arg, env) -> Result:
    text = arg.data
    dec_pt = ord(env.decimal_point)
    if _numval_f_check(text, dec_pt):
        return _bad()
    digits: list[str] = []
    dec_digits = dec_seen = e_seen = exponent = plus_minus = e_plus_minus = 0
    for ch in text:
        if 0x30 <= ch <= 0x39:
            if e_seen:
                exponent = exponent * 10 + (ch & 0x0F)
            else:
                if dec_seen:
                    dec_digits += 1
                digits.append(chr(ch))
        elif ch == 0x45:
            e_seen = 1
        elif ch == 0x2D:
            if e_seen:
                e_plus_minus = 1
            else:
                plus_minus = 1
        elif ch == dec_pt:
            dec_seen = 1
    v = int("".join(digits) or "0")
    if v == 0:
        return _r_dec(Dec(0, 0))
    if plus_minus:
        v = -v
    if exponent:
        if e_plus_minus:
            return _r_dec(Dec(v, dec_digits + exponent))
        if dec_digits >= exponent:
            return _r_dec(Dec(v, dec_digits - exponent))
        return _r_dec(Dec(v * 10 ** (exponent - dec_digits), 0))
    return _r_dec(Dec(v, dec_digits))


_NORMAL = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
_LEAP = (0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366)
_MONTH_DAYS = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def _days_in_year(y: int) -> int:
    return 366 if _leap(y) else 365


def _days_up_to(year: int) -> int:
    y = year - 1  # days in the years 1601 .. year-1
    return 365 * (year - 1601) + (y // 4 - 400) - (y // 100 - 16) + (y // 400 - 4)


def _valid_day_of_month(y: int, m: int, d: int) -> bool:
    top = 29 if m == 2 and _leap(y) else _MONTH_DAYS[m]
    return 1 <= d <= top


def _date_of_integer(n: int) -> tuple[int, int, int]:
    days, year, leng = n, 1601, 365
    while days > leng:
        days -= leng
        year += 1
        leng = _days_in_year(year)
    table = _LEAP if _leap(year) else _NORMAL
    for i in range(1, 13):
        if days <= table[i]:
            return year, i, days - table[i - 1]
    return year, 13, days


def _day_of_integer(n: int) -> tuple[int, int]:
    days, year, leng = n, 1601, 365
    while days > leng:
        days -= leng
        year += 1
        leng = _days_in_year(year)
    return year, days


def _current_year() -> int:
    import datetime

    return datetime.datetime.now().year  # libcob reads time(NULL) here, not the run's clock


def _window(year: int, interval: int, current: int) -> int | None:
    maxyear = current + interval
    if not (1601 <= current <= 9999) or maxyear < 1700 or maxyear > 9999:
        return None
    if maxyear % 100 >= year:
        return year + 100 * (maxyear // 100)
    return year + 100 * (maxyear // 100 - 1)


def _substitute(original: bytes, pairs: list[tuple[bytes, bytes]], fold: bool) -> bytes:
    src = original.lower() if fold else original
    out = bytearray()
    i = 0
    while i < len(original):
        for match, rep in pairs:
            m = match.lower() if fold else match
            if not m or i + len(m) > len(original):
                continue  # a pattern with no characters matches nothing (and would never move on)
            if src[i:i + len(m)] == m:
                out += rep
                i += len(m)
                break
        else:
            out.append(original[i])
            i += 1
    return bytes(out)


def _rand(env, seed: int | None) -> float:
    state = env.rand_state
    if seed is not None:
        state[0] = max(seed, 0) & 0xFFFFFFFF
    state[0] = (state[0] * 214013 + 2531011) & 0xFFFFFFFF
    return ((state[0] >> 16) & 0x7FFF) / RAND_MAX


def call(name: str, args: list[Arg], env) -> Result:
    """FUNCTION name(args). Raises KeyError for a function this port does not have."""
    a = args[0] if args else None
    if name in ("SQRT", "EXP", "LOG", "LOG10", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN"):
        d = a.dec()
        x = d.decimal()
        if name == "SQRT":
            if d.v < 0:
                return _bad()
            return _r_dec(power(d.trim(), Dec(5, 1)))
        if name == "EXP":
            if d.v == 0:
                return Result("uint", n=1)
        elif name in ("LOG", "LOG10"):
            if d.v <= 0:
                return _bad()
            d.trim()
            if d.s == 0 and d.v == 1:
                return Result("uint", n=0)
        elif name in ("ASIN", "ACOS"):
            if x < -1 or x > 1:
                return _bad()
            if name == "ASIN" and d.v == 0:
                return Result("uint", n=0)
        elif name == "ATAN" and d.v == 0:
            return Result("uint", n=0)
        return _r_dec(from_float(_float_fn(name, x)))
    if name == "EXP10":
        d = a.dec()
        if d.v == 0:
            return Result("uint", n=1)
        d.trim()
        if not d.s:
            if d.v < 0 and -d.v < 2 ** 31:
                return _r_dec(Dec(1, -d.v))
            if d.v > 0:
                return _r_dec(Dec(10 ** d.v, 0))
        return _r_dec(power(Dec(10, 0), d))
    if name == "PI":
        return _r_dec(from_float(pi()))
    if name == "E":
        with localcontext(Context(prec=WORK + 10)):
            return _r_dec(from_float(Decimal(1).exp()))
    if name == "ABS":
        if not a.numeric:
            return _bad()
        return Result("copy", arg=a, value=abs(a.value))
    if name in ("INTEGER", "INTEGER-PART"):
        d = a.dec()
        if d.s < 0:
            d = Dec(d.v * 10 ** -d.s, 0)
        elif d.s > 0:
            q, r = _tdiv(d.v, 10 ** d.s), d.v - _tdiv(d.v, 10 ** d.s) * 10 ** d.s
            if name == "INTEGER" and d.v < 0 and r:
                q -= 1
            d = Dec(q, 0)
        return _r_dec(Dec(d.v, 0))
    if name == "FRACTION-PART":
        d = a.dec()
        if d.s > 0:
            q = _tdiv(d.v, 10 ** d.s)
            return _r_dec(Dec(d.v - q * 10 ** d.s, d.s))
        return _r_dec(Dec(0, 0))
    if name == "SIGN":
        v = a.dec().v
        return Result("int", n=(v > 0) - (v < 0))
    if name in ("MOD", "REM"):
        d2, d3 = args[0].dec(), args[1].dec()
        if d3.v == 0:
            return _bad()
        q = div(d2, d3)
        if q.s < 0:
            q = Dec(q.v * 10 ** -q.s, 0)
        elif q.s > 0:
            t = _tdiv(q.v, 10 ** q.s)
            if name == "MOD" and q.v < 0 and q.v - t * 10 ** q.s:
                t -= 1
            q = Dec(t, 0)
        return _r_dec(sub(args[0].dec(), mul(q, args[1].dec())))
    if name == "FACTORIAL":
        n = a.int()
        if n < 0:
            return _bad()
        return _r_dec(Dec(math.factorial(n), 0))
    if name == "SUM":
        total = Dec(0, 0)
        for x in args:
            total = add(total, x.dec())
        return _r_dec(total)
    if name == "MEAN":
        if len(args) == 1:
            return Result("copy", arg=a)
        total = Dec(0, 0)
        for x in args:
            total = add(total, x.dec())
        return _r_dec(div(total, Dec(len(args), 0)))
    if name in ("VARIANCE", "STANDARD-DEVIATION"):
        total = Dec(0, 0)
        for x in args:
            total = add(total, x.dec())
        mean = div(total, Dec(len(args), 0))
        if len(args) == 1:
            var = Dec(0, 0)
        else:
            acc = Dec(0, 0)
            for x in args:
                diff = sub(x.dec(), mean)
                acc = add(acc, mul(diff, diff))
            var = div(acc, Dec(len(args), 0))
        if name == "VARIANCE":
            return _r_dec(var)
        return _r_dec(power(var.trim(), Dec(5, 1)))
    if name in ("MAX", "MIN", "ORD-MAX", "ORD-MIN"):
        best, at = args[0], 1
        for i, x in enumerate(args[1:], start=2):
            c = env.cmp(x, best)
            if (c > 0) if name in ("MAX", "ORD-MAX") else (c < 0):
                best, at = x, i
        if name.startswith("ORD"):
            return Result("uint", n=at)
        return Result("copy", arg=best)
    if name in ("RANGE", "MIDRANGE"):
        lo = hi = args[0]
        for x in args[1:]:
            if env.cmp(x, lo) < 0:
                lo = x
            if env.cmp(x, hi) > 0:
                hi = x
        if name == "RANGE":
            return _r_dec(sub(hi.dec(), lo.dec()))
        return _r_dec(div(add(lo.dec(), hi.dec()), Dec(2, 0)))
    if name == "MEDIAN":
        if len(args) == 1:
            return Result("copy", arg=a)
        from .rt import crt_qsort

        rows = list(args)
        crt_qsort(rows, env.cmp)
        k = len(rows) // 2
        if len(rows) % 2:
            return Result("copy", arg=rows[k])
        return _r_dec(div(add(rows[k - 1].dec(), rows[k].dec()), Dec(2, 0)))
    if name == "PRESENT-VALUE":
        rate = add(a.dec(), Dec(1, 0))
        total = Dec(0, 0)
        for i, x in enumerate(args[1:], start=1):
            base = Dec(rate.v ** i, rate.s * i) if i > 1 else Dec.of(rate)
            total = add(total, div(x.dec(), base))
        return _r_dec(total)
    if name == "ANNUITY":
        d1, d2 = args[0].dec(), args[1].dec()
        if d1.v < 0 or d2.v <= 0 or d2.s != 0:
            return _bad()
        if d1.v == 0:
            return _r_dec(div(Dec(1, 0), d2))
        d3 = add(Dec.of(d1), Dec(1, 0)).trim()
        d3 = power(d3, Dec(-d2.v, 0).trim())
        d4 = sub(Dec(1, 0), d3).trim()
        return _r_dec(div(Dec.of(d1).trim(), d4))
    if name == "RANDOM":
        return Result("double", double=_rand(env, a.int() if a is not None else None))
    if name in ("NUMVAL", "NUMVAL-C"):
        return numval(a, args[1] if len(args) > 1 else None, "C" if name == "NUMVAL-C" else "", env)
    if name == "NUMVAL-F":
        return numval_f(a, env)
    if name in ("TEST-NUMVAL", "TEST-NUMVAL-C"):
        cur = args[1].data if len(args) > 1 else None
        return Result("int", n=_numval_check(a.data, cur, name == "TEST-NUMVAL-C", False, ord(env.decimal_point),
                                              ord(env.currency[:1] or "$")))
    if name == "TEST-NUMVAL-F":
        return Result("int", n=_numval_f_check(a.data, ord(env.decimal_point)))
    if name in ("LENGTH", "BYTE-LENGTH"):
        return Result("uint", n=a.size)
    if name == "ORD":
        return Result("uint", n=(a.data[0] if a.data else 0) + 1)
    if name == "CHAR":
        i = a.int()
        return Result("alpha", data=bytes([i - 1 if 1 <= i <= 256 else 0]))
    if name in ("UPPER-CASE", "LOWER-CASE", "REVERSE"):
        data = a.data.upper() if name == "UPPER-CASE" else a.data.lower() if name == "LOWER-CASE" else a.data[::-1]
        return Result("copy", arg=a, data=data)
    if name == "TRIM":
        direction = args[1] if len(args) > 1 else ""
        data = a.data
        if not data.strip(b" "):
            return Result("alpha", data=b"")
        if direction != "TRAILING":
            data = data.lstrip(b" ")
        if direction != "LEADING":
            data = data.rstrip(b" ")
        return Result("alpha", data=data)
    if name == "CONCATENATE":
        return Result("alpha", data=b"".join(x.data for x in args))
    if name in ("SUBSTITUTE", "SUBSTITUTE-CASE"):
        pairs = [(args[i].data, args[i + 1].data) for i in range(1, len(args) - 1, 2)]
        return Result("alpha", data=_substitute(a.data, pairs, name == "SUBSTITUTE-CASE"))
    if name == "STORED-CHAR-LENGTH":
        return Result("uint", n=len(a.data.rstrip(b" ")))
    if name == "CURRENT-DATE":
        return Result("alpha", data=env.current_date.encode("latin-1"))
    if name == "WHEN-COMPILED":
        return Result("alpha", data=env.when_compiled.encode("latin-1"))
    if name == "DATE-OF-INTEGER":
        n = a.int()
        if not 1 <= n <= 3067671:
            return Result("num", data=b"00000000", error=True)
        y, m, d = _date_of_integer(n)
        return Result("num", data=f"{y:04d}{m:02d}{d:02d}".encode())
    if name == "DAY-OF-INTEGER":
        n = a.int()
        if not 1 <= n <= 3067671:
            return Result("num", data=b"0000000", error=True)
        y, d = _day_of_integer(n)
        return Result("num", data=f"{y:04d}{d:03d}".encode())
    if name in ("INTEGER-OF-DATE", "TEST-DATE-YYYYMMDD"):
        v = a.int()
        y, m, d = v // 10000, v % 10000 // 100, v % 100
        test = name.startswith("TEST")
        if not 1601 <= y <= 9999:
            return Result("uint", n=1) if test else _bad()
        if not 1 <= m <= 12:
            return Result("uint", n=2) if test else _bad()
        if not _valid_day_of_month(y, m, d):
            return Result("uint", n=3) if test else _bad()
        if test:
            return Result("uint", n=0)
        return Result("uint", n=_days_up_to(y) + (_LEAP if _leap(y) else _NORMAL)[m - 1] + d)
    if name in ("INTEGER-OF-DAY", "TEST-DAY-YYYYDDD"):
        v = a.int()
        y, d = v // 1000, v % 1000
        test = name.startswith("TEST")
        if not 1601 <= y <= 9999:
            return Result("uint", n=1) if test else _bad()
        if not 1 <= d <= _days_in_year(y):
            return Result("uint", n=2) if test else _bad()
        return Result("uint", n=0) if test else Result("uint", n=_days_up_to(y) + d)
    if name in ("YEAR-TO-YYYY", "DATE-TO-YYYYMMDD", "DAY-TO-YYYYDDD"):
        v = a.int()
        interval = args[1].int() if len(args) > 1 else 50
        current = args[2].int() if len(args) > 2 else _current_year()
        unit = {"YEAR-TO-YYYY": 1, "DATE-TO-YYYYMMDD": 10000, "DAY-TO-YYYYDDD": 1000}[name]
        year, rest = (v, 0) if unit == 1 else (v // unit, v % unit)
        if name == "YEAR-TO-YYYY" and not 0 <= year <= 99:
            return _bad()
        if unit > 1 and not 0 <= year <= 999999:
            return _bad()
        w = _window(year, interval, current)
        if w is None:
            return _bad()
        return Result("int", n=w * unit + rest)
    if name == "COMBINED-DATETIME":
        days = a.int()
        secs = args[1].dec()
        if not 1 <= days <= 3067671 or cmp(secs, Dec(86400, 0)) > 0:
            return _bad()
        return _r_dec(add(Dec(days, 0), div(secs, Dec(100000, 0))))
    if name in ("HIGHEST-ALGEBRAIC", "LOWEST-ALGEBRAIC"):
        return _limit(a, name.startswith("HIGHEST"))
    raise KeyError(name)


NAMES = {
    "ABS", "ACOS", "ANNUITY", "ASIN", "ATAN", "BYTE-LENGTH", "CHAR", "COMBINED-DATETIME", "CONCATENATE", "COS",
    "CURRENT-DATE", "DATE-OF-INTEGER", "DATE-TO-YYYYMMDD", "DAY-OF-INTEGER", "DAY-TO-YYYYDDD", "E", "EXP", "EXP10",
    "FACTORIAL", "FRACTION-PART", "HIGHEST-ALGEBRAIC", "INTEGER", "INTEGER-OF-DATE", "INTEGER-OF-DAY", "INTEGER-PART",
    "LENGTH", "LOG", "LOG10", "LOWER-CASE", "LOWEST-ALGEBRAIC", "MAX", "MEAN", "MEDIAN", "MIDRANGE", "MIN", "MOD",
    "NUMVAL", "NUMVAL-C", "NUMVAL-F", "ORD", "ORD-MAX", "ORD-MIN", "PI", "PRESENT-VALUE", "RANDOM", "RANGE", "REM",
    "REVERSE", "SIGN", "SIN", "SQRT", "STANDARD-DEVIATION", "STORED-CHAR-LENGTH", "SUBSTITUTE", "SUBSTITUTE-CASE",
    "SUM", "TAN", "TEST-DATE-YYYYMMDD", "TEST-DAY-YYYYDDD", "TEST-NUMVAL", "TEST-NUMVAL-C", "TEST-NUMVAL-F", "TRIM",
    "UPPER-CASE", "VARIANCE", "WHEN-COMPILED", "YEAR-TO-YYYY",
}
TEXT_ARGS = {"UPPER-CASE", "LOWER-CASE", "REVERSE", "TRIM", "LENGTH", "BYTE-LENGTH", "NUMVAL", "NUMVAL-C", "NUMVAL-F",
             "ORD", "CONCATENATE", "SUBSTITUTE", "SUBSTITUTE-CASE", "STORED-CHAR-LENGTH", "TEST-NUMVAL", "TEST-NUMVAL-C",
             "TEST-NUMVAL-F"}  # arguments read as text: LOWER-CASE(NAME(2:19)) must not read NAME as a number
