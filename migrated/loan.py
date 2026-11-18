"""Migrated from legacy/loan/loan.cbl."""

from decimal import Decimal

from generated.loan_records import InRecord, OutRecord
from seance.cobol_num import size_error, store

D = Decimal


def _error(rec: InRecord) -> OutRecord:
    return OutRecord(loan_id=rec.loan_id, payment=D(0), interest=D(0), status="E")


def transform(rec: InRecord) -> OutRecord:
    r = store(rec.rate / 12, 11, 10, signed=False)  # WS-R PIC 9V9(10), truncated
    try:
        if rec.rate == 0:
            raw = rec.principal / rec.term
        else:
            raw = rec.principal * r / (1 - (1 + r) ** (0 - rec.term))
    except ArithmeticError:  # division by zero (term 0): ON SIZE ERROR fires
        return _error(rec)
    if size_error(raw, 9, 2, signed=False, rounded=True):
        return _error(rec)
    pay = store(raw, 9, 2, signed=False, rounded=True)  # WS-PAY PIC 9(7)V99
    interest = store(pay * rec.term - rec.principal, 10, 2)  # OUT-INTEREST PIC S9(8)V99
    return OutRecord(loan_id=rec.loan_id, payment=pay, interest=interest, status="K")
