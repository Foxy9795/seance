"""Gap filling: find inputs that tell a planted bug from the original, and say plainly when none can."""
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from seance.cases import load_set, set_names
from seance.gapfill import Coord, annotate, case_of, fill_gaps, save_verdicts, state_of
from seance.mutate import run_mutants
from seance.recorder import ROOT, get_model

MIGRATED = ROOT / "migrated"


def _cleanup(program: str) -> None:
    for name in set_names(program):
        if name.startswith("gap-"):
            shutil.rmtree(ROOT / "fixtures" / program / name)
    (ROOT / "fixtures" / program / "gapfill.json").unlink(missing_ok=True)


@pytest.fixture
def clean_payroll():
    _cleanup("payroll")
    yield
    _cleanup("payroll")


def test_saved_records_survive_a_round_trip():
    """The search edits records as field values, so every saved set must encode back to the same bytes."""
    model = get_model("payroll")
    for name in set_names("payroll"):
        case, _, _ = load_set("payroll", name)
        st = state_of(model, case)
        if case.files:
            assert st.rows, f"{name}: records were not parsed"
            assert case_of(model, st).files == case.files, f"{name}: records changed on the way through"


def test_numeric_moves_stay_inside_the_picture():
    c = Coord("row", "IN-FILE", 0, 0, digits=5, scale=2, signed=False)
    seen = list(c.moves(Decimal("10.00")))
    assert Decimal("10.01") in seen and Decimal("11.00") in seen and Decimal("9.99") in seen
    assert all(Decimal(0) <= v <= Decimal("999.99") for v in seen)
    assert c.clamp(Decimal("5000")) == Decimal("999.99") and c.clamp(Decimal("-3")) == 0


def test_payroll_gap_is_closed_and_the_equivalent_change_is_named(clean_payroll):
    before = run_mutants("payroll")
    survivors = [m for m in before["mutants"] if not m["caught"]]
    assert {m["change"] for m in survivors} == {"comparison <= changed to <", "constant 1500 changed to 1501"}

    r = fill_gaps("payroll")
    assert "error" not in r, r
    status = {x["change"]: x for x in r["results"]}
    gap = status["constant 1500 changed to 1501"]
    assert gap["status"] == "closed" and gap["set"] in set_names("payroll")
    assert gap["difference"]["expected"] != gap["difference"]["actual"]
    edge = status["comparison <= changed to <"]
    assert edge["status"] == "equivalent" and edge["flips"] >= 4, "the edge must have been reached more than once"
    assert r["after"]["caught"] == r["before"]["caught"] + 1 and r["after"]["equivalent"] == 1

    again = run_mutants("payroll")  # the saved set now catches the first; the verdict is remembered for the second
    assert again["caught"] == again["total"] - 1
    assert [m["verdict"] for m in again["mutants"] if not m["caught"]] == ["equivalent"]
    case, expected, meta = load_set("payroll", gap["set"])
    assert meta["label"].startswith("Gap filler") and expected.outputs, "the new set carries the COBOL's own answer"


def test_a_verdict_is_dropped_when_the_python_changes(clean_payroll):
    source = (MIGRATED / "payroll.py").read_text(encoding="utf-8-sig")
    save_verdicts("payroll", source, [{"kind": "cmp", "line": 76, "before": "<=", "after": "<", "status": "equivalent", "note": "x"}])
    mutants = [{"kind": "cmp", "line": 76, "before": "<=", "after": "<", "caught": False}]
    assert annotate("payroll", source, mutants) == 1 and mutants[0]["verdict"] == "equivalent"
    stale = [{"kind": "cmp", "line": 76, "before": "<=", "after": "<", "caught": False}]
    assert annotate("payroll", source + "\n# edited\n", stale) == 0 and "verdict" not in stale[0]
    data = json.loads((ROOT / "fixtures" / "payroll" / "gapfill.json").read_text(encoding="utf-8"))
    assert data["verdicts"][0]["status"] == "equivalent"


def test_a_real_bug_the_saved_records_missed_is_reported_not_saved(clean_payroll):
    """A Python that is wrong only for gross pay in (1500, 1509]. The saved records never land there, so the check
    passes. The gap filler's changed copy (1509 -> 1500, the planted bug raises the last digit) happens to match the
    COBOL, so the input it finds is one where the COBOL and the original Python disagree: that is a bug, and it
    must not be saved as a passing test."""
    text = (MIGRATED / "payroll.py").read_text(encoding="utf-8-sig")
    assert text.count('D("1500")') >= 2
    head, _, tail = text.partition('elif (S.cmp(S.r("WS-GROSS"), "<=", D("1500")))')
    assert tail, "payroll.py no longer has the bracket test this test plants a bug in"
    target = MIGRATED / "_gapfill_off_by_one.py"
    target.write_text(head + 'elif (S.cmp(S.r("WS-GROSS"), "<=", D("1509")))' + tail, encoding="utf-8")
    try:
        r = fill_gaps("payroll", "migrated._gapfill_off_by_one", limit=60)
        assert "error" not in r, r
        bad = [x for x in r["results"] if x["status"] == "mismatch"]
        assert bad, [(x["change"], x["status"]) for x in r["results"]]
        assert bad[0]["diffs"], "the report shows where the COBOL and the Python differ"
        assert not [n for n in set_names("payroll") if n.startswith("gap-")] or all(x["status"] != "mismatch" or "set" not in x for x in bad)
    finally:
        target.unlink(missing_ok=True)


def test_sql_and_cics_programs_are_refused_with_a_reason():
    r = fill_gaps("payment_posting")
    assert "error" in r and "SQL" in r["error"]
