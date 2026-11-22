"""Settings, read once from the environment. Nothing else in Séance hardcodes these."""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


HOST = os.environ.get("SEANCE_HOST", "127.0.0.1")
PORT = _int("SEANCE_PORT", 8000)
DEFAULT_ROUNDS = _int("SEANCE_ROUNDS", 40)  # random test rounds per check
MAX_ROUNDS = _int("SEANCE_MAX_ROUNDS", 200)
VERIFY_TIMEOUT = _int("SEANCE_VERIFY_TIMEOUT", 600)  # seconds for one check
COMPARE_TIMEOUT = _int("SEANCE_COMPARE_TIMEOUT", 120)
RUN_TIMEOUT = _int("SEANCE_RUN_TIMEOUT", 20)  # seconds for one run of the COBOL on generated input
MUTANTS = _int("SEANCE_MUTANTS", 12)  # planted bugs per test-strength run
MAX_DATA_RECORDS = _int("SEANCE_MAX_DATA_RECORDS", 0)  # records per uploaded test-data file; 0: no limit
RANDOM_RECORDS = _int("SEANCE_RANDOM_RECORDS", 300)  # random records saved when a program is added

# What Séance can read today. Served to the UI and kept in one place so the docs and the product agree.
SUPPORTED = [
    "Fixed-format and free-format source, including IBM-style programs written for z/OS",
    "Sequential, line sequential, indexed (VSAM KSDS style) and relative files, with FILE STATUS and OPTIONAL files",
    "READ by key, READ NEXT, START, WRITE, REWRITE and DELETE, with INVALID KEY and alternate keys",
    "CALL between programs: LINKAGE SECTION, BY REFERENCE and BY CONTENT, GOBACK, CANCEL, IS INITIAL, ON EXCEPTION",
    "SORT and MERGE with USING/GIVING or INPUT/OUTPUT PROCEDURE (RELEASE, RETURN), and SORT of a table",
    "Console programs: DISPLAY, and ACCEPT for typed input",
    "Packed decimal (COMP-3), binary (COMP, COMP-5) and display numbers anywhere, every sign style",
    "OCCURS (DEPENDING ON, INDEXED BY), REDEFINES, RENAMES, groups, level-88 conditions",
    "COPY anywhere (inside entries and statements, nested, OF library) and COPY REPLACING / REPLACE with cobc's own "
    "matching rules, checked word for word against cobc -E",
    "Edited pictures such as $$,$$9.99-, ZZ9.99CR and ***,**9.99",
    "MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, IF, EVALUATE, PERFORM in every form, GO TO, NEXT SENTENCE, ON SIZE ERROR",
    "STRING, UNSTRING, INSPECT, SEARCH, SEARCH ALL, SET, INITIALIZE, CORRESPONDING, ALTER, reference modification",
    "65 intrinsic functions ported from libcob: trigonometry, logarithms, statistics, dates, NUMVAL family, "
    "SUBSTITUTE, CONCATENATE, ORD-MAX, TABLE(ALL) arguments; results typed as libcob types them",
    "SPECIAL-NAMES: switches, CLASS, SYMBOLIC CHARACTERS, ALPHABET (EBCDIC and literal) and PROGRAM COLLATING SEQUENCE",
    "DECLARATIVES (USE AFTER ERROR, USE FOR DEBUGGING), GnuCOBOL's file status codes, SAME RECORD AREA, CLOSE REEL/LOCK",
    "LINAGE, LINAGE-COUNTER and WRITE ... AT END-OF-PAGE (page, footing, top and bottom as libcob lays them out)",
    "READ PREVIOUS and START LAST on indexed and relative files; WRITE record IN file",
    "RECORD VARYING ... DEPENDING ON: the item gives the length written and receives the length read",
    "Mainframe data files in EBCDIC, converted field by field from the record layout",
    "Floating point (COMP-1, COMP-2), P scaling in pictures, and CALL ... RETURNING",
    "Embedded SQL (EXEC SQL: SELECT INTO, cursors, INSERT, UPDATE, DELETE, SQLCA, DSNTIAR), run on SQLite on both sides",
    "CICS transactions (EXEC CICS: files, browse, SEND/RECEIVE, temporary storage, RETURN TRANSID, LINK, XCTL, HANDLE CONDITION), "
    "replayed screen by screen on both sides",
    "JCL jobs: steps that run programs, SORT, IEBGENER and IEFBR14, COND and IF/THEN, temporary data sets passed between steps",
    "Variable-length records (RECORD VARYING, RECORD CONTAINS n TO m)",
    "Compiler directives (>>IF, >>ELIF, >>DEFINE, >>SOURCE FORMAT), REPLACE, level-78 and CONSTANT items, debugging lines WITH DEBUGGING MODE",
    "DECIMAL-POINT IS COMMA, several programs in one source file, DELETE FILE, LENGTH OF",
]
NOT_YET = [
    "IMS databases (EXEC DLI, CALL 'CBLTDLI')",
    "REPORT SECTION (Report Writer) and SCREEN SECTION",
    "POINTER items, ADDRESS OF, and GLOBAL data shared between programs of one file",
    "The exception functions (EXCEPTION-STATUS, EXCEPTION-LOCATION), the FORMATTED-DATE/TIME family and the locale functions",
    "FUNCTION RANDOM without a seed and WHEN-COMPILED translate, but cannot match: the compiled COBOL gives a new value each run",
    "BMS map source (the symbolic map copybook is used instead) and CICS commands outside the list above",
    "Dynamic CALL of programs that are not in the folder, and PROCEDURE DIVISION RETURNING (GnuCOBOL 3.1.2 crashes on it)",
]
