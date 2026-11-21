"""The SPECIAL-NAMES paragraph: switches and their conditions, CLASS tests, SYMBOLIC CHARACTERS and device names.

    SWITCH-1 IS SW1 ON STATUS IS SW1-ON OFF STATUS IS SW1-OFF   (GnuCOBOL reads COB_SWITCH_1=ON|OFF at start)
    CLASS HEXA IS "0" THRU "9" "A" THRU "F"
    SYMBOLIC CHARACTERS BELL IS 8
    SYSIN IS KEYBOARD, CONSOLE IS CRT, SYSERR IS ERRORS
    ALPHABET CU IS "Z" "Y" "X" ALSO "W" "0" THRU "3"      ALPHABET EB IS EBCDIC
and, from OBJECT-COMPUTER, PROGRAM COLLATING SEQUENCE IS CU.
CURRENCY SIGN and DECIMAL-POINT IS COMMA are read elsewhere (the precompiler and the model).

An alphabet is a weight for each of the 256 characters (None: the native order). Measured on GnuCOBOL 3.1.2: the
characters an alphabet lists take positions in the order given (ALSO shares one, so they compare equal), every other
character follows in native order; EBCDIC is cobc's own ASCII-to-EBCDIC table, which is not code page 037 above X'7F';
NATIVE, STANDARD-1, STANDARD-2 and ASCII are the native order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[Xx]\"[0-9A-Fa-f]*\"|[Xx]'[0-9A-Fa-f]*'|[^\s,;]+")
_SWITCH = re.compile(r"^(?:SWITCH-?(\d+)|SW(\d+)|UPSI-(\d+))$")
DEVICES = {"SYSIN", "SYSIPT", "STDIN", "SYSOUT", "SYSLIST", "SYSLST", "STDOUT", "SYSPUNCH", "SYSPCH", "CONSOLE", "SYSERR", "STDERR",
           "PRINTER", "CSP", "FORMFEED", "TOP", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10", "C11", "C12",
           "S01", "S02", "S03", "S04", "S05", "TAB"}
_STOP = {"CURRENCY", "DECIMAL-POINT", "CLASS", "SYMBOLIC", "ALPHABET", "CRT", "CURSOR", "LOCALE", "CALL-CONVENTION", "NUMERIC", "CONSOLE"}
# EBCDIC as an alphabet: the position of each byte, found by sorting all 256 bytes WITH COLLATING SEQUENCE IS EBCDIC
EBCDIC = bytes.fromhex(
    "00010203372d2e2f1605250b0c0d0e0f101112133c3d322618193f271c1d1e1f405a7f7b5b6c507d4d5d5c4e6b604b61f0f1f2f3"
    "f4f5f6f7f8f97a5e4c7e6e6f7cc1c2c3c4c5c6c7c8c9d1d2d3d4d5d6d7d8d9e2e3e4e5e6e7e8e9ade0bd5f6d7981828384858687"
    "8889919293949596979899a2a3a4a5a6a7a8a9c06ad0a10768dc5142434447485253545756586367719c9ecbcccddbdddfecfcb0"
    "b1b23eb44555cede49699a9bab9fbab8b7aa8a8bb6b5624f6465662021227023727374be7677788024158c8d8e41061728299d2a"
    "2b2c090aac4aaeaf1b3031fa1a33343536590838bc39a0bfca3afe3b04cfda14e18f4675fdebeeed90efb3fbb9eabbff"
)
_FIGURATIVE = {"LOW-VALUE": "\x00", "LOW-VALUES": "\x00", "HIGH-VALUE": "\xff", "HIGH-VALUES": "\xff", "SPACE": " ",
               "SPACES": " ", "QUOTE": '"', "QUOTES": '"', "ZERO": "0", "ZEROS": "0", "ZEROES": "0"}


@dataclass
class SpecialNames:
    switch_conds: dict[str, tuple[int, bool]] = field(default_factory=dict)  # condition name -> (switch, True for ON STATUS)
    switch_names: dict[str, int] = field(default_factory=dict)  # mnemonic -> switch number (SET mnemonic TO ON)
    classes: dict[str, str] = field(default_factory=dict)  # class name -> every character it allows
    symbolic: dict[str, str] = field(default_factory=dict)  # symbolic character -> the character
    devices: dict[str, str] = field(default_factory=dict)  # mnemonic -> device (SYSIN, SYSOUT, SYSERR, CONSOLE, C01, ...)
    alphabets: dict[str, bytes | None] = field(default_factory=dict)  # alphabet name -> weight of each byte (None: native)
    program_collating: str | None = None  # OBJECT-COMPUTER. PROGRAM COLLATING SEQUENCE IS alphabet-name

    def collating(self, name: str | None = None) -> bytes | None:
        """The weights of an alphabet, or of the program collating sequence; None for the native order."""
        name = name or self.program_collating
        return self.alphabets.get(name) if name else None


def _literal_chars(tok: str) -> str:
    if tok[:1] in "\"'":
        return tok[1:-1].replace(tok[0] * 2, tok[0])
    if tok[:1] in "xX" and tok[1:2] in "\"'":
        return bytes.fromhex(tok[2:-1]).decode("latin-1")
    if tok.isdigit():  # an ordinal position in the collating sequence: 1 is the first character
        return _from_ordinal(int(tok))
    return ""


def _from_ordinal(n: int, weights: bytes | None = None) -> str:
    """The character at ordinal position n (1 to 256) of an alphabet: the byte whose weight is n - 1."""
    if not 1 <= n <= 256:
        raise ValueError(f"the ordinal position {n} is outside 1 to 256")
    if weights is None:
        return chr(n - 1)
    return chr(weights.index(n - 1))


def parse(text: str) -> SpecialNames:
    """text: the SPECIAL-NAMES paragraph, without the SPECIAL-NAMES header."""
    out = SpecialNames()
    toks = _TOKEN.findall(text)
    up = [t.upper() for t in toks]
    i = 0

    def word(k=0):
        return up[i + k] if i + k < len(up) else ""

    while i < len(toks):
        w = word()
        sm = _SWITCH.match(w)
        if sm:
            n = int(next(g for g in sm.groups() if g))
            i += 1
            if word() == "IS" and word(1) not in ("ON", "OFF"):
                out.switch_names[up[i + 1]] = n
                i += 2
            elif word() not in ("ON", "OFF", "IS") and word() and not _SWITCH.match(word()) and word() not in _STOP | DEVICES:
                out.switch_names[word()] = n
                i += 1
            while word() in ("ON", "OFF"):
                on = word() == "ON"
                i += 1
                if word() == "STATUS":
                    i += 1
                if word() == "IS":
                    i += 1
                if word():
                    out.switch_conds[up[i]] = (n, on)
                    i += 1
            continue
        if w == "CLASS" and i + 1 < len(toks):
            name = up[i + 1]
            i += 2
            if word() == "IS":
                i += 1
            chars = []
            while i < len(toks) and (toks[i][:1] in "\"'" or toks[i].isdigit() or (toks[i][:1] in "xX" and toks[i][1:2] in "\"'")):
                lo = _literal_chars(toks[i])
                i += 1
                if word() in ("THRU", "THROUGH") and i + 1 < len(toks):
                    hi = _literal_chars(toks[i + 1])
                    i += 2
                    chars.extend(chr(c) for c in range(ord(lo[:1] or "\0"), ord(hi[:1] or "\0") + 1))
                else:
                    chars.extend(lo)
            out.classes[name] = "".join(dict.fromkeys(chars))
            continue
        if w == "ALPHABET" and i + 1 < len(toks):
            name = up[i + 1]
            i += 2
            if word() == "FOR":
                i += 2  # FOR ALPHANUMERIC / FOR NATIONAL
            if word() == "IS":
                i += 1
            if word() in ("NATIVE", "STANDARD-1", "STANDARD-2", "ASCII"):
                out.alphabets[name] = None
                i += 1
                continue
            if word() == "EBCDIC":
                out.alphabets[name] = EBCDIC
                i += 1
                continue
            positions: list[list[int]] = []  # the characters at each position, in order

            def chars_at(k: int) -> str:
                return _FIGURATIVE.get(up[k], "") or _literal_chars(toks[k]) if k < len(toks) else ""

            while i < len(toks) and chars_at(i):
                first = chars_at(i)
                i += 1
                if word() in ("THRU", "THROUGH") and chars_at(i + 1):
                    lo, hi = ord(first[0]), ord(chars_at(i + 1)[0])
                    i += 2
                    step = 1 if hi >= lo else -1
                    positions += [[c] for c in range(lo, hi + step, step)]
                else:
                    positions += [[ord(c)] for c in first]
                while word() == "ALSO" and chars_at(i + 1):
                    positions[-1] += [ord(c) for c in chars_at(i + 1)]
                    i += 2
            weight: list[int | None] = [None] * 256
            pos = 0
            for group in positions:
                fresh = [c for c in group if c < 256 and weight[c] is None]
                if fresh:
                    for c in fresh:
                        weight[c] = pos
                    pos += 1
            for c in range(256):  # the characters it does not list come after, in native order
                if weight[c] is None:
                    weight[c] = pos
                    pos += 1
            out.alphabets[name] = bytes(weight)
            continue
        if w == "SYMBOLIC":
            i += 1
            if word() in ("CHARACTERS", "CHARACTER"):
                i += 1
            names, values, alpha = [], [], None

            def flush() -> None:
                for nm, n in zip(names, values):  # IN alphabet-name: the ordinal counts in that alphabet
                    out.symbolic[nm] = _from_ordinal(n, out.alphabets.get(alpha) if alpha else None)

            while i < len(toks) and word() not in _STOP and not _SWITCH.match(word()) and word() not in DEVICES:
                if word() in ("IS", "ARE"):
                    i += 1
                    continue
                if word() == "IN":
                    alpha = word(1)
                    i += 2
                    continue
                if toks[i].isdigit():
                    values.append(int(toks[i]))
                else:
                    if values and len(values) == len(names):  # a new group of names starts
                        flush()
                        names, values, alpha = [], [], None
                    names.append(up[i])
                i += 1
            flush()
            continue
        if w in DEVICES and word(1) == "IS" and i + 2 < len(toks):
            out.devices[up[i + 2]] = w
            i += 3
            continue
        i += 1
    return out


def from_sentences(items: list[tuple[int, str]]) -> SpecialNames:
    """Find the SPECIAL-NAMES paragraph among a program's sentences and read it, with the program collating
    sequence the OBJECT-COMPUTER paragraph names."""
    parts: list[str] = []
    inside = False
    collating = None
    in_object = False
    for _, s in items:
        up = s.upper().strip()
        if up == "OBJECT-COMPUTER":
            in_object = True
            continue
        if in_object:
            m = re.search(r"\bCOLLATING\s+SEQUENCE\s+(?:FOR\s+ALPHANUMERIC\s+)?(?:IS\s+)?([A-Z0-9][A-Z0-9-]*)", up)
            if m:
                collating = m.group(1)
            if re.match(r"^(SPECIAL-NAMES|SOURCE-COMPUTER|REPOSITORY|INPUT-OUTPUT\s+SECTION|DATA\s+DIVISION|PROCEDURE\s+DIVISION)\b", up):
                in_object = False
        if up == "SPECIAL-NAMES":
            inside = True
            continue
        if inside:
            if re.match(r"^(INPUT-OUTPUT\s+SECTION|FILE-CONTROL|DATA\s+DIVISION|PROCEDURE\s+DIVISION|REPOSITORY|"
                        r"SOURCE-COMPUTER|OBJECT-COMPUTER)\b", up):
                break
            parts.append(s)
    out = parse(" ".join(parts))
    out.program_collating = collating
    return out
