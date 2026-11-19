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
MAX_DATA_RECORDS = _int("SEANCE_MAX_DATA_RECORDS", 5000)  # records per uploaded test-data file
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
    "OCCURS (DEPENDING ON, INDEXED BY), REDEFINES, groups, level-88 conditions, COPY and COPY REPLACING",
    "Edited pictures such as $$,$$9.99-, ZZ9.99CR and ***,**9.99",
    "MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, IF, EVALUATE, PERFORM in every form, GO TO, NEXT SENTENCE, ON SIZE ERROR",
    "STRING, UNSTRING, INSPECT, SEARCH, SEARCH ALL, SET, INITIALIZE, reference modification, intrinsic FUNCTIONs",
    "Mainframe data files in EBCDIC, converted field by field from the record layout",
]
NOT_YET = [
    "Embedded SQL (EXEC SQL), CICS and IMS: they need a database or transaction monitor to run the original",
    "JCL jobs with several steps (each program is checked on its own)",
    "REPORT SECTION and SCREEN SECTION",
    "Floating point (COMP-1, COMP-2) and P scaling in pictures",
    "CALL ... RETURNING and dynamic CALL of programs that are not in the folder",
]
