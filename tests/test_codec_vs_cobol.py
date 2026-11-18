"""Byte-level differential tests: our encoding of COMP, COMP-3, COMP-5 and DISPLAY equals GnuCOBOL's, and
DISPLAY prints numbers the way GnuCOBOL does."""

import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from seance.codec import decode, display_text, encode, store_into
from seance.layout import parse_entries
from seance.recorder import cobc_available, cobc_path, cobol_env

pytestmark = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")

FIELDS = [
    "S9(2) COMP", "S9(4) COMP", "S9(9) COMP", "S9(18) COMP", "9(4) COMP", "9(9) BINARY", "S9(4) COMP-5", "9(6) COMP-5",
    "S9(5)V99 COMP-3", "9(4) COMP-3", "S9(4) COMP-3", "S9(7)V99 COMP-3", "S9(3)V99", "S9(3)V99 SIGN LEADING SEPARATE",
    "9(3)V99", "S9(5)V99 COMP",
]
VALUES = ["0", "1", "-1", "12.34", "-12.34", "999", "-999", "1234.56", "-0.01", "99.99", "-5", "77777.77", "-123456.78"]


def _entries():
    lines = ["01 R."] + [f"   05 F{i} PIC {f}." for i, f in enumerate(FIELDS)]
    return [(n, t) for n, t in enumerate(lines, 1)]


def run_cobol():
    decl = "\n".join(f"           05 F{i} PIC {f}." for i, f in enumerate(FIELDS))
    disp = "\n".join(f"           DISPLAY F{i}" for i in range(len(FIELDS)))
    body = "\n".join(f"           MOVE {v} TO W-V\n           PERFORM EMIT" for v in VALUES)
    src = f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CODEC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-F ASSIGN TO OUTF ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD OUT-F.
       01 R.
{decl}
       WORKING-STORAGE SECTION.
       01 W-V PIC S9(9)V99.
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-F
{body}
           CLOSE OUT-F
           STOP RUN.
       EMIT.
           MOVE W-V TO {" ".join(f"F{i}" for i in range(len(FIELDS)))}
           WRITE R
{disp}.
"""
    with tempfile.TemporaryDirectory() as tmp:
        w = Path(tmp)
        (w / "c.cbl").write_text(src, encoding="ascii")
        env = cobol_env()
        r = subprocess.run([cobc_path(), "-x", "-free", "-o", str(w / "c.exe"), str(w / "c.cbl")], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        env["DD_OUTF"] = str(w / "out.dat")
        r = subprocess.run([str(w / "c.exe")], cwd=w, capture_output=True, env=env)
        assert r.returncode == 0, r.stderr
        return (w / "out.dat").read_bytes(), r.stdout.decode("latin-1").replace("\r\n", "\n").split("\n")


def test_encoding_and_display_match_gnucobol():
    (rec,) = parse_entries(_entries())
    items = rec.children
    data, shown = run_cobol()
    assert len(data) == rec.size * len(VALUES), (len(data), rec.size)
    problems = []
    for k, v in enumerate(VALUES):
        chunk = data[k * rec.size:(k + 1) * rec.size]
        for i, it in enumerate(items):
            spec = (it.kind, it.usage, it.digits, it.scale, it.signed, it.sign, it.pic, it.size, it.justified, it.blank_zero)
            stored = store_into(spec, Decimal(store_into((it.kind, "display", 11, 2, True, "trailing_over", "", 11, False, False), Decimal(v), move=True)), move=True)
            ours = encode(spec, stored)
            real = chunk[it.offset:it.offset + it.size]
            if ours != real:
                problems.append(f"{FIELDS[i]:<22} {v:>11}: cobol={real.hex()} ours={ours.hex()}")
            elif decode(spec, real) != stored:
                problems.append(f"{FIELDS[i]:<22} {v:>11}: decoded {decode(spec, real)} expected {stored}")
            printed = shown[k * len(items) + i]
            if display_text(spec, real) != printed:
                problems.append(f"{FIELDS[i]:<22} {v:>11}: DISPLAY cobol={printed!r} ours={display_text(spec, real)!r}")
    assert not problems, "\n" + "\n".join(problems[:30])
