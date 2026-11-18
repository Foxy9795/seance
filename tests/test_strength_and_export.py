"""Test strength (planted bugs) and the standalone package."""

import io
import subprocess
import sys
import zipfile

import pytest

from seance.cases import load_set
from seance.export import bundle
from seance.mutate import run_mutants


def test_planted_bugs_are_caught():
    r = run_mutants("payroll", limit=6)
    assert "error" not in r, r
    assert r["total"] == 6 and r["caught"] >= 5
    assert all(m["cobol_line"] for m in r["mutants"]), "each planted bug is traced to a COBOL line"


def test_strength_needs_a_matching_python_first():
    assert "error" in run_mutants("payroll", "examples.naive.payroll_naive", limit=2)


@pytest.mark.parametrize("program", ["accounts", "add_amounts"])
def test_package_runs_without_seance(tmp_path, program):
    name, data = bundle(program)
    zipfile.ZipFile(io.BytesIO(data)).extractall(tmp_path)
    folder = tmp_path / name.removesuffix(".zip")
    case, expected, _ = load_set(program, "edges")
    for assign, content in case.files.items():
        (folder / assign).write_bytes(content)
    proc = subprocess.run([sys.executable, "run.py"], cwd=folder, input="".join(x + "\n" for x in case.stdin),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.replace("\r\n", "\n") == expected.stdout
    for assign, content in expected.outputs.items():
        assert (folder / assign).read_bytes().replace(b"\r\n", b"\n") == content.replace(b"\r\n", b"\n")
