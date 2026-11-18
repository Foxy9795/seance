"""A plausible first-draft migration of loan.cbl: floats, no SIZE ERROR handling."""

from decimal import Decimal

from generated.loan_records import InRecord, OutRecord


def transform(rec: InRecord) -> OutRecord:
    p, n = float(rec.principal), int(rec.term)
    r = float(rec.rate) / 12
    payment = p / n if r == 0 else p * r / (1 - (1 + r) ** -n)
    payment = round(payment, 2)
    interest = payment * n - p
    return OutRecord(loan_id=rec.loan_id, payment=Decimal(str(payment)), interest=Decimal(str(round(interest, 2))), status="K")
