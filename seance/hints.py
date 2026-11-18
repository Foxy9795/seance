"""Test values taken from the program itself, so generated inputs reach every branch.

For each input field: the values of its level-88 condition names, and every literal it is compared
against in the PROCEDURE DIVISION, plus the neighbours of numeric literals (n - 1 unit, n, n + 1 unit).
"""

from __future__ import annotations

import re
from decimal import Decimal

from .model import ProgramModel

_REL = r"(?:=|>=|<=|<>|>|<|EQUAL(?:\s+TO)?|GREATER(?:\s+THAN)?(?:\s+OR\s+EQUAL(?:\s+TO)?)?|LESS(?:\s+THAN)?(?:\s+OR\s+EQUAL(?:\s+TO)?)?)"
_LIT = r"(\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[+-]?\d*\.?\d+)"


def _lit(text: str):
    if text[:1] in "\"'":
        return text[1:-1]
    try:
        return Decimal(text)
    except Exception:
        return None


def value_hints(model: ProgramModel) -> dict[str, list]:
    fields = {f.name: f for f in model.in_layout.fields if f.name != "FILLER"}
    hints: dict[str, list] = {name: [] for name in fields}

    # level-88 values attached to input fields
    last = ""
    for _, text in model.fd_items.get(model.input.name, []):
        m = re.match(r"^\s*(\d{1,2})\s+([A-Z0-9-]+)(.*)$", text, re.I | re.S)
        if not m:
            continue
        level, name, rest = int(m.group(1)), m.group(2).upper(), m.group(3)
        if level != 88:
            last = name
            continue
        if last in hints:
            vm = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?(.*)$", rest, re.I | re.S)
            for tok in re.findall(_LIT, vm.group(1) if vm else ""):
                v = _lit(tok)
                if v is not None:
                    hints[last].append(v)

    # literals compared with input fields, in either order, including work fields the input is moved into
    proc = " ".join(t for _, t in model.proc_items)
    from .translate import ENDERS, VERBS

    aliases: dict[str, set[str]] = {name: {name} for name in fields}
    words = proc.upper().split()
    for i, w in enumerate(words):
        if w == "MOVE" and i + 2 < len(words) and words[i + 2] == "TO" and words[i + 1] in aliases:
            j = i + 3
            while j < len(words) and words[j] not in VERBS and words[j] not in ENDERS and re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", words[j]):
                aliases[words[i + 1]].add(words[j])
                j += 1
    for name in fields:
        for alias in aliases[name]:
            pat_a = re.compile(rf"\b{re.escape(alias)}\s+(?:IS\s+)?(?:NOT\s+)?{_REL}\s*{_LIT}", re.I)
            pat_b = re.compile(rf"{_LIT}\s*{_REL}\s*{re.escape(alias)}\b", re.I)
            for m in list(pat_a.finditer(proc)) + list(pat_b.finditer(proc)):
                v = _lit(m.group(1))
                if v is not None:
                    hints[name].append(v)

    out: dict[str, list] = {}
    for name, values in hints.items():
        f = fields[name]
        expanded: list = []
        for v in values:
            if isinstance(v, Decimal) and f.kind != "alpha":
                unit = Decimal(1).scaleb(-f.scale) if f.kind == "numeric" else Decimal("0.01")
                expanded += [v - unit, v, v + unit]
            elif isinstance(v, str) and f.kind == "alpha":
                expanded.append(v[: f.width])
            elif isinstance(v, Decimal) and f.kind == "alpha":
                expanded.append(str(v)[: f.width])
        clean = []
        for v in expanded:
            if isinstance(v, Decimal) and f.kind == "numeric":
                if not f.signed and v < 0:
                    continue
                if abs(v) > f.max_value:
                    continue
            if v not in clean:
                clean.append(v)
        if clean:
            out[name] = clean
    return out
