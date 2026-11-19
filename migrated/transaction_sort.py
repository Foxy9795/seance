"""Python translation of legacy/transaction_sort/transaction_sort.cbl (PROGRAM-ID SORTDEMO).

Written by the Séance translator on 2026-11-19. The program reads TRANSIN, writes BYACCT, writes BIGONES.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "TRANS-REC": ['TRANS-REC', 0, 15, 'group', 'display', 0, 0, False, 'none', '', [], ['T-ACCT', 'T-AMOUNT', 'T-TYPE', 'T-SEQ'], False, False],
    "T-ACCT": ['TRANS-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "T-AMOUNT": ['TRANS-REC', 6, 4, 'num', 'packed', 7, 2, True, 'none', 'S99999V99', [], [], False, False],
    "T-TYPE": ['TRANS-REC', 10, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "T-SEQ": ['TRANS-REC', 11, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "BY-ACCT-REC": ['BY-ACCT-REC', 0, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "BIG-LINE": ['BIG-LINE', 0, 40, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "SORT-REC": ['SORT-REC', 0, 15, 'group', 'display', 0, 0, False, 'none', '', [], ['S-ACCT', 'S-AMOUNT', 'S-TYPE', 'S-SEQ'], False, False],
    "S-ACCT": ['SORT-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "S-AMOUNT": ['SORT-REC', 6, 4, 'num', 'packed', 7, 2, True, 'none', 'S99999V99', [], [], False, False],
    "S-TYPE": ['SORT-REC', 10, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "S-SEQ": ['SORT-REC', 11, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-COUNT": ['WS-COUNT', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-TOTAL": ['WS-TOTAL', 0, 9, 'num', 'display', 9, 2, True, 'trailing_over', 'S9999999V99', [], [], False, False],
    "WS-SHOWN": ['WS-SHOWN', 0, 10, 'edited', 'display', 0, 0, False, 'none', '------9.99', [], [], False, False],
    "WS-TABLE": ['WS-TABLE', 0, 25, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-ENTRY'], False, False],
    "WS-ENTRY": ['WS-TABLE', 0, 5, 'group', 'display', 0, 0, False, 'none', '', [(5, 5)], ['WS-CODE', 'WS-RANK'], False, False],
    "WS-CODE": ['WS-TABLE', 0, 3, 'alpha', 'display', 0, 0, False, 'none', 'XXX', [(5, 5)], [], False, False],
    "WS-RANK": ['WS-TABLE', 3, 2, 'num', 'display', 2, 0, False, 'none', '99', [(5, 5)], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'TRANS-REC': 15, 'BY-ACCT-REC': 15, 'BIG-LINE': 40, 'SORT-REC': 15, 'WS-EOF': 1, 'WS-COUNT': 4, 'WS-TOTAL': 9, 'WS-SHOWN': 10, 'WS-TABLE': 25, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-COUNT", D("0"), False),
    ("WS-TOTAL", D("0"), False),
]

CONDITIONS = {

}

FILES = [
    ["TRANS-IN", "TRANSIN", "sequential", "TRANS-REC", 15, None, {'access': 'sequential'}],
    ["BY-ACCT", "BYACCT", "sequential", "BY-ACCT-REC", 15, None, {'access': 'sequential'}],
    ["BIG-ONES", "BIGONES", "line", "BIG-LINE", 40, None, {'access': 'sequential'}],
    ["WORK-SORT", "SORTWK1", "sort", "SORT-REC", 15, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 40)
    S.sort("WORK-SORT", [(True, "S-ACCT"), (False, "S-AMOUNT")], using=['TRANS-IN'], giving=['BY-ACCT'])  # L41
    S.sort("WORK-SORT", [(False, "S-AMOUNT")], input_proc=("PICK-CREDITS", None), output_proc=("PRINT-BIG", None))  # L44
    S.move('DOG04CAT02EEL05ANT01BAT02', "WS-TABLE")  # L47
    S.sort_table("WS-ENTRY", [(True, "WS-RANK")])  # L48
    S.display('TABLE ', S.r("WS-TABLE"))  # L49
    S.display('COUNT ', S.r("WS-COUNT"), ' SORT-RETURN ', S.r("SORT-RETURN"))  # L50
    raise StopRun()  # L51


def p_pick_credits():  # paragraph PICK-CREDITS (line 52)
    S.open("TRANS-IN", "input")  # L53
    for _ in S.loop():  # L54
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("TRANS-IN"):  # L55
            if S.cmp(S.r("T-TYPE"), "==", 'C'):  # L58
                S.release("SORT-REC", S.r("TRANS-REC"))  # L59
        else:
            S.move('Y', "WS-EOF")  # L56
    S.close("TRANS-IN")  # L63


def p_print_big():  # paragraph PRINT-BIG (line 64)
    S.open("BIG-ONES", "output")  # L65
    S.move('N', "WS-EOF")  # L66
    for _ in S.loop():  # L67
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.return_("WORK-SORT"):  # L68
            S.compute([("WS-COUNT", lambda: S.n("WS-COUNT") + D("1"), False)], guarded=False)  # L71
            S.compute([("WS-TOTAL", lambda: S.n("WS-TOTAL") + S.n("S-AMOUNT"), False)], guarded=False)  # L72
            if S.cmp(S.r("WS-COUNT"), "<=", D("5")):  # L73
                S.move(S.r("S-AMOUNT"), "WS-SHOWN")  # L74
                S.move(SPACE, "BIG-LINE")  # L75
                S.string([(S.r("S-ACCT"), None), (' ', None), (S.r("WS-SHOWN"), None), (' ', None), (S.r("S-SEQ"), None)], S.r("BIG-LINE"), None)  # L76
                S.write("BIG-LINE", None, None)  # L78
        else:
            S.move('Y', "WS-EOF")  # L69
    S.move(S.r("WS-TOTAL"), "WS-SHOWN")  # L82
    S.move(SPACE, "BIG-LINE")  # L83
    S.string([('TOTAL ', None), (S.r("WS-SHOWN"), None)], S.r("BIG-LINE"), None)  # L84
    S.write("BIG-LINE", None, None)  # L85
    S.close("BIG-ONES")  # L86


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("PICK-CREDITS", p_pick_credits),
    ("PRINT-BIG", p_print_big),
]
SECTIONS = {}


RUN_FILES = [['TRANS-IN', 'TRANSIN'], ['BY-ACCT', 'BYACCT'], ['BIG-ONES', 'BIGONES']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
