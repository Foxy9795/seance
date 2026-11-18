"""Check a Python migration against the real COBOL program.

Two kinds of evidence:
1. Saved test sets: whole runs of the COBOL (input files and console input, plus what it wrote), replayed
   through the Python and compared byte for byte.
2. Random runs: Hypothesis generates fresh input files and console input, both programs run on them, and the
   first difference is shrunk to a small case (fewer records, plainer values) a person can read.
"""

from __future__ import annotations

import importlib
import random
import string
import sys
from dataclasses import dataclass, field
from decimal import Decimal

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

from .cases import Case, Diff, build_case, compare, console_lines, load_set, run_cobol, run_python, set_names, show
from .layout import Item, leaves
from .model import ProgramModel
from .recorder import ROOT, compile_legacy, get_model

SHRINK_BUDGET = 80  # COBOL runs spent making a failing case smaller
MAX_RECORDS = 25  # records per input file in a random run
SHOWN_DIFFS = 20


@dataclass
class Report:
    program: str
    implementation: str
    sets: list[dict] = field(default_factory=list)  # name, label, compared, differing
    diffs: list[dict] = field(default_factory=list)  # first differences in the saved sets
    random_runs: int = 0
    random_failure: dict | None = None  # the smallest failing random case: inputs, stdin, diffs
    review: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return not self.diffs and self.random_failure is None and all(s["differing"] == 0 for s in self.sets)


def _fresh(name: str):
    """Import `name` from disk every time, so edits made since the last run are picked up."""
    for loaded in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[loaded]
    importlib.invalidate_caches()
    return importlib.import_module(name)


def load_implementation(implementation: str):
    return _fresh(implementation)


# ---------------------------------------------------------------- saved sets

def replay_sets(program: str, impl, model: ProgramModel, root=ROOT) -> tuple[list[dict], list[dict]]:
    sets, diffs = [], []
    for name in set_names(program, root):
        case, expected, meta = load_set(program, name, root)
        actual = run_python(impl, case)
        found, units = compare(model, expected, actual)
        sets.append({"name": name, "label": meta["label"], "records": meta.get("records", 0), "console_lines": len(case.stdin),
                     "compared": units, "differing": len(found),
                     "python_error": actual.error, "cobol_error": expected.error})
        for d in found[: max(0, SHOWN_DIFFS - len(diffs))]:
            diffs.append({"set": name, **d.to_dict()})
    return sets, diffs


# ---------------------------------------------------------------- random runs

_TEXT = string.ascii_uppercase + string.digits + " -.,/"


def _leaf_strategy(it: Item, hints: list):
    if it.kind == "alpha":
        base = st.text(alphabet=_TEXT, min_size=0, max_size=it.size)
        picks = [h for h in hints if isinstance(h, str)]
        return st.one_of(st.sampled_from(picks), base) if picks else base
    digits = it.digits if it.kind == "num" else 5
    scale = it.scale if it.kind == "num" else 2
    signed = it.signed if it.kind == "num" else False
    top = 10**digits - 1
    edges = [0, 1, top, top - 1] + ([-1, -top] if signed else [])
    edges += [int(Decimal(h).scaleb(scale)) for h in hints if isinstance(h, Decimal) and abs(Decimal(h).scaleb(scale)) <= top]
    small = min(top, 10**3)
    ints = st.one_of(st.sampled_from(edges), st.integers(-small if signed else 0, small), st.integers(-top if signed else 0, top))
    return ints.map(lambda n, s=scale: Decimal(n).scaleb(-s))


def _row_strategy(rec: Item, hints: dict[str, list]):
    parts = {i: _leaf_strategy(lf.item, hints.get(lf.item.name, [])) for i, lf in enumerate(leaves(rec)) if lf.name != "FILLER"}
    return st.fixed_dictionaries(parts)


def _case_strategy(model: ProgramModel, hints: dict[str, list]):
    files = {f.name: st.lists(_row_strategy(f.record, hints), min_size=1, max_size=MAX_RECORDS) for f in model.inputs if f.record is not None}
    return st.tuples(st.fixed_dictionaries(files), st.integers(0, 2**31), st.integers(1, 4))


def _stdin(model: ProgramModel, hints: dict[str, list], seed: int, rounds: int) -> list[str]:
    return console_lines(model, hints, random.Random(seed), rounds) if model.accepts else []


class _Runner:
    def __init__(self, exe, model: ProgramModel, impl):
        self.exe, self.model, self.impl, self.runs = exe, model, impl, 0

    def diffs(self, rows: dict, stdin: list[str]) -> tuple[Case, list[Diff]]:
        self.runs += 1
        case = build_case(self.model, rows, stdin)
        found, _ = compare(self.model, run_cobol(self.exe, self.model, case), run_python(self.impl, case))
        return case, found


def _plain(it: Item):
    return "" if it.kind == "alpha" else Decimal(0)


def shrink(runner: _Runner, rows: dict, stdin: list[str], budget: int = SHRINK_BUDGET) -> tuple[Case, list[Diff]]:
    """Make a failing case smaller and plainer within a fixed budget of COBOL runs."""
    start = runner.runs
    best_case, best = runner.diffs(rows, stdin)
    if not best:
        return best_case, best

    def attempt(r, s) -> bool:
        nonlocal rows, stdin, best_case, best
        if runner.runs - start >= budget:
            return False
        case, found = runner.diffs(r, s)
        if found:
            rows, stdin, best_case, best = r, s, case, found
            return True
        return False

    for name in list(rows):  # fewer records: halves first, then one at a time
        while len(rows[name]) > 1 and attempt({**rows, name: rows[name][: len(rows[name]) // 2]}, stdin):
            pass
        i = 0
        while i < len(rows[name]) and len(rows[name]) > 1:
            if not attempt({**rows, name: rows[name][:i] + rows[name][i + 1:]}, stdin):
                i += 1
    i = len(stdin) - 1
    while i >= 0:  # fewer console lines
        attempt(rows, stdin[:i] + stdin[i + 1:])
        i -= 1
    for f in runner.model.inputs:  # plainer values
        if f.name not in rows:
            continue
        lv = leaves(f.record)
        for r_i in range(len(rows[f.name])):
            for k, lf in enumerate(lv):
                cur = rows[f.name][r_i].get(k)
                plain = _plain(lf.item)
                if cur is None or cur == plain:
                    continue
                new_row = dict(rows[f.name][r_i])
                new_row[k] = plain
                attempt({**rows, f.name: rows[f.name][:r_i] + [new_row] + rows[f.name][r_i + 1:]}, stdin)
    return best_case, best


def describe_case(model: ProgramModel, case: Case) -> dict:
    inputs = {}
    for f in model.inputs:
        if f.assign in case.records:
            inputs[f.assign] = [show(r) for r in case.records[f.assign]]
    return {"inputs": inputs, "stdin": list(case.stdin)}


def random_check(program: str, impl, model: ProgramModel, rounds: int) -> tuple[int, dict | None]:
    from .hints import value_hints

    if not model.inputs and not model.accepts:
        return 0, None  # the program reads nothing, so every run is the same as the saved one
    exe = compile_legacy(program)
    hints = value_hints(model)
    runner = _Runner(exe, model, impl)
    state: dict = {"failure": None}

    # Hypothesis only generates here. Its own shrinker would rerun the COBOL thousands of times,
    # so the bounded shrinker above simplifies the first failure instead.
    @settings(max_examples=rounds, deadline=None, database=None, suppress_health_check=list(HealthCheck), phases=[Phase.generate])
    @given(_case_strategy(model, hints))
    def check(drawn):
        if state["failure"] is not None:
            return
        rows, seed, n = drawn
        stdin = _stdin(model, hints, seed, n)
        _, found = runner.diffs(rows, stdin)
        if found:
            state["failure"] = (rows, stdin)

    check()
    runs = runner.runs
    if state["failure"] is None:
        return runs, None
    case, found = shrink(runner, *state["failure"])
    return runs, {**describe_case(model, case), "diffs": [d.to_dict() for d in found[:SHOWN_DIFFS]], "shrink_runs": runner.runs - runs}


# ---------------------------------------------------------------- the whole check

def verify(program: str, implementation: str | None = None, rounds: int = 40) -> Report:
    implementation = implementation or f"migrated.{program}"
    impl = load_implementation(implementation)
    model = get_model(program)
    report = Report(program, implementation)
    report.sets, report.diffs = replay_sets(program, impl, model)
    if not report.sets:
        raise ValueError(f"No saved test sets for {program!r}. Run: python -m seance record {program}")
    report.random_runs, report.random_failure = random_check(program, impl, model, rounds)
    for s in report.sets:
        if s["differing"]:
            report.review.append(f"{s['label']}: {s['differing']} of {s['compared']} output lines differ")
        if s["python_error"]:
            report.review.append(f"{s['label']}: the Python stopped with {s['python_error']}")
    if report.random_failure:
        d = report.random_failure["diffs"][0] if report.random_failure["diffs"] else None
        where = f"{d['stream']} line {d['index'] + 1}" if d and d["index"] >= 0 else "the run result"
        report.review.append(f"Random runs: a small failing case was found ({where} differs)")
    return report
