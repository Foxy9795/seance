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
MUTANTS = _int("SEANCE_MUTANTS", 12)  # planted bugs per test-strength run
MAX_DATA_RECORDS = _int("SEANCE_MAX_DATA_RECORDS", 5000)  # records per uploaded test-data file
RANDOM_RECORDS = _int("SEANCE_RANDOM_RECORDS", 300)  # random records saved when a program is added

# What Séance can read today. Served to the UI and kept in one place so the docs and the product agree.
SUPPORTED = [
    "Fixed-format and free-format source",
    "One input file and one output file, any names, including DD names such as ACCTREC",
    "Fixed-length records and line sequential text files",
    "Records in the FD or in copybooks, with COPY",
    "Groups, FILLER, VALUE and level-88 condition names",
    "Text, numbers, decimals and every sign style",
    "Edited pictures such as $$,$$9.99-, ZZ9.99CR and ***,**9.99",
    "COMP and COMP-3 in WORKING-STORAGE",
    "MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE, IF, EVALUATE, PERFORM (UNTIL, VARYING, TIMES), INITIALIZE, SET ... TO TRUE, ON SIZE ERROR",
]
NOT_YET = [
    "COMP or COMP-3 fields inside the record files",
    "OCCURS tables and REDEFINES",
    "Indexed or relative files, or more than one input or output file",
    "Programs that skip records or add header and total lines",
    "GO TO, STRING, UNSTRING, INSPECT, CALL and intrinsic FUNCTIONs (the draft marks them for you)",
]
