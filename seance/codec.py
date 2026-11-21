"""Bytes <-> values for every COBOL data item, matching GnuCOBOL's storage (see seance.layout)."""

from __future__ import annotations

import math
import struct
from decimal import Decimal

from .cobol_num import NEG_DIGITS, format_edited, format_numeric, store

ENC = "latin-1"


def _scaled(value: Decimal, scale: int) -> int:
    return int((abs(value) * (Decimal(10) ** scale)).to_integral_value())


def encode(spec, value) -> bytes:
    """spec: (kind, usage, digits, scale, signed, sign, pic, size, justified, blank_zero)."""
    kind, usage, digits, scale, signed, sign, pic, size, justified, blank_zero = spec
    if kind in ("alpha", "group"):
        text = str(value)
        if kind == "alpha" and pic and any(c in "B0/" for c in pic):
            from .editing import format_alpha

            text = format_alpha(text, pic)  # alphanumeric-edited: X, A and 9 take the characters, B 0 / are inserted
        raw = text.encode(ENC, errors="replace")
        if justified:
            return raw[-size:].rjust(size, b" ") if size else b""
        return raw[:size].ljust(size, b" ")
    if kind == "edited":
        return format_edited(Decimal(value), pic, "$", blank_zero).encode(ENC)[:size].ljust(size, b" ")
    value = Decimal(value)
    negative = value.is_signed() and signed
    if usage in ("float", "double"):
        return struct.pack("<f" if usage == "float" else "<d", to_float(value, usage))
    if usage == "display":
        if blank_zero and value == 0:  # BLANK WHEN ZERO on a plain numeric item: spaces
            return b" " * size
        return format_numeric(value, digits, scale, signed, sign if signed else "none").encode(ENC)
    if usage == "packed":
        n = _scaled(value, scale) % (10**digits)
        nib = str(n).zfill(size * 2 - 1)[-(size * 2 - 1):]
        nib += ("d" if negative else "c") if signed else "f"
        return bytes.fromhex(nib)
    if usage in ("binary", "native", "index"):
        n = _scaled(value, scale)
        if usage == "binary" and digits:
            n %= 10**digits  # GnuCOBOL binary-truncate: COMP keeps only the PIC's digits; COMP-5 does not
        if negative:
            n = -n
        bits = 8 * size
        if signed:
            n = ((n + (1 << (bits - 1))) % (1 << bits)) - (1 << (bits - 1))
        else:
            n %= 1 << bits
        return n.to_bytes(size, "little" if usage in ("native", "index") else "big", signed=signed)
    raise ValueError(f"cannot encode usage {usage}")


def _display_raw(spec, text: str) -> str:
    """DISPLAY of a USAGE DISPLAY number, as GnuCOBOL prints it (measured): the bytes as they are, not their value, so
    a field holding junk shows the junk. The sign is read from where the PIC keeps it (an overpunch that is not a
    sign counts as +0), a point goes where V is, a character right of the point that is not a digit shows as 0, and
    B shows as a space."""
    kind, usage, digits, scale, signed, sign = spec[0], spec[1], spec[2], spec[3], spec[4], spec[5]
    body, neg = text, False
    if signed:
        if sign == "leading_sep":
            neg, body = body[:1] == "-", body[1:]
        elif sign == "trailing_sep":
            neg, body = body[-1:] == "-", body[:-1]
        elif body:
            k = 0 if sign == "leading_over" else len(body) - 1
            ch = body[k]
            if ch in NEG_DIGITS:
                neg, ch = True, str(NEG_DIGITS.index(ch))
            elif not ch.isdigit():
                ch = "0"
            body = body[:k] + ch + body[k + 1:]
    if scale < 0:
        body = body + "0" * -scale
    elif scale > len(body):
        body = "." + body.rjust(scale, "0")
    elif scale:
        ints = len(body) - scale
        body = body[:ints] + "." + "".join(c if c.isdigit() or c in ",+-/B" else "0" for c in body[ints:])
    body = body.replace("B", " ")
    if signed:
        if neg and not body.strip(" 0.,"):
            neg = False  # a negative zero (stored by MOVE of a small negative) prints as +0 (measured)
        mark = "-" if neg else "+"
        return body + mark if sign == "trailing_sep" else mark + body
    return body


def _lenient_display(text: str, digits: int, scale: int, signed: bool, sign: str) -> Decimal:
    """Read a DISPLAY number the way GnuCOBOL does even when the data is not clean (spaces, junk)."""
    neg = False
    body = text
    if sign == "leading_sep" and body[:1] in "+-":
        neg, body = body[0] == "-", body[1:]
    elif sign == "trailing_sep" and body[-1:] in "+-":
        neg, body = body[-1] == "-", body[:-1]
    out = []
    for i, ch in enumerate(body[:digits]):
        if ch.isdigit():
            out.append(ch)
        elif ch in NEG_DIGITS and ((sign == "trailing_over" and i == len(body) - 1) or (sign == "leading_over" and i == 0)):
            neg = True
            out.append(str(NEG_DIGITS.index(ch)))
        else:
            out.append(str(ord(ch) & 0x0F) if (ord(ch) & 0x0F) < 10 else "0")
    n = int("".join(out) or "0")
    v = Decimal(n).scaleb(-scale)
    return v.copy_negate() if neg and signed else v


def decode(spec, data: bytes):
    kind, usage, digits, scale, signed, sign, pic, size, justified, blank_zero = spec
    if kind in ("alpha", "group", "edited"):
        return data.decode(ENC)
    if usage == "display":
        return _lenient_display(data.decode(ENC), digits, scale, signed, sign if signed else "none")
    if usage in ("float", "double"):
        return Decimal(struct.unpack("<f" if usage == "float" else "<d", bytes(data))[0])
    if usage == "packed":
        h = data.hex()
        body, sgn = h[:-1], h[-1:]
        n = int("".join(c if c.isdigit() else "0" for c in body) or "0")
        v = Decimal(n).scaleb(-scale)
        return v.copy_negate() if sgn in ("d", "b") and signed else v
    if usage in ("binary", "native", "index"):
        n = int.from_bytes(data, "little" if usage in ("native", "index") else "big", signed=signed)
        return Decimal(n).scaleb(-scale)
    raise ValueError(f"cannot decode usage {usage}")


def zero(spec) -> bytes:
    kind = spec[0]
    if kind in ("alpha", "group"):
        return b" " * spec[7]
    if kind == "edited":
        return encode(spec, Decimal(0))
    return encode(spec, Decimal(0))


NATIVE_DIGITS = {1: 3, 2: 5, 4: 10, 8: 20}


def display_text(spec, data: bytes) -> str:
    """How DISPLAY prints an item. Numbers are zero-padded to their full width and signed when the PIC is signed.
    COMP-5 prints at the width of its storage (a 2-byte item prints 5 digits). A packed or binary zero never
    prints a minus; a DISPLAY item keeps its sign even at zero."""
    kind, usage, digits, scale, signed, size = spec[0], spec[1], spec[2], spec[3], spec[4], spec[7]
    if kind != "num":
        return data.decode(ENC)
    if usage in ("float", "double"):
        return float_text(struct.unpack("<f" if usage == "float" else "<d", bytes(data))[0], usage)
    if usage == "display" and spec[9] and not bytes(data).strip():  # BLANK WHEN ZERO holding zero: DISPLAY shows the spaces
        return data.decode(ENC)
    if usage == "display":
        return _display_raw(spec, data.decode(ENC))
    v = decode(spec, data)
    n = _scaled(v, scale)
    width = NATIVE_DIGITS.get(size, digits) if usage in ("native", "index") else digits
    text = str(n % (10**width)).zfill(width)
    if scale < 0:  # PIC 999PP: the P positions print as zeros
        text = text + "0" * -scale
    elif usage in ("native", "index"):
        pass  # COMP-5 with V: DISPLAY prints the stored integer, no point (measured on 3.1.2)
    elif scale > width:  # PIC VPP99
        text = "." + text.zfill(scale)
    elif scale:
        text = text[:-scale] + "." + text[-scale:]
    if signed:
        negative = v.is_signed() if usage == "display" else v < 0
        mark = "-" if negative else "+"
        text = text + mark if spec[5] == "trailing_sep" else mark + text  # an overpunched sign still prints in front
    return text


def store_into(spec, value: Decimal, rounded: bool = False, move: bool = False) -> Decimal:
    """Apply the PIC's truncation and sign rules to a number before it is encoded.

    COMP-5 and INDEX items keep whatever fits in their bytes (they wrap at the storage size, not the PIC's digits).
    """
    kind, usage, digits, scale, signed, size = spec[0], spec[1], spec[2], spec[3], spec[4], spec[7]
    if usage in ("float", "double"):
        return decode(spec, encode(spec, value))
    if usage in ("native", "index"):
        n = _scaled(store(value, 38, scale, signed, rounded, move), scale)
        if signed and store(value, 38, scale, signed, rounded, move).is_signed():
            n = -n
        bits = 8 * size
        n = ((n + (1 << (bits - 1))) % (1 << bits)) - (1 << (bits - 1)) if signed else n % (1 << bits)
        return Decimal(n).scaleb(-scale)
    return store(value, digits, scale, signed, rounded, move)


def to_float(value: Decimal, usage: str = "double") -> float:
    """A decimal value as GnuCOBOL stores it in COMP-2: the exact value cut toward zero to a double (it converts
    through GMP's mpf_get_d, which truncates; measured: 0.0001 becomes 9.999999999999999E-5). COMP-1 then rounds
    that double to single precision, as a C cast does."""
    if value == 0:
        return 0.0
    f = float(value)
    if math.isfinite(f) and abs(Decimal(f)) > abs(value):
        f = math.nextafter(f, 0.0)
    if usage == "float":
        f = struct.unpack("<f", struct.pack("<f", f))[0]
    return f


def float_text(f: float, usage: str) -> str:
    """DISPLAY of COMP-1 / COMP-2: %G with 8 or 16 significant digits, exponent without leading zeros (measured)."""
    text = ("%.8G" if usage == "float" else "%.16G") % f
    if "E" in text:
        mant, exp = text.split("E")
        text = mant + "E" + exp[0] + (exp[1:].lstrip("0") or "0")
    return text
