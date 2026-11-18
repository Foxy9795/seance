"""The translator: every shipped program drafts to Python that matches the recorded COBOL behavior."""

import importlib
import shutil
import sys
from pathlib import Path

import pytest

from seance.hints import value_hints
from seance.recorder import ROOT, get_model
from seance.translate import tokenize_lines, translate
from seance.cobol_src import normalize
from seance.verify import _modules, replay_fixtures

PROGRAMS = ["accounts", "payroll", "interest", "inventory", "loan"]


@pytest.fixture(scope="module")
def drafts(tmp_path_factory):
    folder = tmp_path_factory.mktemp("drafts")
    pkg = folder / "drafts_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").touch()
    sys.path.insert(0, str(folder))
    yield pkg
    sys.path.remove(str(folder))


@pytest.mark.parametrize("program", PROGRAMS)
def test_draft_matches_every_recorded_record(program, drafts):
    tr = translate(program)
    assert tr.unsupported == [], tr.unsupported
    (drafts / f"{program}.py").write_text(tr.code, encoding="utf-8")
    records, impl = _modules(program, f"drafts_pkg.{program}")
    results, mismatches = replay_fixtures(program, records, impl, get_model(program).out_layout)
    assert sum(r["records"] for r in results.values()) > 300
    assert mismatches == [], mismatches[:2]


def test_every_line_is_tagged_with_its_own_cobol_line():
    code = translate("loan").code
    assert "# L32" in code and "# L41" in code and "# L53" in code  # MOVE, the long COMPUTE, WRITE


def test_paragraph_names_that_start_with_digits():
    toks = tokenize_lines(normalize("       0000-MAIN.\n           PERFORM 8000-READ.\n", fixed=True))
    assert [t.value for t in toks if t.kind == "word"] == ["0000-MAIN", "PERFORM", "8000-READ"]


def test_untranslatable_statements_fail_loudly_at_their_line(tmp_path):
    """GO TO and STRING are not translated: the draft says so, names the line, and raises there."""
    src = ROOT / "legacy" / "payroll"
    root = tmp_path
    for d in ("legacy", "generated", "fixtures"):
        (root / d).mkdir()
    shutil.copytree(src, root / "legacy" / "payroll")
    cbl = root / "legacy" / "payroll" / "payroll.cbl"
    text = cbl.read_text(encoding="utf-8").replace(
        "    MOVE IN-EMP-ID TO OUT-EMP-ID", '    MOVE IN-EMP-ID TO OUT-EMP-ID\n    STRING "A" "B" DELIMITED BY SIZE INTO OUT-EMP-ID'
    )
    cbl.write_text(text, encoding="utf-8")
    tr = translate("payroll", root)
    assert len(tr.unsupported) == 1 and "STRING" in tr.unsupported[0]["text"]
    line = tr.unsupported[0]["line"]
    assert f'S.unsupported("line {line}:' in tr.code
    compile(tr.code, "draft.py", "exec")  # a draft with gaps still loads


def test_value_hints_come_from_the_code():
    acc = value_hints(get_model("accounts"))
    assert {"S", "C"} <= set(acc["ACCT-TYPE"])  # level-88 values
    assert {str(v) for v in acc["ACCT-BALANCE"]} >= {"2500", "2499.99", "500.01"}  # literals compared via MOVE ... TO WS-BAL
    assert {str(v) for v in value_hints(get_model("payroll"))["IN-HOURS"]} >= {"39.9", "40", "40.1"}
