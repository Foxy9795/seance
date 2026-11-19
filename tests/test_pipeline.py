"""The whole pipeline on the shipped examples: saved runs, random runs, shrinking, spec, MCP tools."""

import pytest

from seance import mcp_server
from seance.cases import load_set, run_python, set_names
from seance.programs import implementations, program_names
from seance.recorder import cobc_available, get_model
from seance.spec import generate_spec
from seance.translate import translate
from seance.verify import load_implementation, replay_sets, verify

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")
EXAMPLES = [p for p in program_names() if not p.startswith("zz_")]


@pytest.mark.parametrize("program", EXAMPLES)
def test_reference_python_matches_every_saved_run(program):
    model = get_model(program)
    impl = load_implementation(f"migrated.{program}")
    sets, diffs = replay_sets(program, impl, model)
    assert sets, "every example ships with saved test sets"
    assert not diffs, diffs[:2]
    assert any(s["compared"] > 0 for s in sets)


@pytest.mark.parametrize("program", EXAMPLES)
def test_translator_handles_every_statement_of_the_examples(program):
    assert translate(program).unsupported == []


@needs_cobol
def test_reference_passes_random_runs():
    report = verify("payroll", "migrated.payroll", 10)
    assert report.matched and report.random_runs == 10


@needs_cobol
def test_naive_float_draft_is_caught_and_shrunk():
    report = verify("payroll", "examples.naive.payroll_naive", 10)
    assert not report.matched
    assert sum(s["differing"] for s in report.sets) > 0
    failure = report.random_failure
    assert failure is not None
    assert len(failure["inputs"]["INPUT.DAT"]) == 1, "the shrinker reduces the case to one record"
    fields = {f["name"] for d in failure["diffs"] for f in d["fields"] if not f["same"]}
    assert fields & {"OUT-GROSS", "OUT-TAX", "OUT-NET"}


@needs_cobol
def test_python_crash_is_reported_not_raised():
    report = verify("loan", "examples.naive.loan_naive", 5)
    assert not report.matched
    assert any("ZeroDivisionError" in (s["python_error"] or "") for s in report.sets)


def test_console_program_replays_typed_input():
    case, expected, _ = load_set("add_amounts", set_names("add_amounts")[0])
    assert case.stdin and "Total Amount" in expected.stdout
    actual = run_python(load_implementation("migrated.add_amounts"), case)
    assert actual.stdout == expected.stdout


def test_packed_decimal_report_layout():
    model = get_model("account_report")
    rec = next(f for f in model.files if f.assign == "ACCTREC").record
    usages = {c.name: c.usage for c in rec.children}
    assert usages["ACCT-LIMIT"] == "packed" and rec.size == 170
    assert any("PROGRAM-ID" in n for n in model.notes), "the dialect fix is reported"


def test_spec_mentions_files_and_silent_changes():
    md = generate_spec("payroll").markdown
    assert "INPUT.DAT" in md and "Where values can silently change" in md
    assert "rounds half away from zero" in md


def test_implementations_list_roles():
    roles = {i.role for i in implementations("payroll")}
    assert roles == {"reference", "naive"}


@needs_cobol
def test_mcp_run_legacy_program_returns_every_stream():
    out = mcp_server.run_legacy_program("payroll", ["E000010451012345"])
    assert "== OUTPUT.DAT" in out and "E00001" in out and "== return code 0" in out
    out = mcp_server.run_legacy_program("add_amounts", console_input=["ANN", "1", "2", "3", "NO"])
    assert "Total Amount = 000006" in out


def test_mcp_describe_layout_lists_storage():
    text = mcp_server.describe_layout("account_report")
    assert "storage=packed" in text and "PRTLINE" in text
