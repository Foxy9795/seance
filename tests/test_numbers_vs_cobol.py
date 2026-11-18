"""Differential tests: our number formatting must equal what real GnuCOBOL writes."""

import re
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from seance.cobol_num import edited_digits, edited_supported, format_edited, format_numeric, parse_numeric, store
from seance.recorder import cobc_available, cobc_path, cobol_env

pytestmark = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")

VALUES = ["0", "0.05", "5", "12.5", "123.45", "1234.56", "-1.5", "-0.05", "-1234.56", "99999.99", "987654.32", "-987654.32", "7", "100", "0.99", "1000000", "-1000000", "100000.5", "2000000.07", "-0.001", "-0.00"]

EDITED = [
    "9999.99", "ZZZ9.99", "ZZZ9", "ZZ,ZZ9.99", "ZZ,ZZ9.99-", "ZZ9.99CR", "ZZ9.99DB", "$$,$$$,$$9.99", "$$$9.99", "$ZZ,ZZ9.99",
    "+++9.99", "---9.99", "-(5)9.99", "--,--9.99", "***,**9.99", "ZZZ,ZZ9", "999,999.99", "ZZ9.99+", "99B99",
    "$$,$$9.99-", "$$,$$9.99", "$$$,$$9.99-", "$$$9.99-", "$$,$$9",
]
SIGNED = [("S9(5)V99", "trailing_over"), ("S9(5)V99 SIGN LEADING", "leading_over"), ("S9(5)V99 SIGN TRAILING SEPARATE", "trailing_sep"), ("S9(5)V99 SIGN LEADING SEPARATE", "leading_sep")]


def expand(pic: str) -> str:
    return re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), pic)


def run_cobol(fields: list[str]) -> list[str]:
    """fields: PIC clauses. Returns, per VALUES entry, the line COBOL wrote (all fields side by side)."""
    decl = "\n".join(f"           05 F{i} PIC {pic}." for i, pic in enumerate(fields))
    moves = "\n".join(f"           MOVE F{i}-SRC TO F{i}" for i in range(len(fields)))
    steps = "\n".join(f"           MOVE {v} TO W-V\n           PERFORM EMIT" for v in VALUES)
    src = f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NUMS.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-F ASSIGN TO "OUT.TXT" ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD OUT-F.
       01 OUT-R.
{decl}
       WORKING-STORAGE SECTION.
       01 W-V PIC S9(7)V99.
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-F
{steps}
           CLOSE OUT-F
           STOP RUN.
       EMIT.
           MOVE W-V TO {" ".join(f"F{i}" for i in range(len(fields)))}
           WRITE OUT-R.
"""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "nums.cob").write_text(src, encoding="ascii")
        env = cobol_env()
        built = subprocess.run([cobc_path(), "-x", "-free", "-o", str(work / "nums.exe"), str(work / "nums.cob")], capture_output=True, text=True, env=env)
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(work / "nums.exe")], cwd=work, capture_output=True, text=True, env=env)
        assert ran.returncode == 0, ran.stderr
        return (work / "OUT.TXT").read_text(encoding="latin-1").split("\n")[: len(VALUES)]


def split(line: str, widths: list[int]) -> list[str]:
    out, pos = [], 0
    for w in widths:
        out.append(line[pos : pos + w].ljust(w))
        pos += w
    return out


def test_edited_pictures_match_cobol():
    unsupported = [p for p in EDITED if not edited_supported(expand(p))]
    assert not unsupported, unsupported
    widths = [len(expand(p)) for p in EDITED]
    lines = run_cobol(EDITED)
    problems = []
    for v, line in zip(VALUES, lines):
        for pic, w, real in zip(EDITED, widths, split(line.ljust(sum(widths)), widths)):
            if len(str(int(abs(Decimal(v))))) > edited_digits(expand(pic))[0]:
                continue  # overflow display is not emulated (documented)
            ours = format_edited(Decimal(v), expand(pic))
            if ours != real:
                problems.append(f"{pic:<16} value {v:>11}: cobol={real!r} ours={ours!r}")
    assert not problems, "\n" + "\n".join(problems[:25])


def test_signed_storage_matches_cobol():
    fields = [p for p, _ in SIGNED]
    widths = [7, 7, 8, 8]
    lines = run_cobol(fields)
    problems = []
    for v, line in zip(VALUES, lines):
        for (pic, mode), w, real in zip(SIGNED, widths, split(line.ljust(sum(widths)), widths)):
            literal = Decimal(v) if Decimal(v) != 0 else Decimal(0)  # a literal -0.00 in COBOL source is plain zero
            sender = store(literal, 9, 2, True, move=True)  # W-V PIC S9(7)V99
            expected_value = store(sender, 7, 2, True, move=True)  # MOVE W-V TO the S9(5)V99 field
            ours = format_numeric(expected_value, 7, 2, True, mode)
            if ours != real:
                problems.append(f"{pic:<34} value {v:>11}: cobol={real!r} ours={ours!r}")
            elif parse_numeric(real, 7, 2, True, mode) != expected_value or parse_numeric(real, 7, 2, True, mode).is_signed() != expected_value.is_signed():
                problems.append(f"{pic:<34} value {v:>11}: parse gave {parse_numeric(real, 7, 2, True, mode)} expected {expected_value}")
    assert not problems, "\n" + "\n".join(problems[:25])





