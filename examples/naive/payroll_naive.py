"""A plausible first-draft migration of payroll.cbl. Used to show what Séance catches."""

from decimal import Decimal

from generated.payroll_records import InRecord, OutRecord


def transform(rec: InRecord) -> OutRecord:
    hours, rate = float(rec.hours), float(rec.rate)
    pay = min(hours, 40) * rate + max(hours - 40, 0) * rate * 1.5
    gross = round(pay, 2)
    if gross <= 500:
        tax = gross * 0.10
    elif gross <= 1500:
        tax = 50 + (gross - 500) * 0.20
    else:
        tax = 250 + (gross - 1500) * 0.30
    tax = round(tax, 2)
    net = round(gross - tax - 12.5, 2) if hours > 0 else 0.0
    return OutRecord(emp_id=rec.emp_id, gross=Decimal(str(gross)), tax=Decimal(str(tax)), net=Decimal(str(net)))
