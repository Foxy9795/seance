"""Verify a Python migration against the recorded behavior of the legacy program."""

from __future__ import annotations

import importlib
import sys
import string
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from .cobol_num import edited_digits, edited_has_sign, format_alpha, format_edited, format_numeric
from .copybook import Layout
from .recorder import ROOT, compile_legacy, get_model, run_legacy


@dataclass
class Mismatch:
    source: str  # fixture name or "property"
    index: int
    input: str
    expected: str
    actual: str
    field: str  # first differing field, or "record count"


@dataclass
class Report:
    program: str
    implementation: str
    fixtures: dict[str, dict] = field(default_factory=dict)  # name -> {records, mismatches}
    property_runs: int = 0
    property_mismatch: Mismatch | None = None
    mismatches: list[Mismatch] = field(default_factory=list)
    review: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return not self.mismatches and self.property_mismatch is None


def _fresh(name: str):
    """Import `name` from disk every time, so edits made since the last run are picked up."""
    for loaded in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[loaded]
    importlib.invalidate_caches()
    return importlib.import_module(name)


def _modules(program: str, implementation: str):
    records = _fresh(f"generated.{program}_records")
    impl = _fresh(implementation)
    return records, impl


def run_python(records, impl, lines: list[str]) -> list[str]:
    """Run the migration on one input file. Translated code keeps WORKING-STORAGE between records, so reset first."""
    reset = getattr(impl, "reset", None)
    if callable(reset):
        try:
            reset()
        except Exception as exc:  # start-up code failed: every record fails with the same reason
            return [f"<{type(exc).__name__}: {exc}>" for _ in lines]
    out = []
    for line in lines:
        try:
            out.append(impl.transform(records.InRecord.parse(line)).format())
        except Exception as exc:  # a crash is a mismatch, not a reason to stop
            out.append(f"<{type(exc).__name__}: {exc}>")
    return out


def first_diff_field(layout: Layout, expected: str, actual: str) -> str:
    if actual.startswith("<") and actual.endswith(">"):
        return "(migrated code raised an exception)"
    e, a = expected.ljust(layout.width), actual.ljust(layout.width)
    for f, lo, hi in layout.slices():
        if e[lo:hi] != a[lo:hi]:
            return f.name
    return "unknown"


def compare(source: str, layout: Layout, inputs, expected, actual) -> list[Mismatch]:
    if len(expected) != len(actual):
        return [Mismatch(source, -1, "", f"{len(expected)} records", f"{len(actual)} records", "record count")]
    found = []
    for i, (inp, e, a) in enumerate(zip(inputs, expected, actual)):
        if e != a:
            found.append(Mismatch(source, i, inp, e, a, first_diff_field(layout, e, a)))
    return found


def replay_fixtures(program: str, records, impl, out_layout: Layout, root: Path = ROOT):
    from .testdata import labels

    names = labels(program, root)
    results, all_mismatches = {}, []
    for in_file in sorted((root / "fixtures" / program).glob("*.in")):
        name = in_file.stem
        inputs = in_file.read_text(encoding="ascii").splitlines()
        expected = (in_file.with_suffix(".out")).read_text(encoding="ascii").splitlines()
        actual = run_python(records, impl, inputs)
        found = compare(name, out_layout, inputs, expected, actual)
        results[name] = {"records": len(inputs), "mismatches": len(found), "label": names.get(name, name)}
        all_mismatches += found
    return results, all_mismatches


def record_strategy(layout: Layout, hints: dict[str, list] | None = None):
    """Hypothesis strategy producing one valid input line for `layout`."""
    hints = hints or {}
    parts = []
    for f in layout.fields:
        if f.kind == "alpha":
            text = st.text(alphabet=string.printable[:-5], min_size=0, max_size=f.width)
            if hints.get(f.name):
                text = st.one_of(st.sampled_from([str(h) for h in hints[f.name]]), text)
            parts.append(text.map(lambda s, w=f.width: format_alpha(s, w)))
            continue
        if f.kind == "edited":
            ints, decs = edited_digits(f.pic)
            digits, scale, signed = ints + decs, decs, edited_has_sign(f.pic)
            render = lambda v, f=f: format_edited(v, f.pic).ljust(f.width)[: f.width]
        else:
            digits, scale, signed = f.digits, f.scale, f.signed
            render = lambda v, f=f: format_numeric(v, f.digits, f.scale, f.signed, f.sign)
        top = 10**digits - 1
        low = -top if signed else 0
        interesting = [0, 1, top, top - 1] + ([-1, -top] if signed else [])
        interesting += [int(h.scaleb(scale)) for h in hints.get(f.name, []) if isinstance(h, Decimal)]
        small = min(top, 10**3)
        parts.append(
            st.one_of(
                st.sampled_from(interesting),
                st.integers(-small if signed else 0, small),
                st.integers(low, top),
            ).map(lambda n, s=scale, r=render: r(Decimal(n).scaleb(-s)))
        )
    return st.tuples(*parts).map("".join).map(str.rstrip)


SHRINK_BUDGET = 80  # COBOL runs spent making a failing input simpler


def _simpler_values(f) -> list[str]:
    """Simpler texts for one input field, simplest first."""
    if f.kind == "alpha":
        return [" " * f.width, "A".ljust(f.width)]
    if f.kind == "edited":
        return [format_edited(Decimal(0), f.pic).ljust(f.width)[: f.width]]
    return [format_numeric(Decimal(0), f.digits, f.scale, f.signed, f.sign), format_numeric(Decimal(1).scaleb(-f.scale), f.digits, f.scale, f.signed, f.sign)]


def shrink(exe, model, records, impl, out_layout, lines: list[str], index: int, budget: int = SHRINK_BUDGET):
    """Make a failing batch smaller and simpler, with a fixed budget of COBOL runs. Returns (lines, mismatch)."""
    runs = 0

    def failing(batch: list[str]):
        nonlocal runs
        runs += 1
        found = compare("property", out_layout, batch, run_legacy(exe, batch, model), run_python(records, impl, batch))
        return found[0] if found else None

    best_lines = lines[: index + 1]
    best = failing(best_lines)
    if best is None:
        return None
    single = failing([best_lines[-1]])
    if single is not None:
        best_lines, best = [best_lines[-1]], single
    in_layout = model.in_layout
    changed = True
    while changed and runs < budget:
        changed = False
        target = best_lines[-1].ljust(in_layout.width)
        for f, lo, hi in in_layout.slices():
            for simple in _simpler_values(f):
                if runs >= budget:
                    break
                if target[lo:hi] == simple:
                    break
                candidate = (target[:lo] + simple + target[hi:]).rstrip()
                result = failing(best_lines[:-1] + [candidate])
                if result is not None:
                    best_lines, best, target, changed = best_lines[:-1] + [candidate], result, candidate.ljust(in_layout.width), True
                    break
    if len(best_lines) > 1:
        best.index = len(best_lines) - 1
    return best


def property_check(program: str, records, impl, in_layout, out_layout, examples: int = 100):
    from hypothesis import Phase

    from .hints import value_hints

    exe = compile_legacy(program)
    model = get_model(program)
    hints = value_hints(model)
    state = {"runs": 0, "failure": None, "lines": None}

    # Hypothesis only generates here. Its own shrinker would call the COBOL program thousands of times,
    # so a bounded shrinker below simplifies the first failure instead.
    @settings(max_examples=examples, deadline=None, database=None, suppress_health_check=list(HealthCheck),
              phases=[Phase.explicit, Phase.generate])
    @given(st.lists(record_strategy(in_layout, hints), min_size=1, max_size=25))
    def check(lines):
        if state["failure"] is not None:
            return
        state["runs"] += 1
        expected = run_legacy(exe, lines, model)
        actual = run_python(records, impl, lines)
        found = compare("property", out_layout, lines, expected, actual)
        if found:
            state["failure"], state["lines"] = found[0], lines

    check()
    if state["failure"] is not None:
        first = state["failure"]
        shrunk = shrink(exe, model, records, impl, out_layout, state["lines"], max(first.index, 0))
        state["failure"] = shrunk or first
    return state["runs"], state["failure"]


def verify(program: str, implementation: str | None = None, examples: int = 100) -> Report:
    implementation = implementation or f"migrated.{program}"
    records, impl = _modules(program, implementation)
    model = get_model(program)
    in_layout, out_layout = model.in_layout, model.out_layout
    report = Report(program, implementation)
    report.fixtures, report.mismatches = replay_fixtures(program, records, impl, out_layout)
    if not report.fixtures or sum(f["records"] for f in report.fixtures.values()) == 0:
        raise ValueError(f"No recorded fixtures for {program!r}. Run: python -m seance record {program}")
    report.property_runs, report.property_mismatch = property_check(program, records, impl, in_layout, out_layout, examples)
    for m in report.mismatches[:20]:
        report.review.append(f"{m.source} record {m.index}: field {m.field} differs")
    if report.property_mismatch:
        m = report.property_mismatch
        report.review.append(f"property test: field {m.field} differs on a minimal input")
    return report



