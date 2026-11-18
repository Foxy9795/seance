"""Python translation of legacy/table_search/table_search.cbl (PROGRAM-ID SRCHBIN).

Written by the Séance translator on 2026-11-18. The program reads ACCTREC.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, Program, StopRun, run_cli

ITEMS = {
    "ACCT-FIELDS": ['ACCT-FIELDS', 0, 170, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FLAGS": ['FLAGS', 0, 5, 'group', 'display', 0, 0, False, 'none', '', [], ['LASTREC', 'TABLE-VAR', 'TABLE-MAX'], False, False],
    "LASTREC": ['FLAGS', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "TABLE-VAR": ['FLAGS', 1, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "TABLE-MAX": ['FLAGS', 3, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "ACCT-TABLE": ['ACCT-TABLE', 0, 7650, 'group', 'display', 0, 0, False, 'none', '', [], ['ACCT-TABLE-ITEM'], False, False],
    "ACCT-TABLE-ITEM": ['ACCT-TABLE', 0, 170, 'group', 'display', 0, 0, False, 'none', '', [(45, 170)], ['ACCT-NO', 'ACCT-LIMIT', 'ACCT-BALANCE', 'LAST-NAME', 'FIRST-NAME', 'CLIENT-ADDR', 'RESERVED', 'COMMENTS'], False, False],
    "ACCT-NO": ['ACCT-TABLE', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [(45, 170)], [], False, False],
    "ACCT-LIMIT": ['ACCT-TABLE', 8, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [(45, 170)], [], False, False],
    "ACCT-BALANCE": ['ACCT-TABLE', 13, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [(45, 170)], [], False, False],
    "LAST-NAME": ['ACCT-TABLE', 18, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "FIRST-NAME": ['ACCT-TABLE', 38, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "CLIENT-ADDR": ['ACCT-TABLE', 53, 60, 'group', 'display', 0, 0, False, 'none', '', [(45, 170)], ['STREET-ADDR', 'CITY-COUNTY', 'USA-STATE'], False, False],
    "STREET-ADDR": ['ACCT-TABLE', 53, 25, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "CITY-COUNTY": ['ACCT-TABLE', 78, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "USA-STATE": ['ACCT-TABLE', 98, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "RESERVED": ['ACCT-TABLE', 113, 7, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXX', [(45, 170)], [], False, False],
    "COMMENTS": ['ACCT-TABLE', 120, 50, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [(45, 170)], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
}

RECORDS = {'ACCT-FIELDS': 170, 'FLAGS': 5, 'ACCT-TABLE': 7650, '_SPECIAL': 6}

VALUES = [
    ("LASTREC", SPACE, False),
    ("TABLE-MAX", D("45"), False),
]

CONDITIONS = {
    "END-OF-FILE": ("LASTREC", [('Y', None)]),
}

FILES = [
    ["ACCT-REC", "ACCTREC", "sequential", "ACCT-FIELDS", 170, None],
]

INDEXES = ['TABLE-IDX']

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES)


def p_open_files():  # paragraph OPEN-FILES (line 47)
    S.open("ACCT-REC", "input")  # L48


def p_load_tables():  # paragraph LOAD-TABLES (line 50)
    S.perform("READ-RECORD")  # L51
    pass  # L52  # PERFORM VARYING
    S.compute([("TABLE-VAR", lambda: D("1"), False)])
    for _ in S.loop():
        if S.cmp(S.r("TABLE-VAR"), "==", S.r("TABLE-MAX")) or S.cond("END-OF-FILE"):
            break
        S.move(S.r("ACCT-FIELDS"), S.r("ACCT-TABLE-ITEM", int(S.n("TABLE-VAR"))))  # L54
        S.perform("READ-RECORD")  # L55
        S.compute([("TABLE-VAR", lambda: S.n("TABLE-VAR") + D("1"), False)])


def p_search_record():  # paragraph SEARCH-RECORD (line 58)
    S.set_index("TABLE-IDX", int(D("1")))  # L59
    S.set_index("TABLE-IDX", 1)  # SEARCH ALL: the table is in key order, so the first match is the match  # L60
    for _ in S.loop():  # L60
        if S.idx_value("TABLE-IDX") > 45:
            S.display('Not Found')  # L61
            break
        if S.cmp(S.r("ACCT-NO", S.idx_value("TABLE-IDX")), "==", D("18011809")):
            S.display('User with Acct No 18011809 is found!')  # L63
            break
        S.set_index("TABLE-IDX", S.idx_value("TABLE-IDX") + 1)


def p_close_stop():  # paragraph CLOSE-STOP (line 65)
    S.close("ACCT-REC")  # L66
    raise StopRun()  # L67


def p_read_record():  # paragraph READ-RECORD (line 69)
    if S.read("ACCT-REC"):  # L70
        pass
    else:
        S.set_true("END-OF-FILE")  # L71


PARAGRAPHS = [
    ("OPEN-FILES", p_open_files),
    ("LOAD-TABLES", p_load_tables),
    ("SEARCH-RECORD", p_search_record),
    ("CLOSE-STOP", p_close_stop),
    ("READ-RECORD", p_read_record),
]
SECTIONS = {}


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, FILES))
