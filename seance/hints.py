"""Test values taken from the program itself, so generated inputs reach every branch.

For each input field and each ACCEPTed item: the values of its level-88 condition names, and every literal it is
compared against in the PROCEDURE DIVISION (directly, or through a field it is MOVEd into), plus the neighbours
of numeric literals (n - 1 unit, n, n + 1 unit).
"""

from __future__ import annotations

import re
from decimal import Decimal

from .layout import leaves
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
    """Hints from the main program and every program it calls, merged."""
    out: dict[str, list] = {}
    for m in model._every():
        for k, values in _hints(model, m).items():
            out.setdefault(k, [])
            out[k] += [v for v in values if v not in out[k]]
    return out


def _hints(model: ProgramModel, unit: ProgramModel) -> dict[str, list]:
    from .translate import ENDERS, VERBS, build_names

    names, _ = build_names(unit)
    targets = {}
    for f in model.inputs:
        if f.record is not None:
            for lf in leaves(f.record):
                if lf.name != "FILLER":
                    targets[lf.item.name] = lf.item
    for name in unit.accepts:
        if name in names.by_name:
            targets[name] = names.by_name[name][0]
    hints: dict[str, list] = {n: [] for n in targets}
    for n, it in targets.items():
        for _, choices in it.conds:
            for lo, hi in choices:
                for v in (lo, hi):
                    if isinstance(v, (str, Decimal)) and v not in ("SPACE", "ZERO", "HIGH", "LOW", "QUOTE"):
                        hints[n].append(v)

    proc = " ".join(t for _, t in unit.proc_items)
    aliases: dict[str, set[str]] = {n: {n} for n in targets}
    words = proc.upper().split()
    for i, w in enumerate(words):
        if w == "MOVE" and i + 2 < len(words) and words[i + 2] == "TO" and words[i + 1] in aliases:
            j = i + 3
            while j < len(words) and words[j] not in VERBS and words[j] not in ENDERS and re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", words[j]):
                aliases[words[i + 1]].add(words[j])
                j += 1
    for n in targets:
        for alias in aliases[n]:
            pat_a = re.compile(rf"(?<![A-Z0-9-]){re.escape(alias)}(?![A-Z0-9-])\s+(?:IS\s+)?(?:NOT\s+)?{_REL}\s*{_LIT}", re.I)
            pat_b = re.compile(rf"{_LIT}\s*{_REL}\s*{re.escape(alias)}(?![A-Z0-9-])", re.I)
            for m in list(pat_a.finditer(proc)) + list(pat_b.finditer(proc)):
                v = _lit(m.group(1))
                if v is not None:
                    hints[n].append(v)

    out: dict[str, list] = {}
    for n, values in hints.items():
        it = targets[n]
        expanded: list = []
        for v in values:
            if isinstance(v, Decimal) and it.kind == "num":
                unit = Decimal(1).scaleb(-it.scale)
                expanded += [v - unit, v, v + unit]
            elif isinstance(v, str) and it.kind == "alpha":
                expanded.append(v[: it.size])
            elif isinstance(v, Decimal) and it.kind == "alpha":
                expanded.append(str(v)[: it.size])
        clean = []
        for v in expanded:
            if isinstance(v, Decimal):
                if not it.signed and v < 0:
                    continue
                if abs(v) > it.max_value:
                    continue
            if v not in clean:
                clean.append(v)
        if clean:
            out[n] = clean
    return out
