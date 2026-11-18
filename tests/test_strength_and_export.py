"""Test strength (planted bugs) and the standalone export."""

import io
import subprocess
import sys
import zipfile

import pytest

from seance.export import bundle
from seance.mutate import run_mutants
from seance.recorder import ROOT, get_model


def test_planted_bugs_are_caught_and_survivors_point_at_cobol_lines():
    r = run_mutants("accounts")
    assert r["total"] >= 10
    assert r["caught"] >= r["total"] - 1
    survivors = [m for m in r["mutants"] if not m["caught"]]
    # the only survivor is the record counter, which never reaches the output file
    assert all(m["cobol_line"] == 43 for m in survivors), survivors
    assert all(m["cobol_line"] for m in r["mutants"])  # every planted bug is traced to a COBOL line


def test_a_planted_bug_that_makes_a_loop_endless_counts_as_caught():
    r = run_mutants("accounts")
    hang = [m for m in r["mutants"] if "made the program hang" in m["change"]]
    assert hang and all(m["caught"] for m in hang)


def test_test_strength_refuses_a_python_that_does_not_match():
    r = run_mutants("payroll", "examples.naive.payroll_naive")
    assert "error" in r


@pytest.mark.parametrize("program", ["accounts", "loan"])
def test_export_runs_standalone_and_reproduces_the_cobol(program, tmp_path):
    model = get_model(program)
    name, data = bundle(program)
    zipfile.ZipFile(io.BytesIO(data)).extractall(tmp_path)
    folder = tmp_path / name[:-4]
    lines = (ROOT / "fixtures" / program / "random.in").read_text(encoding="latin-1").splitlines()
    payload = "".join(l + "\n" for l in lines) if model.input.organization == "line" else "".join(l.ljust(model.in_layout.width) for l in lines)
    (folder / "in.dat").write_bytes(payload.encode("latin-1"))
    # -I: isolated mode, so nothing from this repository or its virtualenv can leak in
    r = subprocess.run([sys.executable, "-I", "run.py", "in.dat", "out.dat"], cwd=folder, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    produced = (folder / "out.dat").read_bytes().decode("latin-1")
    if model.output.organization == "line":
        got = [l.rstrip() for l in produced.split("\n")[:-1]]
    else:
        w = model.out_layout.width
        got = [produced[i:i + w].rstrip() for i in range(0, len(produced), w)]
    assert got == (ROOT / "fixtures" / program / "random.out").read_text(encoding="latin-1").splitlines()

