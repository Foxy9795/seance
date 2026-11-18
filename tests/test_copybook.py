import pytest

from seance.copybook import CopybookError, parse_copybook

GOOD = """
01 IN-REC.
   05 IN-ID   PIC X(4).
   05 IN-AMT  PIC S9(3)V99 SIGN LEADING SEPARATE.
   05 IN-QTY  PIC 9(2).
"""


def test_layout_offsets_and_names():
    layout = parse_copybook(GOOD)
    assert [f.py_name for f in layout.fields] == ["id", "amt", "qty"]
    assert [(f.offset, f.width) for f in layout.fields] == [(0, 4), (4, 6), (10, 2)]
    assert layout.width == 12


def test_unsupported_clause_is_reported():
    with pytest.raises(CopybookError, match="COMP-3"):
        parse_copybook("01 R.\n 05 R-X PIC S9(5) COMP-3.")


def test_signed_without_separate_sign_uses_the_cobol_default():
    (f,) = parse_copybook("01 R-REC.\n 05 R-X PIC S9(5).").fields
    assert f.sign == "trailing_over" and f.width == 5

