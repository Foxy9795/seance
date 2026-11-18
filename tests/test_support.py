"""The COBOL features Séance reads: fixed format, groups, FILLER, level-88, sign storage, edited fields, clear errors."""

import pytest

from seance.cobol_src import detect_fixed, normalize, sentences
from seance.copybook import CopybookError, parse_copybook, parse_items
from seance.programs import TEMPLATE


def fields(text):
    return parse_copybook(text).fields


def test_fixed_vs_free_detection():
    assert detect_fixed(TEMPLATE["cobol"]) is True
    assert detect_fixed("IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n") is False


def test_fixed_format_ignores_columns_outside_the_code_area():
    src = (
        "000100 IDENTIFICATION DIVISION.                                              SEQ00010\n"
        "      * a comment line\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'ABC\n"
        "      -    'DEF'.\n"
    )
    lines = normalize(src, fixed=True)
    texts = [l.text.strip() for l in lines]
    assert "IDENTIFICATION DIVISION." in texts[0] and "SEQ00010" not in texts[0]
    assert lines[1].comment and "a comment line" in lines[1].text
    assert any("ABCDEF" in t for t in texts)  # continuation line joined


def test_sentences_respect_quotes_and_periods():
    out = sentences(normalize("       01 A.\n           05 B PIC X(3) VALUE 'A.B'.\n", fixed=True))
    assert [s for _, s in out] == ["01 A", "05 B PIC X(3) VALUE 'A.B'"]


def test_groups_filler_value_and_level_88_are_handled():
    layout = parse_copybook(
        """
        01 R-REC.
           05 R-ID          PIC X(4) VALUE SPACES.
           05 R-DATE.
              10 R-YY       PIC 99.
              10 R-MM       PIC 99.
           05 FILLER        PIC X(2).
           05 FILLER        PIC X(2).
           05 R-FLAG        PIC X.
              88 IS-ON      VALUE 'Y'.
        """
    )
    assert [f.py_name for f in layout.fields] == ["id", "yy", "mm", "filler", "filler_2", "flag"]
    assert layout.width == 4 + 2 + 2 + 2 + 2 + 1
    assert [f.offset for f in layout.fields] == [0, 4, 6, 8, 10, 12]


@pytest.mark.parametrize(
    "decl, sign, width",
    [
        ("PIC S9(5)V99", "trailing_over", 7),
        ("PIC S9(5)V99 SIGN LEADING", "leading_over", 7),
        ("PIC S9(5)V99 SIGN TRAILING SEPARATE", "trailing_sep", 8),
        ("PIC S9(5)V99 SIGN IS LEADING SEPARATE CHARACTER", "leading_sep", 8),
        ("PIC 9(5)V99", "none", 7),
    ],
)
def test_sign_storage_modes(decl, sign, width):
    (f,) = fields(f"01 R.\n   05 R-X {decl}.")
    assert (f.sign, f.width, f.digits, f.scale) == (sign, width, 7, 2)


def test_edited_picture_field():
    (f,) = fields("01 R.\n   05 R-X PIC $$,$$9.99-.")
    assert f.kind == "edited" and f.width == 10 and f.pic == "$$,$$9.99-"


@pytest.mark.parametrize(
    "decl, words",
    [
        ("PIC S9(7)V99 COMP-3", ["COMP-3", "WORKING-STORAGE"]),
        ("PIC S9(4) COMP", ["binary", "not supported"]),
        ("PIC X(3) OCCURS 5 TIMES", ["OCCURS", "Flatten"]),
        ("PIC X(3) REDEFINES OTHER", ["REDEFINES"]),
        ("PIC N(3)", ["not supported"]),
    ],
)
def test_unsupported_features_say_what_and_what_to_do(decl, words):
    with pytest.raises(CopybookError) as err:
        parse_copybook(f"01 R.\n   05 R-X {decl}.")
    for w in words:
        assert w.lower() in str(err.value).lower()


def test_real_world_comp3_record_is_explained():
    """Shape taken from the IBM-style course program CBL0001 (packed balances in the account record)."""
    with pytest.raises(CopybookError, match="COMP-3"):
        parse_items(sentences(normalize("""
       01  ACCT-FIELDS.
           05  ACCT-NO            PIC X(8).
           05  ACCT-LIMIT         PIC S9(7)V99 COMP-3.
           05  CLIENT-ADDR.
               10  STREET-ADDR    PIC X(25).
""", fixed=True)))

