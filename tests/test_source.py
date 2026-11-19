"""Reading COBOL source and data descriptions."""

from decimal import Decimal

import pytest

from seance.cobol_src import detect_fixed, normalize, sentences, source_fixes
from seance.layout import LayoutError, leaves, parse_entries
from sample_cobol import TEMPLATE


def entries(text):
    return [(i, s) for i, s in sentences(normalize(text, False))]


def test_template_is_fixed_format():
    assert detect_fixed(TEMPLATE["cobol"])


def test_fixed_format_drops_sequence_area_and_comments():
    text = "       IDENTIFICATION DIVISION.\n      * a comment\n       PROGRAM-ID. X.                                                   SEQ00010\n"
    lines = normalize(text)
    assert lines[1].comment and "SEQ" not in lines[2].text


def test_program_id_without_period_is_fixed_and_reported():
    text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID.    CBL0001\n       AUTHOR.        Otto.\n"
    fixed, notes = source_fixes(text, True)
    assert "PROGRAM-ID.    CBL0001." in fixed and len(notes) == 1
    assert fixed.count("\n") == text.count("\n"), "line numbers never move"
    assert source_fixes("       PROGRAM-ID. OK.\n", True)[1] == []


def test_packed_binary_occurs_and_redefines_layout():
    rec = parse_entries(entries("""01 R.
   05 R-ID     PIC X(4).
   05 R-AMT    PIC S9(7)V99 COMP-3.
   05 R-CNT    PIC 9(4) COMP.
   05 R-TAB OCCURS 3 TIMES.
      10 R-V   PIC 9(2).
   05 R-RAW    PIC X(6).
   05 R-NUM    REDEFINES R-RAW PIC 9(6).
"""))[0]
    sizes = {c.name: c.size for c in rec.children}
    assert sizes["R-AMT"] == 5 and sizes["R-CNT"] == 2
    assert rec.size == 4 + 5 + 2 + 6 + 6
    names = [lf.name for lf in leaves(rec)]
    assert names[3:6] == ["R-V(1)", "R-V(2)", "R-V(3)"] and "R-NUM" not in names


def test_condition_names_and_values():
    rec = parse_entries(entries("""01 W.
   05 W-FLAG PIC X VALUE 'N'.
      88 W-DONE VALUE 'Y'.
   05 W-RATE PIC 9V99 VALUE 1.25.
"""))[0]
    flag, rate = rec.children
    assert flag.conds[0][0] == "W-DONE" and rate.value == Decimal("1.25")


def test_bad_redefines_is_rejected():
    with pytest.raises(LayoutError):
        parse_entries(entries("01 R.\n 05 A PIC X.\n 05 B REDEFINES NOPE PIC X.\n"))
