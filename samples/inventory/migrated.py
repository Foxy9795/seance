"""Python translation of legacy/inventory/inventory.cbl (PROGRAM-ID INVENTORY).

Written by the Séance translator on 2026-11-19. The program reads INPUT.DAT, writes OUTPUT.DAT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "IN-REC": ['IN-REC', 0, 29, 'group', 'display', 0, 0, False, 'none', '', [], ['IN-SKU', 'IN-ON-HAND', 'IN-RECEIVED', 'IN-SHIPPED', 'IN-REORDER'], False, False],
    "IN-SKU": ['IN-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "IN-ON-HAND": ['IN-REC', 8, 6, 'num', 'display', 5, 0, True, 'leading_sep', 'S99999', [], [], False, False],
    "IN-RECEIVED": ['IN-REC', 14, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "IN-SHIPPED": ['IN-REC', 19, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "IN-REORDER": ['IN-REC', 24, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "OUT-REC": ['OUT-REC', 0, 19, 'group', 'display', 0, 0, False, 'none', '', [], ['OUT-SKU', 'OUT-NEW-ON-HAND', 'OUT-BACKORDER', 'OUT-FLAG'], False, False],
    "OUT-SKU": ['OUT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "OUT-NEW-ON-HAND": ['OUT-REC', 8, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "OUT-BACKORDER": ['OUT-REC', 13, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "OUT-FLAG": ['OUT-REC', 18, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-NET": ['WS-NET', 0, 6, 'num', 'display', 6, 0, True, 'trailing_over', 'S999999', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'IN-REC': 29, 'OUT-REC': 19, 'WS-EOF': 1, 'WS-NET': 6, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
]

CONDITIONS = {

}

FILES = [
    ["IN-FILE", "INPUT.DAT", "line", "IN-REC", 29, None, {'access': 'sequential'}],
    ["OUT-FILE", "OUTPUT.DAT", "line", "OUT-REC", 19, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


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
    S.move(S.r("IN-SKU"), "OUT-SKU")  # L30
    S.compute([("WS-NET", lambda: S.n("IN-ON-HAND") + S.n("IN-RECEIVED") - S.n("IN-SHIPPED"), False)], guarded=False)  # L31
    if S.cmp(S.r("WS-NET"), "<", D("0")):  # L32
        S.compute([("OUT-BACKORDER", lambda: D("0") - S.n("WS-NET"), False)], guarded=False)  # L33
        S.move(D("0"), "OUT-NEW-ON-HAND")  # L34
    else:
        S.move(D("0"), "OUT-BACKORDER")  # L36
        S.move(S.r("WS-NET"), "OUT-NEW-ON-HAND")  # L37
    if S.cmp(S.r("OUT-NEW-ON-HAND"), "<=", S.r("IN-REORDER")):  # L39
        S.move('R', "OUT-FLAG")  # L40
    else:
        S.move(' ', "OUT-FLAG")  # L42
    S.write("OUT-REC", None, None)  # L44


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
