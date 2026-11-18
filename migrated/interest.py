"""Migrated from legacy/interest/interest.cbl."""

from decimal import Decimal

from generated.interest_records import InRecord, OutRecord
from seance.cobol_num import store

D = Decimal


def transform(rec: InRecord) -> OutRecord:
    if rec.balance > 0:
        status = "P"
        interest = store(rec.balance * rec.rate * rec.days / 365, 11, 2, rounded=True)
        new_bal = rec.balance + interest
    elif rec.balance < 0:
        status = "O"
        interest = D(0)
        new_bal = rec.balance - D("25.00")
    else:
        status = "Z"
        interest = D(0)
        new_bal = D(0)
    return OutRecord(acct_id=rec.acct_id, interest=interest, new_bal=new_bal, status=status)
