"""Python translation of legacy/add_amounts/add_amounts.cbl (PROGRAM-ID ADDAMT).

Written by the Séance translator on 2026-11-19. The program reads console input.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "KEYED-INPUT": ['KEYED-INPUT', 0, 30, 'group', 'display', 0, 0, False, 'none', '', [], ['CUST-NO-IN', 'AMT1-IN', 'AMT2-IN', 'AMT3-IN'], False, False],
    "CUST-NO-IN": ['KEYED-INPUT', 0, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "AMT1-IN": ['KEYED-INPUT', 15, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "AMT2-IN": ['KEYED-INPUT', 20, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "AMT3-IN": ['KEYED-INPUT', 25, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "DISPLAYED-OUTPUT": ['DISPLAYED-OUTPUT', 0, 21, 'group', 'display', 0, 0, False, 'none', '', [], ['CUST-NO-OUT', 'TOTAL-OUT'], False, False],
    "CUST-NO-OUT": ['DISPLAYED-OUTPUT', 0, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "TOTAL-OUT": ['DISPLAYED-OUTPUT', 15, 6, 'num', 'display', 6, 0, False, 'none', '999999', [], [], False, False],
    "MORE-DATA": ['MORE-DATA', 0, 3, 'alpha', 'display', 0, 0, False, 'none', 'XXX', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'KEYED-INPUT': 30, 'DISPLAYED-OUTPUT': 21, 'MORE-DATA': 3, '_SPECIAL': 10}

VALUES = [
    ("MORE-DATA", 'YES', False),
]

CONDITIONS = {

}

FILES = [

]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_100_main():  # paragraph 100-MAIN (line 23)
    for _ in S.loop():  # L24
        if S.cmp(S.r("MORE-DATA"), "==", 'NO '):
            break
        S.display('ENTER NAME       (15 CHARACTERS)')  # L25
        S.accept("CUST-NO-IN", "console")  # L26
        S.display('Enter amount of first purchase (5 digits)')  # L27
        S.accept("AMT1-IN", "console")  # L28
        S.display('Enter amount of second purchase (5 digits)')  # L29
        S.accept("AMT2-IN", "console")  # L30
        S.display('Enter amount of third purchase (5 digits)')  # L31
        S.accept("AMT3-IN", "console")  # L32
        S.move(S.r("CUST-NO-IN"), "CUST-NO-OUT")  # L33
        S.compute([("TOTAL-OUT", lambda: S.n("AMT1-IN") + S.n("AMT2-IN") + S.n("AMT3-IN"), False)], guarded=False)  # L34
        S.display(S.r("CUST-NO-OUT"), 'Total Amount = ', S.r("TOTAL-OUT"))  # L36
        S.display('MORE INPUT DATA (YES/NO)?')  # L37
        S.accept("MORE-DATA", "console")  # L38
        S.inspect_convert(S.r("MORE-DATA"), 'noyes', 'NOYES', None, None)  # L39
    raise GoBack()  # L41


PARAGRAPHS = [
    ("100-MAIN", p_100_main),
]
SECTIONS = {}


RUN_FILES = []  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
