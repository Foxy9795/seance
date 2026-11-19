"""Python translation of legacy/accounts/accounts.cbl (PROGRAM-ID ACCOUNTS).

Written by the Séance translator on 2026-11-19. The program reads ACCTIN, writes ACCTOUT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "ACCT-REC": ['ACCT-REC', 0, 38, 'group', 'display', 0, 0, False, 'none', '', [], ['ACCT-NO', 'ACCT-BALANCE', 'ACCT-LIMIT', 'ACCT-RATE', 'ACCT-TYPE', 'ACCT-MONTHS', 'FILLER#11-1'], False, False],
    "ACCT-NO": ['ACCT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "ACCT-BALANCE": ['ACCT-REC', 8, 9, 'num', 'display', 9, 2, True, 'trailing_over', 'S9999999V99', [], [], False, False],
    "ACCT-LIMIT": ['ACCT-REC', 17, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
    "ACCT-RATE": ['ACCT-REC', 26, 4, 'num', 'display', 4, 4, False, 'none', 'V9999', [], [], False, False],
    "ACCT-TYPE": ['ACCT-REC', 30, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "ACCT-MONTHS": ['ACCT-REC', 31, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "FILLER#11-1": ['ACCT-REC', 33, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "OUT-REC": ['OUT-REC', 0, 53, 'group', 'display', 0, 0, False, 'none', '', [], ['OUT-ACCT-NO', 'OUT-NEW-BAL', 'OUT-FEE', 'OUT-INTEREST', 'OUT-STATUS', 'OUT-SHOWN'], False, False],
    "OUT-ACCT-NO": ['OUT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "OUT-NEW-BAL": ['OUT-REC', 8, 9, 'num', 'display', 9, 2, True, 'trailing_over', 'S9999999V99', [], [], False, False],
    "OUT-FEE": ['OUT-REC', 17, 5, 'num', 'display', 5, 2, False, 'none', '999V99', [], [], False, False],
    "OUT-INTEREST": ['OUT-REC', 22, 7, 'num', 'display', 7, 2, False, 'none', '99999V99', [], [], False, False],
    "OUT-STATUS": ['OUT-REC', 29, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "OUT-SHOWN": ['OUT-REC', 39, 14, 'edited', 'display', 0, 0, False, 'none', '$$,$$$,$$9.99-', [], [], False, False],
    "WS-FLAGS": ['WS-FLAGS', 0, 1, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-EOF'], False, False],
    "WS-EOF": ['WS-FLAGS', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-WORK": ['WS-WORK', 0, 24, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-BAL', 'WS-MONTH-RATE', 'WS-I', 'WS-COUNT'], False, False],
    "WS-BAL": ['WS-WORK', 0, 7, 'num', 'packed', 13, 4, True, 'none', 'S999999999V9999', [], [], False, False],
    "WS-MONTH-RATE": ['WS-WORK', 7, 7, 'num', 'display', 7, 6, False, 'none', '9V999999', [], [], False, False],
    "WS-I": ['WS-WORK', 14, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "WS-COUNT": ['WS-WORK', 17, 7, 'num', 'display', 7, 0, False, 'none', '9999999', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'ACCT-REC': 38, 'OUT-REC': 53, 'WS-FLAGS': 1, 'WS-WORK': 24, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-COUNT", ZERO, False),
]

CONDITIONS = {
    "SAVINGS": ("ACCT-TYPE", [('S', None)]),
    "CHECKING": ("ACCT-TYPE", [('C', None)]),
    "END-OF-FILE": ("WS-EOF", [('Y', None)]),
}

FILES = [
    ["ACCT-IN", "ACCTIN", "sequential", "ACCT-REC", 38, None, {'access': 'sequential'}],
    ["ACCT-OUT", "ACCTOUT", "sequential", "OUT-REC", 53, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_0000_main():  # paragraph 0000-MAIN (line 32)
    S.open("ACCT-IN", "input"); S.open("ACCT-OUT", "output")  # L33
    S.perform("8000-READ")  # L35
    for _ in S.loop():  # L36
        if S.cond("END-OF-FILE"):
            break
        S.perform("1000-PROCESS")  # L36
    S.close("ACCT-IN"); S.close("ACCT-OUT")  # L37
    raise GoBack()  # L38


def p_1000_process():  # paragraph 1000-PROCESS (line 39)
    S.initialize("OUT-REC")  # L40
    S.move(S.r("ACCT-NO"), "OUT-ACCT-NO")  # L41
    S.move(S.r("ACCT-BALANCE"), "WS-BAL")  # L42
    S.compute([("WS-COUNT", lambda: S.n("WS-COUNT") + D("1"), False)], guarded=False)  # L43
    if (S.cond("SAVINGS")):  # L44
        S.perform("2000-INTEREST")  # L46
    elif (S.cond("CHECKING")):
        S.perform("3000-FEE")  # L48
    else:
        S.move('UNKNOWN', "OUT-STATUS")  # L50
    if S.cmp(S.r("WS-BAL"), "<", ZERO):  # L52
        if S.cmp(D("0") - S.n("WS-BAL"), ">", S.r("ACCT-LIMIT")):  # L53
            S.move('OVER-LIMIT', "OUT-STATUS")  # L54
        else:
            S.move('OVERDRAWN', "OUT-STATUS")  # L56
    else:
        if S.cmp(S.r("OUT-STATUS"), "==", SPACE):  # L59
            S.move('OK', "OUT-STATUS")  # L60
    S.compute([("OUT-NEW-BAL", lambda: S.n("WS-BAL"), False)], guarded=False)  # L63
    S.move(S.r("OUT-NEW-BAL"), "OUT-SHOWN")  # L64
    S.write("OUT-REC", None, None)  # L65
    S.perform("8000-READ")  # L66


def p_2000_interest():  # paragraph 2000-INTEREST (line 67)
    S.compute([("WS-MONTH-RATE", lambda: S.n("ACCT-RATE") / D("12"), False)], guarded=False)  # L68
    pass  # L69  # PERFORM VARYING
    S.compute([("WS-I", lambda: D("1"), False)])
    for _ in S.loop():
        if S.cmp(S.r("WS-I"), ">", S.r("ACCT-MONTHS")):
            break
        S.compute([("WS-BAL", lambda: S.n("WS-BAL") * (D("1") + S.n("WS-MONTH-RATE")), True)], guarded=False)  # L70
        S.compute([("WS-I", lambda: S.n("WS-I") + D("1"), False)])
    if not S.compute([("OUT-INTEREST", lambda: S.n("WS-BAL") - S.n("ACCT-BALANCE"), True)], guarded=True):  # L72
        S.move(D("99999.99"), "OUT-INTEREST")  # L73


def p_3000_fee():  # paragraph 3000-FEE (line 75)
    if (S.cmp(S.r("WS-BAL"), ">=", D("2500"))):  # L76
        S.move(D("0"), "OUT-FEE")  # L78
    elif (S.cmp(S.r("WS-BAL"), ">=", D("500"))):
        S.move(D("4.50"), "OUT-FEE")  # L80
    else:
        S.move(D("12.00"), "OUT-FEE")  # L82
    S.compute([("WS-BAL", lambda: S.n("WS-BAL") - (S.n("OUT-FEE")), False)], guarded=False)  # L84


def p_8000_read():  # paragraph 8000-READ (line 85)
    if S.read("ACCT-IN"):  # L86
        pass
    else:
        S.set_true("END-OF-FILE")  # L87


PARAGRAPHS = [
    ("0000-MAIN", p_0000_main),
    ("1000-PROCESS", p_1000_process),
    ("2000-INTEREST", p_2000_interest),
    ("3000-FEE", p_3000_fee),
    ("8000-READ", p_8000_read),
]
SECTIONS = {}


RUN_FILES = [['ACCT-IN', 'ACCTIN'], ['ACCT-OUT', 'ACCTOUT']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
