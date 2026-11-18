"""Python translation of legacy/loan/loan.cbl (PROGRAM-ID LOAN).

Written by the Séance translator on 2026-11-18. The program reads INPUT.DAT, writes OUTPUT.DAT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, Program, StopRun, run_cli

ITEMS = {
    "IN-REC": ['IN-REC', 0, 25, 'group', 'display', 0, 0, False, 'none', '', [], ['IN-LOAN-ID', 'IN-PRINCIPAL', 'IN-RATE', 'IN-TERM'], False, False],
    "IN-LOAN-ID": ['IN-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "IN-PRINCIPAL": ['IN-REC', 8, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
    "IN-RATE": ['IN-REC', 17, 5, 'num', 'display', 5, 4, False, 'none', '9V9999', [], [], False, False],
    "IN-TERM": ['IN-REC', 22, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "OUT-REC": ['OUT-REC', 0, 29, 'group', 'display', 0, 0, False, 'none', '', [], ['OUT-LOAN-ID', 'OUT-PAYMENT', 'OUT-INTEREST', 'OUT-STATUS'], False, False],
    "OUT-LOAN-ID": ['OUT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "OUT-PAYMENT": ['OUT-REC', 8, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
    "OUT-INTEREST": ['OUT-REC', 17, 11, 'num', 'display', 10, 2, True, 'leading_sep', 'S99999999V99', [], [], False, False],
    "OUT-STATUS": ['OUT-REC', 28, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-R": ['WS-R', 0, 11, 'num', 'display', 11, 10, False, 'none', '9V9999999999', [], [], False, False],
    "WS-PAY": ['WS-PAY', 0, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
}

RECORDS = {'IN-REC': 25, 'OUT-REC': 29, 'WS-EOF': 1, 'WS-R': 11, 'WS-PAY': 9, '_SPECIAL': 6}

VALUES = [
    ("WS-EOF", 'N', False),
]

CONDITIONS = {

}

FILES = [
    ["IN-FILE", "INPUT.DAT", "line", "IN-REC", 25, None],
    ["OUT-FILE", "OUTPUT.DAT", "line", "OUT-REC", 29, None],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES)


def p_main_para():  # paragraph MAIN-PARA (line 21)
    S.open("IN-FILE", "input"); S.open("OUT-FILE", "output")  # L22
    for _ in S.loop():  # L23
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("IN-FILE"):  # L24
            S.perform("PROCESS-PARA")  # L26
        else:
            S.move('Y', "WS-EOF")  # L25
    S.close("IN-FILE"); S.close("OUT-FILE")  # L29
    raise StopRun()  # L30


def p_process_para():  # paragraph PROCESS-PARA (line 31)
    S.move(S.r("IN-LOAN-ID"), "OUT-LOAN-ID")  # L32
    S.move('K', "OUT-STATUS")  # L33
    S.move(D("0"), "WS-PAY")  # L34
    S.compute([("WS-R", lambda: S.n("IN-RATE") / D("12"), False)], guarded=False)  # L35
    if S.cmp(S.r("IN-RATE"), "==", D("0")):  # L36
        if not S.compute([("WS-PAY", lambda: S.n("IN-PRINCIPAL") / S.n("IN-TERM"), True)], guarded=True):  # L37
            S.move('E', "OUT-STATUS")  # L38
    else:
        if not S.compute([("WS-PAY", lambda: S.n("IN-PRINCIPAL") * S.n("WS-R") / (D("1") - (D("1") + S.n("WS-R")) ** (D("0") - S.n("IN-TERM"))), True)], guarded=True):  # L41
            S.move('E', "OUT-STATUS")  # L43
    if S.cmp(S.r("OUT-STATUS"), "==", 'E'):  # L46
        S.move(D("0"), "OUT-PAYMENT")  # L47
        S.move(D("0"), "OUT-INTEREST")  # L48
    else:
        S.move(S.r("WS-PAY"), "OUT-PAYMENT")  # L50
        S.compute([("OUT-INTEREST", lambda: S.n("WS-PAY") * S.n("IN-TERM") - S.n("IN-PRINCIPAL"), False)], guarded=False)  # L51
    S.write("OUT-REC", None, None)  # L53


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
