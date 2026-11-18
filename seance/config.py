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
    "Any number of sequential input and output files, with DD names such as ACCTREC",
    "Programs that only use the console: DISPLAY, and ACCEPT for typed input",
    "Fixed-length records, line sequential text files, and reports written with ADVANCING",
    "Records in the FD, WORKING-STORAGE or copybooks (COPY, COPY REPLACING)",
    "Packed decimal (COMP-3), binary (COMP, COMP-5) and display numbers anywhere, every sign style",
    "OCCURS tables (with DEPENDING ON and INDEXED BY), REDEFINES, groups, FILLER, VALUE, level-88 conditions",
    "Edited pictures such as $$,$$9.99-, ZZ9.99CR and ***,**9.99",
    "MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, IF, EVALUATE, PERFORM in every form, GO TO, ON SIZE ERROR",
    "STRING, UNSTRING, INSPECT, SEARCH and SEARCH ALL, SET, INITIALIZE, reference modification",
    "Intrinsic FUNCTIONs such as CURRENT-DATE, UPPER-CASE, TRIM, NUMVAL, MOD and MAX",
]
NOT_YET = [
    "Indexed or relative files (ORGANIZATION INDEXED or RELATIVE)",
    "SORT and MERGE",
    "Embedded SQL (EXEC SQL) and CICS",
    "CALL to another program",
    "REPORT SECTION and SCREEN SECTION",
    "Floating point (COMP-1, COMP-2) and P scaling in pictures",
]
