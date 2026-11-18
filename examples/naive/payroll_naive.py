"""A plausible first-draft port of payroll.cbl, written by hand with floats. Séance shows where it goes wrong."""

from seance.rt import IO


def main(io: IO) -> IO:
    out = []
    for line in io.lines("INPUT.DAT"):
        line = line.ljust(15)
        emp_id, hours, rate = line[0:6], float(line[6:10] or 0) / 10, float(line[10:15] or 0) / 100
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
        sign = "-" if net < 0 else "+"
        out.append(f"{emp_id}{int(gross * 100):08d}{int(tax * 100):08d}{sign}{int(abs(net) * 100):08d}")
    io.write_lines("OUTPUT.DAT", out)
    return io
