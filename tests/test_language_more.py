"""COBOL that release 1.2 added to the translator, each program checked against GnuCOBOL: the COBOL is the judge.

Edited pictures are measured with random pictures and values (scripts/fuzz_editing.py), both ways: what a MOVE writes
into the edited field, and what a MOVE reads back out of it.
"""
import importlib.util
import random
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from seance import editing
from seance.recorder import cobc_available

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stress = _load("stress_translate")
fuzz = _load("fuzz_editing")

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. prog.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"

PROGRAMS = {
    "continued literals keep their spaces to column 72": HEAD + """       01  HDR.
           02 FILLER  PIC IS X(60)    VALUE IS " FEATURE              PA
      -    "SS  PARAGRAPH-NAME
      -    "       REMARKS".
       01  W2  PIC X(40) VALUE "ONE TWO
      *    a comment line between the halves
      -    "THREE ""Q"" FOUR".
       01  N1  PIC 9(6) VALUE 12
      -    3456.
       PROCEDURE DIVISION.
           DISPLAY "[" HDR "]" "[" W2 "]" N1.
           STOP RUN.
""",
    "condition names qualified, several set at once, set to false": HEAD + """       01  REC-A.
           05 STATUS-A PIC X VALUE "Y".
              88 OK VALUE "Y" FALSE "N".
              88 BAD VALUE "N".
       01  REC-B.
           05 STATUS-B PIC X VALUE "N".
              88 OK VALUE "Y" FALSE "N".
       PROCEDURE DIVISION.
           IF OK OF REC-A DISPLAY "A OK" ELSE DISPLAY "A NOT OK".
           IF OK IN STATUS-B DISPLAY "B OK" ELSE DISPLAY "B NOT OK".
           SET OK OF REC-B BAD TO TRUE.
           DISPLAY STATUS-A STATUS-B.
           SET OK OF REC-A TO FALSE.
           DISPLAY STATUS-A.
           STOP RUN.
""",
    "edited pictures, alphanumeric edited, currency sign, de-editing": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           CURRENCY SIGN IS "W".
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  AE1 PIC XXBXX/XX.
       01  AE2 PIC X0X0X.
       01  ED1 PIC WWW,WW9.99.
       01  ED2 PIC -9,9.9/9.
       01  ED3 PIC W9,9B9.9+.
       01  ED4 PIC ZZZPP.
       01  ED5 PIC .9/9,9,9.
       01  ED6 PIC --9B.9B9/9.
       01  BACK PIC S9(6)V99.
       PROCEDURE DIVISION.
           MOVE "ABCDEFGH" TO AE1. MOVE "XYZ" TO AE2.
           DISPLAY "[" AE1 "][" AE2 "]".
           MOVE 1234.5 TO ED1. DISPLAY "[" ED1 "]".
           MOVE ED1 TO BACK. DISPLAY BACK.
           MOVE -12.34 TO ED2. MOVE -1234.5 TO ED3. MOVE 12345 TO ED4.
           MOVE 0.1234 TO ED5. MOVE 12.345 TO ED6.
           DISPLAY "[" ED2 "][" ED3 "][" ED4 "][" ED5 "][" ED6 "]".
           MOVE ED3 TO BACK. DISPLAY BACK.
           STOP RUN.
""",
    "indexes without BY, MULTIPLY into a table entry": HEAD + """       01  TAB.
           05 ENT PIC 9(3) OCCURS 4 TIMES INDEXED IX1.
       01  NUM PIC 9(3) VALUE 7.
       PROCEDURE DIVISION.
           SET IX1 TO 3.
           MOVE 25 TO ENT (IX1).
           MULTIPLY NUM BY ENT (IX1).
           DISPLAY ENT (3).
           STOP RUN.
""",
    "paragraphs of the same name in two sections, and ALTER": HEAD + """       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM DUP-PARA OF SEC-TWO.
           PERFORM SEC-ONE.
           PERFORM SEC-TWO.
           ALTER SWITCH-PARA TO PROCEED TO SECOND-WAY.
           GO TO SWITCH-PARA.
       SWITCH-PARA.
           GO TO FIRST-WAY.
       FIRST-WAY.
           DISPLAY "FIRST WAY".
           GO TO DONE-PARA.
       SECOND-WAY.
           DISPLAY "SECOND WAY".
       DONE-PARA.
           STOP RUN.
       SEC-ONE SECTION.
       DUP-PARA.
           DISPLAY "DUP IN ONE".
           PERFORM DUP-PARA2.
       DUP-PARA2.
           DISPLAY "DUP2 IN ONE".
       SEC-TWO SECTION.
       DUP-PARA.
           DISPLAY "DUP IN TWO".
       DUP-PARA2.
           DISPLAY "DUP2 IN TWO".
""",
}


@needs_cobol
@pytest.mark.parametrize("label", sorted(PROGRAMS))
def test_translation_matches_gnucobol(tmp_path, label):
    src = tmp_path / "prog.cob"
    src.write_text(PROGRAMS[label], encoding="utf-8")
    result = stress.run_one(src, "stp", tmp_path)
    assert result["stage"] == "match", result


def _fuzz(seed: int, deedit: bool, pics: int = 120, values: int = 8):
    rng = random.Random(seed)
    chosen, seen = [], set()
    while len(chosen) < pics:
        p = fuzz.rand_numeric_pic(rng)
        if p[0] in seen or fuzz.re.fullmatch(r"[9PV]+", p[0]) or not editing.numeric_edited_ok(p[0]):
            continue
        seen.add(p[0])
        chosen.append(p)
    vals = fuzz.rand_values(rng, values)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        while True:
            out, err = fuzz.compile_run(fuzz.program(chosen, vals, deedit), work)
            if out is not None:
                break
            bad = {int(m.group(1)) - 7 for m in fuzz.re.finditer(r"fuzz\.cbl:(\d+):", err)}
            assert bad, err[:500]
            chosen = [p for i, p in enumerate(chosen) if i not in bad]
    diffs, k = [], 0
    for v in vals:
        src = Decimal(v).quantize(Decimal("0.000001"), rounding="ROUND_DOWN")
        for p, bwz in chosen:
            want = out[k][1:-1]
            k += 1
            got = editing.format_numeric(src, p, "$", bwz)
            if deedit:
                got = fuzz.shown_back(editing.deedit_numeric(got, p))
            if got != want:
                diffs.append(f"{p} {'BWZ ' if bwz else ''}{v}: cobol [{want}] seance [{got}]")
    return diffs


@needs_cobol
@pytest.mark.parametrize("seed", [101, 202])
def test_edited_moves_match_gnucobol_on_random_pictures(seed):
    diffs = _fuzz(seed, deedit=False)
    assert not diffs, "\n".join(diffs[:20])


@needs_cobol
@pytest.mark.parametrize("seed", [303])
def test_moves_out_of_edited_fields_match_gnucobol(seed):
    diffs = _fuzz(seed, deedit=True)
    assert not diffs, "\n".join(diffs[:20])


def test_edited_capacity_counts_the_cells_a_symbol_keeps():
    assert editing.capacity("$$$$") == (3, 0)
    assert editing.capacity("+$ZZ9") == (3, 0)
    assert editing.capacity("----9.99") == (4, 2)
    assert editing.capacity("ZZZPP") == (5, 0)
    assert editing.format_alpha("ABCDEFGH", "XXBXX/XX") == "AB CD/EF"
