"""Python translation of legacy/interest/interest.cbl (PROGRAM-ID INTEREST).

Written by the Séance translator on 2026-11-18. The program reads INPUT.DAT, writes OUTPUT.DAT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, Program, StopRun, run_cli

ITEMS = {
    "IN-REC": ['IN-REC', 0, 28, 'group', 'display', 0, 0, False, 'none', '', [], ['IN-ACCT-ID', 'IN-BALANCE', 'IN-RATE', 'IN-DAYS'], False, False],
    "IN-ACCT-ID": ['IN-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "IN-BALANCE": ['IN-REC', 8, 12, 'num', 'display', 11, 2, True, 'leading_sep', 'S999999999V99', [], [], False, False],
    "IN-RATE": ['IN-REC', 20, 5, 'num', 'display', 5, 4, False, 'none', '9V9999', [], [], False, False],
    "IN-DAYS": ['IN-REC', 25, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "OUT-REC": ['OUT-REC', 0, 33, 'group', 'display', 0, 0, False, 'none', '', [], ['OUT-ACCT-ID', 'OUT-INTEREST', 'OUT-NEW-BAL', 'OUT-STATUS'], False, False],
    "OUT-ACCT-ID": ['OUT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "OUT-INTEREST": ['OUT-REC', 8, 12, 'num', 'display', 11, 2, True, 'leading_sep', 'S999999999V99', [], [], False, False],
    "OUT-NEW-BAL": ['OUT-REC', 20, 12, 'num', 'display', 11, 2, True, 'leading_sep', 'S999999999V99', [], [], False, False],
    "OUT-STATUS": ['OUT-REC', 32, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-INT": ['WS-INT', 0, 11, 'num', 'display', 11, 2, True, 'trailing_over', 'S999999999V99', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
}

RECORDS = {'IN-REC': 28, 'OUT-REC': 33, 'WS-EOF': 1, 'WS-INT': 11, '_SPECIAL': 6}

VALUES = [
    ("WS-EOF", 'N', False),
]

CONDITIONS = {

}

FILES = [
    ["IN-FILE", "INPUT.DAT", "line", "IN-REC", 28, None],
    ["OUT-FILE", "OUTPUT.DAT", "line", "OUT-REC", 33, None],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES)


def p_main_para():  # paragraph MAIN-PARA (line 19)
    S.open("IN-FILE", "input"); S.open("OUT-FILE", "output")  # L20
    for _ in S.loop():  # L21
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("IN-FILE"):  # L22
            S.perform("PROCESS-PARA")  # L24
        else:
            S.move('Y', "WS-EOF")  # L23
    S.close("IN-FILE"); S.close("OUT-FILE")  # L27
    raise StopRun()  # L28


def p_process_para():  # paragraph PROCESS-PARA (line 29)
    S.move(S.r("IN-ACCT-ID"), "OUT-ACCT-ID")  # L30
    if (S.cmp(S.r("IN-BALANCE"), ">", D("0"))):  # L31
        S.move('P', "OUT-STATUS")  # L33
        S.compute([("WS-INT", lambda: S.n("IN-BALANCE") * S.n("IN-RATE") * S.n("IN-DAYS") / D("365"), True)], guarded=False)  # L34
        S.compute([("OUT-NEW-BAL", lambda: S.n("IN-BALANCE") + S.n("WS-INT"), False)], guarded=False)  # L35
    elif (S.cmp(S.r("IN-BALANCE"), "<", D("0"))):
        S.move('O', "OUT-STATUS")  # L37
        S.move(D("0"), "WS-INT")  # L38
        S.compute([("OUT-NEW-BAL", lambda: S.n("IN-BALANCE") - D("25.00"), False)], guarded=False)  # L39
    else:
        S.move('Z', "OUT-STATUS")  # L41
        S.move(D("0"), "WS-INT")  # L42
        S.move(D("0"), "OUT-NEW-BAL")  # L43
    S.move(S.r("WS-INT"), "OUT-INTEREST")  # L45
    S.write("OUT-REC", None, None)  # L46


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("PROCESS-PARA", p_process_para),
]
SECTIONS = {}


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, FILES))
