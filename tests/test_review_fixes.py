"""Fixes for the findings in review/REPORT.md. Each test fails on the code as it was reviewed."""
import importlib.util
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seance.api import app
from seance.cases import Result, _units, compare, text_only
from seance.export import TEST_SUITE, bundle
from seance.recorder import get_model
from seance.report import source_sha
from seance.rt import _alpha_to_number

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stress_translate.py"
_spec = importlib.util.spec_from_file_location("stress_translate", SCRIPT)
stress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stress)

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. prog.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"


def _matches_gnucobol(tmp_path, source: str):
    src = tmp_path / "prog.cob"
    src.write_text(source, encoding="utf-8")
    result = stress.run_one(src, "rv", tmp_path)
    assert result["stage"] == "match", result


# ---- F2.1 / F3.1 / F8.1: two programs that both stop with an error

def test_a_python_crash_is_not_the_same_as_the_cobol_stopping():
    model = get_model("payroll")
    cobol = Result(error="file does not exist", return_code=1)
    assert compare(model, cobol, Result(error="ZeroDivisionError: division by zero", return_code=1))[0], "a Python crash must be a difference"
    assert compare(model, cobol, Result(error="NotImplementedError: could not translate line 4", return_code=1))[0]
    assert not compare(model, cobol, Result(error="CobolError: OPEN INPUT IN-FILE: file IN-FILE does not exist", return_code=1))[0], \
        "the runtime's own CobolError stands for a libcob error"


# ---- F2.2: binary and packed records are not print files

def test_a_line_feed_byte_in_a_packed_record_is_data():
    f = next(x for x in get_model("account_report").all_files if x.assign == "ACCTREC")
    assert not text_only(f), "ACCTREC has packed fields"
    data = bytes(range(f.size)) * 2  # two records; byte 10 (a line feed) is inside each
    assert b"\n" in data and len(_units(f, data)) == 2


def test_a_print_file_still_splits_at_its_line_and_page_breaks():
    f = next(x for x in get_model("payroll").all_files if x.assign == "OUTPUT.DAT")
    assert text_only(f)


def test_the_exported_suite_is_strict_and_keeps_binary_records_whole():
    assert "pytest.raises(CobolError)" in TEST_SUITE and "pytest.raises(Exception)" not in TEST_SUITE
    assert "if assign in PRINT_FILES and" in TEST_SUITE


@pytest.mark.parametrize("program", ["payroll", "account_report"])
def test_the_exported_suite_passes_on_its_own(tmp_path, program):
    name, data = bundle(program)
    zipfile.ZipFile(io.BytesIO(data)).extractall(tmp_path)
    folder = tmp_path / name.removesuffix(".zip")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=folder, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-500:]


# ---- F1.1: UNSTRING with a pointer outside the sending item

def test_unstring_pointer_outside_the_item_overflows(tmp_path):
    _matches_gnucobol(tmp_path, HEAD + """       01  SRC PIC X(10) VALUE "HELLO WORL".
       01  T1  PIC X(5).
       01  T2  PIC X(5).
       01  PTR PIC 99.
       01  OVR PIC X.
       PROCEDURE DIVISION.
       MAIN.
           MOVE 0 TO PTR. PERFORM RUN-ONE.
           MOVE 1 TO PTR. PERFORM RUN-ONE.
           MOVE 6 TO PTR. PERFORM RUN-ONE.
           MOVE 10 TO PTR. PERFORM RUN-ONE.
           MOVE 11 TO PTR. PERFORM RUN-ONE.
           MOVE 99 TO PTR. PERFORM RUN-ONE.
           STOP RUN.
       RUN-ONE.
           MOVE "11111" TO T1. MOVE "22222" TO T2. MOVE "N" TO OVR.
           UNSTRING SRC DELIMITED BY SPACE INTO T1 T2 WITH POINTER PTR
               ON OVERFLOW MOVE "Y" TO OVR
           END-UNSTRING.
           DISPLAY "T1=" T1 " T2=" T2 " PTR=" PTR " OVER=" OVR.
""")


# ---- F1.2: text with a sign or a decimal point moved to a number

def test_text_to_number_follows_libcob(tmp_path):
    _matches_gnucobol(tmp_path, HEAD + """       01  S1 PIC X(6) VALUE "-123  ".
       01  S2 PIC X(6) VALUE "+45   ".
       01  S3 PIC X(6) VALUE " 12.5 ".
       01  S4 PIC X(6) VALUE "12-   ".
       01  S5 PIC X(6) VALUE "1 2   ".
       01  S6 PIC X(6) VALUE "abc   ".
       01  S7 PIC X(6) VALUE "  7   ".
       01  S8 PIC X(6) VALUE "-.5   ".
       01  S9 PIC X(6) VALUE "-12.34".
       01  S10 PIC X(6) VALUE "12abc ".
       01  N1 PIC S9(5)V9.
       01  N2 PIC 9(5)V9.
       PROCEDURE DIVISION.
           MOVE S1 TO N1 N2. DISPLAY "1:" N1 " " N2.
           MOVE S2 TO N1 N2. DISPLAY "2:" N1 " " N2.
           MOVE S3 TO N1 N2. DISPLAY "3:" N1 " " N2.
           MOVE S4 TO N1 N2. DISPLAY "4:" N1 " " N2.
           MOVE S5 TO N1 N2. DISPLAY "5:" N1 " " N2.
           MOVE S6 TO N1 N2. DISPLAY "6:" N1 " " N2.
           MOVE S7 TO N1 N2. DISPLAY "7:" N1 " " N2.
           MOVE S8 TO N1 N2. DISPLAY "8:" N1 " " N2.
           MOVE S9 TO N1 N2. DISPLAY "9:" N1 " " N2.
           MOVE S10 TO N1 N2. DISPLAY "10:" N1 " " N2.
           STOP RUN.
""")


def test_text_to_number_unit():
    assert str(_alpha_to_number("-123 ")) == "-123.0" and str(_alpha_to_number("12-")) == "0" and str(_alpha_to_number("1 2")) == "12.0"


# ---- F1.3: INSPECT on a signed DISPLAY number works on its storage

def test_inspect_on_signed_numbers_keeps_the_sign(tmp_path):
    _matches_gnucobol(tmp_path, HEAD + """       01  N   PIC S9(5) SIGN LEADING SEPARATE VALUE -12045.
       01  M   PIC S9(5) VALUE -12045.
       01  K   PIC 9(5) VALUE 12045.
       01  CNT PIC 99 VALUE 0.
       PROCEDURE DIVISION.
           INSPECT N REPLACING ALL "0" BY "9". DISPLAY "N=" N.
           INSPECT M REPLACING ALL "4" BY "9". DISPLAY "M=" M.
           INSPECT M TALLYING CNT FOR ALL "1". DISPLAY "CNT=" CNT.
           INSPECT K CONVERTING "012" TO "987". DISPLAY "K=" K.
           STOP RUN.
""")


# ---- F1.4: DIVIDE ... REMAINDER needs GIVING

def test_divide_remainder_without_giving_is_reported(tmp_path):
    (tmp_path / "legacy" / "dv").mkdir(parents=True)
    (tmp_path / "legacy" / "dv" / "dv.cbl").write_text(HEAD + """       01  A PIC 99 VALUE 7.
       01  B PIC 99 VALUE 20.
       01  R PIC 99.
       PROCEDURE DIVISION.
           DIVIDE A INTO B REMAINDER R.
           STOP RUN.
""", encoding="utf-8")
    from seance.translate import translate

    tr = translate("dv", tmp_path)
    assert any("REMAINDER needs GIVING" in g["why"] for g in tr.unsupported), tr.unsupported


# ---- F2.3: the receipt covers copybooks and called programs

def test_the_receipt_changes_when_a_copybook_changes(tmp_path):
    base = tmp_path / "legacy" / "p"
    base.mkdir(parents=True)
    (base / "p.cbl").write_text("main", encoding="utf-8")
    alone = source_sha("p", tmp_path)
    import hashlib

    assert alone == hashlib.sha256(b"main").hexdigest()[:16], "a one-file program keeps the plain hash of its file"
    (base / "REC.cpy").write_text("01 A PIC X.", encoding="utf-8")
    with_copy = source_sha("p", tmp_path)
    (base / "REC.cpy").write_text("01 A PIC X(2).", encoding="utf-8")
    assert len({alone, with_copy, source_sha("p", tmp_path)}) == 3


# ---- F4.1: the IPv6 loopback address is accepted, other hosts are not

def test_ipv6_loopback_is_accepted():
    assert TestClient(app, base_url="http://[::1]:8000").get("/api/about").status_code == 200
    assert TestClient(app, base_url="http://127.0.0.1:8000").get("/api/about").status_code == 200
    assert TestClient(app, base_url="http://evil.example").get("/api/about").status_code == 400
    assert TestClient(app, base_url="http://127.0.0.1.evil.example").get("/api/about").status_code == 400


# the page knows which build it is, so an old tab can tell it is out of date

def test_the_page_carries_the_build_the_server_reports():
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    build = c.get("/api/about").json()["build"]
    assert len(build) == 10 and f"const BUILD = '{build}';" in c.get("/").text
