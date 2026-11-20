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


def test_supported_constructs_raise_no_limit_note():
    assert limit_notes([(1, "SPECIAL-NAMES"), (2, "DECIMAL-POINT IS COMMA")]) == [], "DECIMAL-POINT IS COMMA is supported"
    assert limit_notes([(1, "PROGRAM-ID. a"), (2, "DISPLAY 1")]) == []


PRECOMPILED = {
    "compiler directives": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       >>DEFINE LEVEL-NO AS 2
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       >>IF LEVEL-NO = 2
       01  X   PIC X(4) VALUE "TWO ".
       >>ELSE
       01  X   PIC X(4) VALUE "ONE ".
       >>END-IF
       PROCEDURE DIVISION.
       >>IF NOTSET IS DEFINED
           DISPLAY "WRONG".
       >>ELIF LEVEL-NO > 1
           DISPLAY "RIGHT " X.
       >>ELSE
           DISPLAY "ALSO WRONG".
       >>END-IF
       >>IF LEVEL-NO IS NOT DEFINED
           DISPLAY "NOT DEFINED".
       >>ELSE
           DISPLAY "DEFINED".
       >>END-IF
           STOP RUN.
""",
    "REPLACE": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       REPLACE ==LIMIT== BY ==5== ==:TAG:== BY ==WS==.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I    PIC 99.
       01  WS-T    PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > LIMIT
               ADD WS-I TO WS-T
           END-PERFORM
           DISPLAY "SUM " WS-T " LIMIT".
       REPLACE OFF.
           STOP RUN.
""",
    "decimal point is comma": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N     PIC 9(4)V99 VALUE 1234,5.
       01  M     PIC S9(3)V9 VALUE -12,3.
       01  E     PIC Z.ZZ9,99.
       01  F     PIC ---9,9.
       01  T     PIC 9(5)V99.
       PROCEDURE DIVISION.
           DISPLAY N " " M.
           MOVE N TO E. DISPLAY "[" E "]".
           MOVE M TO F. DISPLAY "[" F "]".
           COMPUTE T = N * 1,5.
           DISPLAY T " " 2,25.
           MOVE E TO T. DISPLAY T.
           STOP RUN.
""",
    "named constants": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       78  MAX-ROWS   VALUE 3.
       78  GREETING   VALUE "HELLO".
       78  TWICE      VALUE MAX-ROWS * 2.
       01  T.
           05  ROW    PIC 9(3) OCCURS MAX-ROWS TIMES.
       01  I          PIC 9.
       PROCEDURE DIVISION.
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > MAX-ROWS
               COMPUTE ROW (I) = I * TWICE
           END-PERFORM
           DISPLAY GREETING " " T " " MAX-ROWS.
           STOP RUN.
""",
    "two programs in one file": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  N    PIC 9(3) VALUE 20.
       PROCEDURE DIVISION.
           CALL "doubler" USING N
           DISPLAY "N=" N
           STOP RUN.
       END PROGRAM prog.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. doubler.
       DATA DIVISION.
       LINKAGE SECTION.
       01  V    PIC 9(3).
       PROCEDURE DIVISION USING V.
           COMPUTE V = V * 2
           GOBACK.
       END PROGRAM doubler.
""",
    "DELETE FILE and LENGTH OF": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. prog.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OPTIONAL F ASSIGN TO "WORK.DAT"
               ORGANIZATION LINE SEQUENTIAL FILE STATUS FS.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  F-REC  PIC X(10).
       WORKING-STORAGE SECTION.
       01  FS     PIC XX.
       01  REC    PIC X(17).
       PROCEDURE DIVISION.
           OPEN OUTPUT F
           WRITE F-REC FROM "SOME DATA"
           CLOSE F
           DELETE FILE F
           DISPLAY "DELETE " FS " LENGTH " LENGTH OF REC
           OPEN INPUT F
           DISPLAY "REOPEN " FS
           CLOSE F
           STOP RUN.
""",
}


@pytest.mark.parametrize("label", sorted(PRECOMPILED))
def test_precompiled_programs_match_gnucobol(tmp_path, label):
    src = tmp_path / "prog.cob"
    src.write_text(PRECOMPILED[label], encoding="utf-8")
    result = stress.run_one(src, "stp", tmp_path)
    assert result["stage"] == "match", result
