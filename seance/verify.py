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
    results, all_mismatches = {}, []
    for in_file in sorted((root / "fixtures" / program).glob("*.in")):
        name = in_file.stem
        inputs = in_file.read_text(encoding="ascii").splitlines()
        expected = (in_file.with_suffix(".out")).read_text(encoding="ascii").splitlines()
        actual = run_python(records, impl, inputs)
        found = compare(name, out_layout, inputs, expected, actual)
        results[name] = {"records": len(inputs), "mismatches": len(found)}
        all_mismatches += found
    return results, all_mismatches


def record_strategy(layout: Layout):
    """Hypothesis strategy producing one valid input line for `layout`."""
    parts = []
    for f in layout.fields:
        if f.kind == "alpha":
            parts.append(st.text(alphabet=string.printable[:-5], min_size=0, max_size=f.width).map(lambda s, w=f.width: format_alpha(s, w)))
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
        small = min(top, 10**3)
        parts.append(
            st.one_of(
                st.sampled_from(interesting),
                st.integers(-small if signed else 0, small),
                st.integers(low, top),
            ).map(lambda n, s=scale, r=render: r(Decimal(n).scaleb(-s)))
        )
    return st.tuples(*parts).map("".join).map(str.rstrip)


def property_check(program: str, records, impl, in_layout, out_layout, examples: int = 100):
    exe = compile_legacy(program)
    model = get_model(program)
    state = {"runs": 0, "failure": None}

    @settings(max_examples=examples, deadline=None, database=None, suppress_health_check=list(HealthCheck))
    @given(st.lists(record_strategy(in_layout), min_size=1, max_size=25))
    def check(lines):
        state["runs"] += 1
        expected = run_legacy(exe, lines, model)
        actual = run_python(records, impl, lines)
        found = compare("property", out_layout, lines, expected, actual)
        if found:
            state["failure"] = found[0]
            raise AssertionError("migration differs from legacy")

    try:
        check()
    except AssertionError:
        pass
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



