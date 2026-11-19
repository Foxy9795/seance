"""Mainframe data files (EBCDIC) to the ASCII layout GnuCOBOL uses, field by field.

A file downloaded from z/OS in binary keeps EBCDIC text and zoned decimals, but its packed (COMP-3) and binary
(COMP) fields are the same bytes on both sides. Converting the whole file with a code page would corrupt those,
so each field is converted according to the record layout:
- text, edited and FILLER: code page 037 (or another EBCDIC code page) to Latin-1
- zoned decimal (display numbers): read the EBCDIC digits and sign nibble, then write the GnuCOBOL form
- packed and big-endian binary: unchanged; COMP-5 (native) is byte-swapped, since z/OS is big-endian
"""

from __future__ import annotations

from decimal import Decimal

from .codec import ENC, encode
from .layout import Item, leaves

CODE_PAGES = ("cp037", "cp1140", "cp500", "cp273", "cp1047") 


def _spec(it: Item) -> tuple:
    return (it.kind, it.usage, it.digits, it.scale, it.signed, it.sign, it.pic, it.size, it.justified, it.blank_zero)


def _zoned(raw: bytes, it: Item) -> Decimal:
    body = raw
    neg = False
    if it.sign == "leading_sep":
        neg, body = raw[:1] == b"\x60", raw[1:]  # EBCDIC '-' is 0x60
    elif it.sign == "trailing_sep":
        neg, body = raw[-1:] == b"\x60", raw[:-1]
    digits = []
    for i, b in enumerate(body):
        zone, digit = b >> 4, b & 0x0F
        carries_sign = (it.sign in ("trailing_over", "none") and i == len(body) - 1) or (it.sign == "leading_over" and i == 0)
        if carries_sign and zone in (0xD, 0xB):
            neg = True
        digits.append(str(digit if digit < 10 else 0))
    v = Decimal(int("".join(digits) or "0")).scaleb(-it.scale)
    return -v if neg and it.signed else v


def record_to_ascii(rec: Item, data: bytes, code_page: str = "cp037") -> bytes:
    out = bytearray(data.ljust(rec.size, b"\x40")[: rec.size])
    covered = bytearray(rec.size)
    for lf in leaves(rec):
        it, lo, hi = lf.item, lf.offset, lf.offset + lf.width
        raw = bytes(data[lo:hi])
        if it.kind == "num" and it.usage == "display":
            out[lo:hi] = encode(_spec(it), _zoned(raw, it))
        elif it.kind == "num" and it.usage == "native":
            out[lo:hi] = raw[::-1]
        elif it.kind == "num":
            out[lo:hi] = raw  # packed, binary: the same bytes on z/OS and here
        else:
            out[lo:hi] = raw.decode(code_page).encode(ENC, errors="replace")
        covered[lo:hi] = b"\x01" * (hi - lo)
    for i, c in enumerate(covered):  # bytes no field describes (FILLER without PIC, slack): treat as text
        if not c:
            out[i:i + 1] = bytes(data[i:i + 1]).decode(code_page).encode(ENC, errors="replace") if i < len(data) else b" "
    return bytes(out)


def file_to_ascii(rec: Item, size: int, data: bytes, code_page: str = "cp037") -> bytes:
    if code_page not in CODE_PAGES:
        raise ValueError(f"Unknown EBCDIC code page {code_page}. Use one of: {', '.join(CODE_PAGES)}.")
    if len(data) % size:
        raise ValueError(f"The file is {len(data)} bytes, which is not a whole number of {size}-byte records. "
                         "Download it from the mainframe in binary, with fixed-length records (RECFM=FB).")
    return b"".join(record_to_ascii(rec, data[i:i + size], code_page) for i in range(0, len(data), size))
