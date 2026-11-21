"""Measure Séance's edited pictures against GnuCOBOL: random pictures, random values, one compiled program.

    python scripts/fuzz_editing.py [--pics 300] [--values 8] [--seed 1] [--alpha]

Each picture becomes a field of a COBOL program that MOVEs every value into it and DISPLAYs the result. The same moves
go through seance.editing. Every difference is printed with the picture and the value. Pictures GnuCOBOL refuses to
compile are dropped (and counted), so the generator may be generous.
"""

from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def rand_numeric_pic(rng: random.Random) -> tuple[str, bool]:
    """A numeric-edited picture in the usual shapes, and whether it is BLANK WHEN ZERO."""
    cur = "$"
    parts: list[str] = []
    style = rng.choice(["z", "star", "float$", "float+", "float-", "nine", "z", "float$"])
    lead = rng.choice(["", "", "", "+", "-", "$", "+$", "-$"]) if style in ("z", "star", "nine") else rng.choice(["", "", "+", "-"]) if style == "float$" else ""
    parts.append(lead)
    n_int = rng.randint(1, 7)
    body = []
    sym = {"z": "Z", "star": "*", "float$": "$", "float+": "+", "float-": "-", "nine": "9"}[style]
    run = rng.randint(1 if style in ("z", "star", "nine") else 2, n_int + 1)
    for k in range(run):
        body.append(sym)
        if k and rng.random() < 0.2:
            body.append(rng.choice([",", ",", "B", "0", "/"]))
    for _ in range(max(0, n_int - run + 1)):
        body.append("9")
        if rng.random() < 0.15:
            body.append(rng.choice([",", "B", "0", "/"]))
    if body and body[-1] in ",B0/" and rng.random() < 0.7:
        body.pop()
    parts.append("".join(body))
    point = rng.choice([".", ".", ".", "V", ""])
    if point:
        n_dec = rng.randint(0 if point == "V" else 1, 4)
        dec_sym = rng.choice(["9", "9", "9", sym if style not in ("nine",) else "9", "Z" if style == "z" else "9"])
        dec = []
        for k in range(n_dec):
            dec.append(dec_sym if (dec_sym != "9" and rng.random() < 0.8) else "9")
            if rng.random() < 0.1:
                dec.append(rng.choice(["B", "0", "/"]))
        parts.append(point + "".join(dec))
    trail = ""
    if not lead and style not in ("float+", "float-") and rng.random() < 0.5:
        trail = rng.choice(["+", "-", "CR", "DB"])
    parts.append(trail)
    if rng.random() < 0.06 and not point:
        parts.append("PP")
    pic = "".join(parts).rstrip(",")  # a comma before a space is a separator, not part of the picture
    return pic, rng.random() < 0.08


def rand_values(rng: random.Random, n: int) -> list[str]:
    vals = ["0", "-0.01", "1", "-1"]
    while len(vals) < n:
        ints = rng.choice([0, 0, 1, 2, 3, 4, 5, 6, 8, 10])
        decs = rng.choice([0, 1, 2, 2, 3, 4])
        i = str(rng.randint(0, 10 ** ints - 1)) if ints else "0"
        d = "".join(rng.choice("0123456789") for _ in range(decs))
        s = ("-" if rng.random() < 0.4 else "") + i + ("." + d if decs else "")
        vals.append(s)
    return vals[:n]


def program(pics: list[tuple[str, bool]], values: list[str], deedit: bool = False) -> str:
    """MOVE each value into each picture and DISPLAY it; with deedit, MOVE the edited field back into a number and
    DISPLAY that number instead."""
    lines = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. FUZZED.", "       DATA DIVISION.", "       WORKING-STORAGE SECTION.",
             "       01  SRC PIC S9(12)V9(6).", "       01  BACK PIC S9(12)V9(6) SIGN LEADING SEPARATE."]
    for i, (p, bwz) in enumerate(pics):
        lines.append(f"       01  E{i:04d} PIC {p}{' BLANK WHEN ZERO' if bwz else ''}.")
    lines.append("       PROCEDURE DIVISION.")
    for v in values:
        lines.append(f"           MOVE {v} TO SRC.")
        for i in range(len(pics)):
            lines.append(f"           MOVE SRC TO E{i:04d}.")
            if deedit:
                lines.append(f"           MOVE E{i:04d} TO BACK.")
                lines.append('           DISPLAY "[" BACK "]".')
            else:
                lines.append(f'           DISPLAY "[" E{i:04d} "]".')
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


def shown_back(value: Decimal) -> str:
    """How GnuCOBOL DISPLAYs S9(12)V9(6) SIGN LEADING SEPARATE."""
    n = int((abs(value) * 10**6).to_integral_value(rounding="ROUND_DOWN")) % 10**18
    s = str(n).zfill(18)
    return ("-" if value < 0 and n else "+") + s[:12] + "." + s[12:]


def compile_run(src: str, work: Path) -> tuple[list[str] | None, str]:
    from seance.recorder import cobc_path, cobol_env

    cob = work / "fuzz.cbl"
    cob.write_text(src, encoding="latin-1")
    exe = work / "fuzz.exe"
    proc = subprocess.run([cobc_path(), "-x", "-o", str(exe), str(cob)], capture_output=True, text=True, env=cobol_env(), cwd=work)
    if proc.returncode != 0:
        return None, proc.stderr + proc.stdout
    run = subprocess.run([str(exe)], capture_output=True, env=cobol_env(), cwd=work, timeout=120)
    return run.stdout.decode("latin-1").splitlines(), ""


def main(argv: list[str]) -> int:
    from seance import editing

    ap = argparse.ArgumentParser()
    ap.add_argument("--pics", type=int, default=300)
    ap.add_argument("--values", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--show", type=int, default=40)
    ap.add_argument("--deedit", action="store_true", help="check MOVE from the edited field back into a number")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    pics, seen = [], set()
    while len(pics) < a.pics:
        p = rand_numeric_pic(rng)
        if re.fullmatch(r"[9PV]+", p[0]):
            continue  # a plain number with scaling, not an edited picture
        if p[0] not in seen:
            seen.add(p[0])
            pics.append(p)
    values = rand_values(rng, a.values)
    dropped = 0
    with tempfile.TemporaryDirectory(prefix="fuzz_") as tmp:
        work = Path(tmp)
        while True:
            out, err = compile_run(program(pics, values, a.deedit), work)
            if out is not None:
                break
            bad = {int(m.group(1)) for m in re.finditer(r"fuzz\.cbl:(\d+):", err)}
            idx = {n - 7 for n in bad if 7 <= n < 7 + len(pics)}  # the fields start on line 7
            if not idx:
                print(err[:2000])
                return 2
            dropped += len(idx)
            pics = [p for i, p in enumerate(pics) if i not in idx]
    k = 0
    diffs = []
    refused: set[str] = set()
    for v in values:
        src = Decimal(v).quantize(Decimal("0.000001"), rounding="ROUND_DOWN")
        for p, bwz in pics:
            want = out[k][1:-1]
            k += 1
            try:
                got = editing.format_numeric(src, p, "$", bwz)
                if a.deedit:
                    got = shown_back(editing.deedit_numeric(got, p))
            except editing.EditError:
                refused.add(p)  # Séance says so when it loads the program, and translates nothing silently
                continue
            except Exception as exc:  # anything else is a bug
                got = f"<{type(exc).__name__}: {exc}>"
            if got != want:
                diffs.append((p, bwz, v, want, got))
    total = len(values) * len(pics)
    print(f"{len(pics)} pictures ({dropped} refused by GnuCOBOL, {len(refused)} by Séance) x {len(values)} values = {total} moves; "
          f"{len(diffs)} differ")
    for p, bwz, v, want, got in diffs[: a.show]:
        print(f"  {p:<22}{' BWZ' if bwz else '    '} {v:>16}  cobol [{want}]  seance [{got}]")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
