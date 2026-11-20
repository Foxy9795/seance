"""Constructs found by the translator stress test (scripts/stress_translate.py), each checked against GnuCOBOL.

Every program here is compiled with GnuCOBOL, translated, run both ways, and compared: the COBOL is the judge.
"""
import importlib.util
from pathlib import Path

import pytest

from seance.model import limit_notes

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "stress_translate.py"
_spec = importlib.util.spec_from_file_location("stress_translate", SCRIPT)
stress = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stress)

HEAD = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. prog.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"

PROGRAMS = {
    "signed literals": HEAD + """       01  I    PIC S99.
       PROCEDURE DIVISION.
           DISPLAY FUNCTION MAX ( 3 -14 0 8 -3 ).
           DISPLAY FUNCTION MIN ( 3 -14 0 8 -3 ).
           PERFORM VARYING I FROM 3 BY -1 UNTIL I < 1
               DISPLAY "I=" I
           END-PERFORM.
           SUBTRACT -1 FROM I. DISPLAY I.
           STOP RUN.
""",
    "rounded modes": HEAD + """       01  R1   PIC S9.
       01  R2   PIC S9.
       01  R3   PIC S9.
       01  R4   PIC S9.
       01  R5   PIC 9V9.
       01  R6   PIC S9.
       PROCEDURE DIVISION.
           COMPUTE R1 ROUNDED MODE AWAY-FROM-ZERO = 2.49.
           COMPUTE R2 ROUNDED MODE NEAREST-EVEN = 2.5.
           COMPUTE R3 ROUNDED MODE TOWARD-GREATER = -2.5.
           COMPUTE R4 ROUNDED MODE TRUNCATION = 2.99.
           COMPUTE R5 ROUNDED MODE NEAREST-TOWARD-ZERO = 1.25.
           COMPUTE R6 ROUNDED MODE TOWARD-LESSER = -2.1.
           DISPLAY R1 " " R2 " " R3 " " R4 " " R5 " " R6.
           STOP RUN.
""",
    "binary types without a PIC": HEAD + """       01  A5  PIC S9(04) COMP-5 VALUE 33.
       01  BL  USAGE BINARY-LONG VALUE 33.
       01  BC  USAGE BINARY-CHAR VALUE -5.
       01  BS  USAGE BINARY-SHORT UNSIGNED VALUE 7.
       01  BI  USAGE BINARY-INT VALUE 5.
       01  BD  USAGE BINARY-DOUBLE VALUE 123456789012.
       01  X7  PIC X(7) JUSTIFIED RIGHT.
       01  X8  PIC X(8).
       PROCEDURE DIVISION.
           MOVE A5 TO X7. DISPLAY ">" X7 "<".
           MOVE BL TO X8. DISPLAY ">" X8 "<".
           MOVE BC TO X8. DISPLAY ">" X8 "<".
           MOVE BS TO X8. DISPLAY ">" X8 "<".
           DISPLAY BL " " BC " " BS " " BI " " BD.
           ADD 1 TO BC. DISPLAY BC.
           STOP RUN.
""",
    "sign positions and BLANK WHEN ZERO": HEAD + """       01  X            PIC S9 SIGN LEADING SEPARATE.
       01  Y            PIC S9 SIGN TRAILING SEPARATE.
       01  Z            PIC S9(3) TRAILING SEPARATE.
       01  W            PIC S9(3) LEADING.
       01  V            PIC 9, BLANK WHEN ZERO, VALUE 1.
       PROCEDURE DIVISION.
           MOVE 0 TO X. DISPLAY X NO ADVANCING.
           MOVE ZERO TO Y. DISPLAY Y NO ADVANCING.
           MOVE -12 TO Z. DISPLAY Z " " NO ADVANCING.
           MOVE -12 TO W. DISPLAY W " " NO ADVANCING.
           DISPLAY V NO ADVANCING.
           MOVE 0 TO V. DISPLAY "[" V "]".
           STOP RUN.
""",
    "P positions moved to text": HEAD + """       01  N   PIC S9(4)PP VALUE 4400.
       01  X7  PIC X(7) JUSTIFIED RIGHT.
       PROCEDURE DIVISION.
           MOVE N TO X7. DISPLAY ">" X7 "<".
           STOP RUN.
""",
    "packed NUMERIC class test": HEAD + """       01 G.
         02 X-2         PIC X(2).
         02 N-2         REDEFINES X-2 PIC 999  USAGE PACKED-DECIMAL.
         02 N-S2        REDEFINES X-2 PIC S999 USAGE PACKED-DECIMAL.
       PROCEDURE DIVISION.
           MOVE X"0000" TO X-2.
           IF N-2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           IF N-S2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           MOVE X"000c" TO X-2.
           IF N-2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           IF N-S2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           MOVE X"000f" TO X-2.
           IF N-2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           IF N-S2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           MOVE X"1234" TO X-2.
           IF N-2 IS NUMERIC DISPLAY "a" ELSE DISPLAY "b" END-IF.
           STOP RUN.
""",
    "perform forever and until exit": HEAD + """       01  INDVAL       PIC 9(4).
       PROCEDURE DIVISION.
       A01.
           MOVE 0 TO INDVAL
           PERFORM UNTIL EXIT
            ADD 1 TO INDVAL
            IF INDVAL > 2
               EXIT PERFORM
            END-IF
           END-PERFORM
           DISPLAY "A " INDVAL.
           PERFORM FOREVER
            ADD 1 TO INDVAL
            IF INDVAL < 4
               EXIT PERFORM CYCLE
            END-IF
            IF INDVAL > 5
               EXIT PERFORM
            END-IF
           END-PERFORM
           DISPLAY "B " INDVAL.
           STOP RUN.
""",
    "star-greater comment in fixed format": HEAD + """       01  A   PIC X(9).
       *> a floating comment before the next entry must not join it
       01  B   PIC X(2) VALUE "ok".
       PROCEDURE DIVISION.
           MOVE "x" TO A. *> and one after a statement
           DISPLAY A B.
           STOP RUN.
""",
}


@pytest.mark.parametrize("label", sorted(PROGRAMS))
def test_translation_matches_gnucobol(tmp_path, label):
    src = tmp_path / "prog.cob"
    src.write_text(PROGRAMS[label], encoding="utf-8")
    result = stress.run_one(src, "stp", tmp_path)
    assert result["stage"] == "match", result


def test_the_suite_reader_finds_programs_and_skips_the_unusable():
    at = (
        "AT_SETUP([first])\nAT_DATA([prog.cob], [\n       DISPLAY @S|@X @<:@1@:>@.\n])\n"
        "AT_CHECK([$COMPILE prog.cob], [0], [], [])\nAT_CLEANUP\n"
        "AT_SETUP([needs a file])\nAT_DATA([prog.cob], [\n       STOP RUN.\n])\nAT_DATA([data.txt], [\nabc\n])\nAT_CLEANUP\n"
        "AT_SETUP([must not compile])\nAT_DATA([prog.cob], [\n       oops\n])\nAT_CHECK([$COMPILE prog.cob], [1], [], [err])\nAT_CLEANUP\n"
    )
    cases = stress.extract(at)
    assert [c["name"] for c in cases] == ["first", "needs a file", "must not compile"]
    assert "DISPLAY $X [1]." in cases[0]["source"] and cases[0]["skip"] is None
    assert "extra files" in cases[1]["skip"] and "not to compile" in cases[2]["skip"]


def test_known_limits_are_said_up_front():
    notes = limit_notes([(1, "SPECIAL-NAMES"), (2, "DECIMAL-POINT IS COMMA"), (3, "PROGRAM-ID. a"), (4, "PROGRAM-ID. b"), (5, ">>IF X DEFINED")])
    text = " ".join(notes)
    assert "DECIMAL-POINT IS COMMA" in text and "more than one program" in text and "directives" in text
    assert limit_notes([(1, "PROGRAM-ID. a"), (2, "DISPLAY 1")]) == []
