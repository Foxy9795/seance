"""Python translation of legacy/seat_bookings/seat_bookings.cbl (PROGRAM-ID SEATBOOK).

Written by the Séance translator on 2026-11-19. The program reads SEATFILE, reads REQFILE, writes SEATFILE.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "SEAT-REC": ['SEAT-REC', 0, 13, 'group', 'display', 0, 0, False, 'none', '', [], ['S-NAME', 'S-PAID'], False, False],
    "S-NAME": ['SEAT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "S-PAID": ['SEAT-REC', 8, 5, 'num', 'display', 5, 2, False, 'none', '999V99', [], [], False, False],
    "REQ-REC": ['REQ-REC', 0, 17, 'group', 'display', 0, 0, False, 'none', '', [], ['R-ACTION', 'R-SEAT', 'R-NAME', 'R-PAID'], False, False],
    "R-ACTION": ['REQ-REC', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "R-SEAT": ['REQ-REC', 1, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "R-NAME": ['REQ-REC', 4, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "R-PAID": ['REQ-REC', 12, 5, 'num', 'display', 5, 2, False, 'none', '999V99', [], [], False, False],
    "WS-SEAT": ['WS-SEAT', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-FS": ['WS-FS', 0, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-TAKEN": ['WS-TAKEN', 0, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'SEAT-REC': 13, 'REQ-REC': 17, 'WS-SEAT': 4, 'WS-FS': 2, 'WS-EOF': 1, 'WS-TAKEN': 3, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-TAKEN", D("0"), False),
]

CONDITIONS = {

}

FILES = [
    ["SEATS", "SEATFILE", "relative", "SEAT-REC", 13, 'WS-FS', {'access': 'dynamic', 'relkey': 'WS-SEAT'}],
    ["REQS", "REQFILE", "line", "REQ-REC", 17, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 32)
    S.open("SEATS", "io")  # L33
    S.open("REQS", "input")  # L34
    for _ in S.loop():  # L35
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("REQS"):  # L36
            S.perform("ONE-REQUEST")  # L38
        else:
            S.move('Y', "WS-EOF")  # L37
    S.move(D("1"), "WS-SEAT")  # L41
    S.move('N', "WS-EOF")  # L42
    if not S.start("SEATS", ">=", "WS-SEAT"):  # L43
        S.move('Y', "WS-EOF")  # L44
    for _ in S.loop():  # L46
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read_next("SEATS"):  # L47
            S.compute([("WS-TAKEN", lambda: S.n("WS-TAKEN") + D("1"), False)], guarded=False)  # L50
            S.display('SEAT ', S.r("WS-SEAT"), ' ', S.r("S-NAME"), ' ', S.r("S-PAID"))  # L51
        else:
            S.move('Y', "WS-EOF")  # L48
    S.display('TAKEN ', S.r("WS-TAKEN"))  # L54
    S.close("SEATS"); S.close("REQS")  # L55
    raise StopRun()  # L56


def p_one_request():  # paragraph ONE-REQUEST (line 57)
    S.move(S.r("R-SEAT"), "WS-SEAT")  # L58
    if S.cmp(S.r("R-ACTION"), "==", 'B'):  # L59
        S.move(S.r("R-NAME"), "S-NAME")  # L60
        S.move(S.r("R-PAID"), "S-PAID")  # L61
        if not S.write("SEAT-REC", None, None):  # L62
            S.display('TAKEN OR BAD ', S.r("R-SEAT"), ' ', S.r("WS-FS"))  # L63
    else:
        if not S.delete("SEATS"):  # L66
            S.display('NOT BOOKED ', S.r("R-SEAT"), ' ', S.r("WS-FS"))  # L67


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("ONE-REQUEST", p_one_request),
]
SECTIONS = {}


RUN_FILES = [['SEATS', 'SEATFILE'], ['REQS', 'REQFILE']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
