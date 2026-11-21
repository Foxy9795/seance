"""Intrinsic functions, Séance against GnuCOBOL on random arguments.

Writes a program that DISPLAYs FUNCTION results (and COMPUTEs them into fields) for random arguments, runs the
compiled COBOL and the translated Python on it, and prints every line that differs.

    python scripts/fuzz_functions.py [--seed N] [--count N] [--only NAME,NAME]
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = [
    # name, picture/usage, value
    ("N1", "PIC 9(5)V99", "123.45"), ("N2", "PIC S9(7)V9(4)", "-4567.0912"), ("N3", "PIC S9(3) COMP", "-17"),
    ("N4", "PIC 9(9)V9(9) COMP-3", "12.000000001"), ("N5", "PIC S99V9(6) COMP-5", "0.523599"), ("N6", "PIC 9(4)", "2024"),
    ("N7", "PIC S9(15)V9(3)", "-999999999999.999"), ("N8", "PIC 99V99", "0"), ("N9", "PIC S9V9(8)", "0.70710678"),
    ("N10", "PIC 9(8)", "20240229"), ("N11", "PIC 9(7)", "2024060"), ("N12", "PIC S9(4)V9(2) SIGN LEADING SEPARATE", "-12.50"),
    ("A1", "PIC X(12)", '"  Mixed Case"'), ("A2", "PIC X(20)", '" -1,234.56CR"'), ("A3", "PIC X(8)", '"abc"'),
    ("A4", "PIC X(15)", '"$ 1,234.56 "'), ("A5", "PIC X(10)", '"1.5E+03"'), ("A6", "PIC X(6)", '"ZZZ"'),
]
NUMS = [n for n, _, _ in DATA if n.startswith("N")]
TEXTS = [n for n, _, _ in DATA if n.startswith("A")]


def lit_num(rng: random.Random, lo: float = -1e6, hi: float = 1e6, scale: int | None = None) -> str:
    scale = rng.choice([0, 0, 1, 2, 3, 5, 8]) if scale is None else scale
    v = rng.uniform(lo, hi)
    text = f"{v:.{scale}f}"
    if text.startswith("-0") and float(text) == 0:
        text = text[1:]
    return text


def num_arg(rng: random.Random, lo=-1e6, hi=1e6) -> str:
    return rng.choice(NUMS) if rng.random() < 0.35 else lit_num(rng, lo, hi)


def text_lit(rng: random.Random) -> str:
    pool = ["  12.50", "-3.14", "1,234.50", "+ 7", "12-", "4.5CR", "  9 DB", "1.2.3", "abc", "", " ", "0.001",
            "$12.34", "1.5E+3", "-2.5E-2", "12 34", "Hello World", "ÉÀé", "  x  "]
    s = rng.choice(pool)
    return '"' + s.replace('"', '""') + '"'


def text_arg(rng: random.Random) -> str:
    return rng.choice(TEXTS) if rng.random() < 0.5 else text_lit(rng)


def cases(rng: random.Random, only: set[str] | None) -> list[str]:
    out: list[str] = []

    def add(name: str, args: str) -> None:
        if only and name not in only:
            return
        out.append(f"FUNCTION {name} ( {args} )" if args else f"FUNCTION {name}")

    for _ in range(3):
        add("SQRT", num_arg(rng, 0, 1e6))
        add("EXP", lit_num(rng, -30, 30))
        add("EXP10", rng.choice([lit_num(rng, -8, 8), str(rng.randint(-5, 12))]))
        add("LOG", num_arg(rng, 0.001, 1e6))
        add("LOG10", num_arg(rng, 0.001, 1e6))
        add("SIN", num_arg(rng, -10, 10))
        add("COS", num_arg(rng, -10, 10))
        add("TAN", num_arg(rng, -1.5, 1.5))
        add("ASIN", lit_num(rng, -1, 1))
        add("ACOS", lit_num(rng, -1, 1))
        add("ATAN", num_arg(rng, -100, 100))
        add("ABS", num_arg(rng))
        add("INTEGER", num_arg(rng))
        add("INTEGER-PART", num_arg(rng))
        add("FRACTION-PART", num_arg(rng))
        add("SIGN", num_arg(rng))
        add("FACTORIAL", str(rng.randint(0, 30)))
        add("CHAR", str(rng.randint(33, 126)))
        add("MOD", f"{lit_num(rng, -1000, 1000, 0)} {rng.choice(['7', '-3', '2.5', 'N3', '13'])}")
        add("REM", f"{num_arg(rng, -1000, 1000)} {rng.choice(['7', '-3', '2.5', 'N3', '0.7'])}")
        add("ANNUITY", f"{lit_num(rng, 0, 0.2, 3)} {rng.randint(1, 360)}")
        add("PRESENT-VALUE", " ".join([lit_num(rng, 0, 0.2, 3)] + [num_arg(rng, 0, 1000) for _ in range(rng.randint(1, 4))]))
        for fn in ("MAX", "MIN", "ORD-MAX", "ORD-MIN", "SUM", "MEAN", "MEDIAN", "MIDRANGE", "RANGE", "VARIANCE",
                   "STANDARD-DEVIATION"):
            add(fn, " ".join(num_arg(rng, -1000, 1000) for _ in range(rng.randint(1, 5))))
        add("MAX", " ".join(text_arg(rng) for _ in range(rng.randint(2, 4))))
        add("MIN", " ".join(text_arg(rng) for _ in range(rng.randint(2, 4))))
        add("ORD-MAX", " ".join(text_arg(rng) for _ in range(rng.randint(2, 4))))
        for fn in ("UPPER-CASE", "LOWER-CASE", "REVERSE", "LENGTH", "BYTE-LENGTH", "STORED-CHAR-LENGTH", "ORD"):
            add(fn, text_arg(rng))
        add("TRIM", text_arg(rng) + rng.choice(["", " LEADING", " TRAILING"]))
        add("CONCATENATE", " ".join(text_arg(rng) for _ in range(rng.randint(2, 3))))
        add("SUBSTITUTE", f"{text_arg(rng)} \"1\" \"one\" \"a\" \"A\"")
        add("SUBSTITUTE-CASE", f"{text_arg(rng)} \"A\" \"xy\" \"l\" \"\"\"\"")
        for fn in ("NUMVAL", "NUMVAL-F", "TEST-NUMVAL", "TEST-NUMVAL-F", "TEST-NUMVAL-C"):
            add(fn, text_arg(rng))
        add("NUMVAL-C", text_arg(rng))
        add("NUMVAL-C", f"{text_arg(rng)} \"$\"")
        add("DATE-OF-INTEGER", str(rng.randint(1, 3067671)))
        add("DAY-OF-INTEGER", str(rng.randint(1, 3067671)))
        add("INTEGER-OF-DATE", rng.choice(["N10", f"{rng.randint(1601, 9999)}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"]))
        add("INTEGER-OF-DAY", rng.choice(["N11", f"{rng.randint(1601, 9999)}{rng.randint(1, 365):03d}"]))
        add("TEST-DATE-YYYYMMDD", str(rng.choice([20240230, 20231301, 16000101, 20240229, rng.randint(15000101, 99991231)])))
        add("TEST-DAY-YYYYDDD", str(rng.choice([2024366, 2023366, 1600100, rng.randint(1500001, 9999400)])))
        add("YEAR-TO-YYYY", f"{rng.randint(0, 99)} {rng.randint(-50, 80)} {rng.randint(1700, 2100)}")
        add("DATE-TO-YYYYMMDD", f"{rng.randint(0, 991231)} {rng.randint(0, 80)} {rng.randint(1700, 2100)}")
        add("DAY-TO-YYYYDDD", f"{rng.randint(0, 99366)} {rng.randint(0, 80)} {rng.randint(1700, 2100)}")
        add("HIGHEST-ALGEBRAIC", rng.choice(NUMS))
        add("LOWEST-ALGEBRAIC", rng.choice(NUMS))
    add("PI", "")
    add("E", "")
    add("RANDOM", "")
    add("RANDOM", str(rng.randint(0, 99999)))
    add("RANDOM", "")
    add("WHEN-COMPILED", "")
    add("CURRENT-DATE", "")
    return out


def wrap(head: str, words: list[str], indent: str = "               ") -> list[str]:
    lines, cur = [], "           " + head
    for w in words:
        if len(cur) + 1 + len(w) > 72:
            lines.append(cur)
            cur = indent + w
        else:
            cur += " " + w
    lines.append(cur)
    return lines


def tokens(expr: str) -> list[str]:
    import re

    return re.findall(r'"(?:[^"]|"")*"|\S+', expr)


def program(exprs: list[str]) -> str:
    lines = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. FUZZFN.", "       DATA DIVISION.",
             "       WORKING-STORAGE SECTION."]
    for name, pic, value in DATA:
        lines.append(f"       01  {name} {pic} VALUE {value}.")
    lines.append("       01  R1 PIC S9(9)V9(9).")
    lines.append("       01  R2 PIC X(40).")
    lines.append("       PROCEDURE DIVISION.")
    for k, e in enumerate(exprs, start=1):
        lines += wrap(f'DISPLAY "{k:03d}|"', tokens(e))
        numeric = not any(e.startswith(f"FUNCTION {n} ") or e == f"FUNCTION {n}" for n in (
            "UPPER-CASE", "LOWER-CASE", "REVERSE", "TRIM", "CONCATENATE", "SUBSTITUTE", "SUBSTITUTE-CASE", "CHAR",
            "CURRENT-DATE", "WHEN-COMPILED", "MAX", "MIN", "MEDIAN"))
        if numeric:
            lines += wrap("COMPUTE R1 =", tokens(e))
            lines.append(f'           DISPLAY "{k:03d}=" R1')
        lines += wrap("MOVE", tokens(e) + ["TO", "R2"])
        lines.append(f'           DISPLAY "{k:03d}>" R2 "<"')
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


def run(src: str) -> tuple[list[str], list[str], str]:
    """(COBOL lines, Python lines, problem) for one program."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from seance.cases import Case, run_cobol, run_python
    from seance.model import load_model
    from seance.recorder import compile_legacy
    from seance.translate import translate

    root = Path(tempfile.mkdtemp(prefix="fuzzfn_"))
    folder = root / "legacy" / "fuzzfn"
    folder.mkdir(parents=True)
    (folder / "fuzzfn.cbl").write_text(src, encoding="latin-1")
    model = load_model("fuzzfn", root)
    exe = compile_legacy("fuzzfn", root)
    tr = translate("fuzzfn", root)
    gaps = [f"line {g['line']}: {g['why']}" for g in tr.unsupported]
    ns: dict = {"__name__": "fuzzfn"}
    exec(compile(tr.code, "fuzzfn.py", "exec"), ns)
    from types import SimpleNamespace

    want = run_cobol(exe, model, Case(), 60)
    got = run_python(SimpleNamespace(main=ns["main"], __file__="fuzzfn.py"), Case())
    return want.stdout.splitlines(), got.stdout.splitlines(), "; ".join(gaps) + (got.error or "")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--show", action="store_true", help="print the program")
    a = ap.parse_args(argv)
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()} or None
    bad = total = 0
    for r in range(a.rounds):
        rng = random.Random(a.seed + r)
        exprs = cases(rng, only)
        src = program(exprs)
        if a.show:
            print(src)
        want, got, problem = run(src)
        if problem:
            print("PROBLEM:", problem[:2000])
        by_key_w = {ln[:4]: ln for ln in want}
        by_key_g = {ln[:4]: ln for ln in got}
        for key in sorted(set(by_key_w) | set(by_key_g)):
            total += 1
            w, g = by_key_w.get(key), by_key_g.get(key)
            if w != g:
                bad += 1
                k = int(key[:3]) - 1
                print(f"{exprs[k] if 0 <= k < len(exprs) else '?'}\n   cobol : {w!r}\n   python: {g!r}")
    print(f"{bad} of {total} lines differ")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
