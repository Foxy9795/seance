"""The SPECIAL-NAMES paragraph: switches and their conditions, CLASS tests, SYMBOLIC CHARACTERS and device names.

    SWITCH-1 IS SW1 ON STATUS IS SW1-ON OFF STATUS IS SW1-OFF   (GnuCOBOL reads COB_SWITCH_1=ON|OFF at start)
    CLASS HEXA IS "0" THRU "9" "A" THRU "F"
    SYMBOLIC CHARACTERS BELL IS 8
    SYSIN IS KEYBOARD, CONSOLE IS CRT, SYSERR IS ERRORS
CURRENCY SIGN and DECIMAL-POINT IS COMMA are read elsewhere (the precompiler and the model).
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


@dataclass
class SpecialNames:
    switch_conds: dict[str, tuple[int, bool]] = field(default_factory=dict)  # condition name -> (switch, True for ON STATUS)
    switch_names: dict[str, int] = field(default_factory=dict)  # mnemonic -> switch number (SET mnemonic TO ON)
    classes: dict[str, str] = field(default_factory=dict)  # class name -> every character it allows
    symbolic: dict[str, str] = field(default_factory=dict)  # symbolic character -> the character
    devices: dict[str, str] = field(default_factory=dict)  # mnemonic -> device (SYSIN, SYSOUT, SYSERR, CONSOLE, C01, ...)


def _literal_chars(tok: str) -> str:
    if tok[:1] in "\"'":
        return tok[1:-1].replace(tok[0] * 2, tok[0])
    if tok[:1] in "xX" and tok[1:2] in "\"'":
        return bytes.fromhex(tok[2:-1]).decode("latin-1")
    if tok.isdigit():  # an ordinal position in the collating sequence: 1 is the first character
        return chr(int(tok) - 1)
    return ""


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
        if w == "SYMBOLIC":
            i += 1
            if word() in ("CHARACTERS", "CHARACTER"):
                i += 1
            names, values = [], []
            while i < len(toks) and word() not in _STOP and not _SWITCH.match(word()) and word() not in DEVICES:
                if word() in ("IS", "ARE"):
                    i += 1
                    continue
                if word() == "IN":
                    i += 2  # IN alphabet-name: the ordinal is in that alphabet, which Séance reads as the native one
                    continue
                if toks[i].isdigit():
                    values.append(chr(int(toks[i]) - 1))
                else:
                    if values and len(values) == len(names):  # a new group of names starts
                        for nm, ch in zip(names, values):
                            out.symbolic[nm] = ch
                        names, values = [], []
                    names.append(up[i])
                i += 1
            for nm, ch in zip(names, values):
                out.symbolic[nm] = ch
            continue
        if w in DEVICES and word(1) == "IS" and i + 2 < len(toks):
            out.devices[up[i + 2]] = w
            i += 3
            continue
        i += 1
    return out


def from_sentences(items: list[tuple[int, str]]) -> SpecialNames:
    """Find the SPECIAL-NAMES paragraph among a program's sentences and read it."""
    parts: list[str] = []
    inside = False
    for _, s in items:
        up = s.upper().strip()
        if up == "SPECIAL-NAMES":
            inside = True
            continue
        if inside:
            if re.match(r"^(INPUT-OUTPUT\s+SECTION|FILE-CONTROL|DATA\s+DIVISION|PROCEDURE\s+DIVISION|REPOSITORY|"
                        r"SOURCE-COMPUTER|OBJECT-COMPUTER)\b", up):
                break
            parts.append(s)
    return parse(" ".join(parts))
