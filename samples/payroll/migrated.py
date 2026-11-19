"""Python translation of legacy/payroll/payroll.cbl (PROGRAM-ID PAYROLL).

Written by the Séance translator on 2026-11-19. The program reads INPUT.DAT, writes OUTPUT.DAT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "IN-REC": ['IN-REC', 0, 15, 'group', 'display', 0, 0, False, 'none', '', [], ['IN-EMP-ID', 'IN-HOURS', 'IN-RATE'], False, False],
    "IN-EMP-ID": ['IN-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "IN-HOURS": ['IN-REC', 6, 4, 'num', 'display', 4, 1, False, 'none', '999V9', [], [], False, False],
    "IN-RATE": ['IN-REC', 10, 5, 'num', 'display', 5, 2, False, 'none', '999V99', [], [], False, False],
    "OUT-REC": ['OUT-REC', 0, 31, 'group', 'display', 0, 0, False, 'none', '', [], ['OUT-EMP-ID', 'OUT-GROSS', 'OUT-TAX', 'OUT-NET'], False, False],
    "OUT-EMP-ID": ['OUT-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "OUT-GROSS": ['OUT-REC', 6, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "OUT-TAX": ['OUT-REC', 14, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "OUT-NET": ['OUT-REC', 22, 9, 'num', 'display', 8, 2, True, 'leading_sep', 'S999999V99', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-REG": ['WS-REG', 0, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "WS-OT": ['WS-OT', 0, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "WS-GROSS": ['WS-GROSS', 0, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "WS-TAX": ['WS-TAX', 0, 8, 'num', 'display', 8, 2, False, 'none', '999999V99', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'IN-REC': 15, 'OUT-REC': 31, 'WS-EOF': 1, 'WS-REG': 8, 'WS-OT': 8, 'WS-GROSS': 8, 'WS-TAX': 8, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
]

CONDITIONS = {

}

FILES = [
    ["IN-FILE", "INPUT.DAT", "line", "IN-REC", 15, None, {'access': 'sequential'}],
    ["OUT-FILE", "OUTPUT.DAT", "line", "OUT-REC", 31, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 23)
    S.open("IN-FILE", "input"); S.open("OUT-FILE", "output")  # L24
    for _ in S.loop():  # L25
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("IN-FILE"):  # L26
            S.perform("PROCESS-PARA")  # L28
        else:
            S.move('Y', "WS-EOF")  # L27
    S.close("IN-FILE"); S.close("OUT-FILE")  # L31
    raise StopRun()  # L32


def p_process_para():  # paragraph PROCESS-PARA (line 33)
    S.move(S.r("IN-EMP-ID"), "OUT-EMP-ID")  # L34
    if S.cmp(S.r("IN-HOURS"), ">", D("40")):  # L35
        S.compute([("WS-REG", lambda: D("40") * S.n("IN-RATE"), True)], guarded=False)  # L36
        S.compute([("WS-OT", lambda: (S.n("IN-HOURS") - D("40")) * S.n("IN-RATE") * D("1.5"), True)], guarded=False)  # L37
    else:
        S.compute([("WS-REG", lambda: S.n("IN-HOURS") * S.n("IN-RATE"), True)], guarded=False)  # L39
        S.move(D("0"), "WS-OT")  # L40
    S.compute([("WS-GROSS", lambda: S.n("WS-REG") + S.n("WS-OT"), False)], guarded=False)  # L42
    if (S.cmp(S.r("WS-GROSS"), "<=", D("500"))):  # L43
        S.compute([("WS-TAX", lambda: S.n("WS-GROSS") * D("0.10"), True)], guarded=False)  # L45
    elif (S.cmp(S.r("WS-GROSS"), "<=", D("1500"))):
        S.compute([("WS-TAX", lambda: D("50") + (S.n("WS-GROSS") - D("500")) * D("0.20"), True)], guarded=False)  # L47
    else:
        S.compute([("WS-TAX", lambda: D("250") + (S.n("WS-GROSS") - D("1500")) * D("0.30"), True)], guarded=False)  # L49
    S.move(S.r("WS-GROSS"), "OUT-GROSS")  # L51
    S.move(S.r("WS-TAX"), "OUT-TAX")  # L52
    if S.cmp(S.r("IN-HOURS"), ">", D("0")):  # L53
        S.compute([("OUT-NET", lambda: S.n("WS-GROSS") - S.n("WS-TAX") - D("12.50"), False)], guarded=False)  # L54
    else:
        S.move(D("0"), "OUT-NET")  # L56
    S.write("OUT-REC", None, None)  # L58


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("PROCESS-PARA", p_process_para),
]
SECTIONS = {}


RUN_FILES = [['IN-FILE', 'INPUT.DAT'], ['OUT-FILE', 'OUTPUT.DAT']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
