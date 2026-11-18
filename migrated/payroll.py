"""Migrated from legacy/payroll/payroll.cbl. Each COBOL PIC store is mirrored by store()."""

from decimal import Decimal

from generated.payroll_records import InRecord, OutRecord
from seance.cobol_num import store

D = Decimal


def transform(rec: InRecord) -> OutRecord:
    if rec.hours > 40:
        reg = store(40 * rec.rate, 8, 2, signed=False, rounded=True)
        ot = store((rec.hours - 40) * rec.rate * D("1.5"), 8, 2, signed=False, rounded=True)
    else:
        reg = store(rec.hours * rec.rate, 8, 2, signed=False, rounded=True)
        ot = D(0)
    gross = store(reg + ot, 8, 2, signed=False)
    if gross <= 500:
        tax = store(gross * D("0.10"), 8, 2, signed=False, rounded=True)
    elif gross <= 1500:
        tax = store(50 + (gross - 500) * D("0.20"), 8, 2, signed=False, rounded=True)
    else:
        tax = store(250 + (gross - 1500) * D("0.30"), 8, 2, signed=False, rounded=True)
    net = gross - tax - D("12.50") if rec.hours > 0 else D(0)
    return OutRecord(emp_id=rec.emp_id, gross=gross, tax=tax, net=net)
