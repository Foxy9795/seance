"""End to end: every shipped migration must match the real COBOL program."""

import pytest

from seance.recorder import cobc_available
from seance.verify import verify

pytestmark = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")


@pytest.mark.parametrize("program", ["payroll", "interest", "inventory", "loan"])
def test_migration_matches_legacy(program):
    report = verify(program, examples=30)
    assert report.matched, report.review


def test_naive_payroll_is_caught():
    report = verify("payroll", "examples.naive.payroll_naive", examples=30)
    assert not report.matched
    assert report.property_mismatch is not None


def test_naive_loan_is_caught():
    report = verify("loan", "examples.naive.loan_naive", examples=30)
    assert not report.matched
    assert report.property_mismatch is not None
