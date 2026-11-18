from decimal import Decimal as D

from hypothesis import given, strategies as st

from seance.cobol_num import format_numeric, parse_numeric, store


def test_rounded_is_half_away_from_zero():
    assert store(D("0.075"), 4, 2, rounded=True) == D("0.08")
    assert store(D("-0.075"), 4, 2, rounded=True) == D("-0.08")


def test_unrounded_truncates():
    assert store(D("0.079"), 4, 2) == D("0.07")


def test_high_order_digits_are_dropped():
    assert store(D("123456.78"), 7, 2, signed=False) == D("23456.78")


def test_move_keeps_the_sign_of_a_value_that_truncates_to_zero():
    """Measured against GnuCOBOL: MOVE -0.001 TO PIC S9(3)V99 stores a negative zero."""
    assert format_numeric(D("-0.001"), 5, 2, True, "leading_sep") == "-00000"


def test_compute_result_of_zero_is_positive_zero():
    assert not store(D("-0.001"), 5, 2).is_signed()
    assert not store(D("-5") * 0, 5, 2).is_signed()
    assert store(D("-0.001"), 5, 2, move=True).is_signed()


@given(st.integers(-99999, 99999))
def test_roundtrip_signed(n):
    text = format_numeric(D(n).scaleb(-2), 5, 2, True)
    assert parse_numeric(text, 5, 2, True) == D(n).scaleb(-2)

