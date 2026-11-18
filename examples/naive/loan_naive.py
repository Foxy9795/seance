"""A plausible first-draft port of loan.cbl, written by hand: floats and no SIZE ERROR handling."""

from seance.rt import IO


def main(io: IO) -> IO:
    out = []
    for line in io.lines("INPUT.DAT"):
        line = line.ljust(25)
        loan_id = line[0:8]
        p, r, n = float(line[8:17] or 0) / 100, float(line[17:22] or 0) / 10000 / 12, int(line[22:25] or 0)
        payment = p / n if r == 0 else p * r / (1 - (1 + r) ** -n)
        payment = round(payment, 2)
        interest = round(payment * n - p, 2)
        sign = "-" if interest < 0 else "+"
        out.append(f"{loan_id}{int(payment * 100):09d}{sign}{int(abs(interest) * 100):010d}K")
    io.write_lines("OUTPUT.DAT", out)
    return io
