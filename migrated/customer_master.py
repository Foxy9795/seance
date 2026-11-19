"""Python translation of legacy/customer_master/customer_master.cbl (PROGRAM-ID IDXDEMO).

Written by the Séance translator on 2026-11-19. The program reads CUSTMAST, reads TRANSIN, writes CUSTMAST, writes RPTOUT.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "M-REC": ['M-REC', 0, 21, 'group', 'display', 0, 0, False, 'none', '', [], ['M-ID', 'M-REGION', 'M-BALANCE', 'M-NAME'], False, False],
    "M-ID": ['M-REC', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "M-REGION": ['M-REC', 5, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "M-BALANCE": ['M-REC', 7, 4, 'num', 'packed', 7, 2, True, 'none', 'S99999V99', [], [], False, False],
    "M-NAME": ['M-REC', 11, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "T-REC": ['T-REC', 0, 26, 'group', 'display', 0, 0, False, 'none', '', [], ['T-ACTION', 'T-ID', 'T-REGION', 'T-AMOUNT', 'T-NAME'], False, False],
    "T-ACTION": ['T-REC', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "T-ID": ['T-REC', 1, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "T-REGION": ['T-REC', 6, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "T-AMOUNT": ['T-REC', 8, 8, 'num', 'display', 7, 2, True, 'leading_sep', 'S99999V99', [], [], False, False],
    "T-NAME": ['T-REC', 16, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "RPT-LINE": ['RPT-LINE', 0, 60, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "WS-FS": ['WS-FS', 0, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-SHOWN": ['WS-SHOWN', 0, 9, 'edited', 'display', 0, 0, False, 'none', '-----9.99', [], [], False, False],
    "WS-COUNTS": ['WS-COUNTS', 0, 12, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-ADDED', 'WS-CHANGED', 'WS-DELETED', 'WS-REJECTS'], False, False],
    "WS-ADDED": ['WS-COUNTS', 0, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "WS-CHANGED": ['WS-COUNTS', 3, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "WS-DELETED": ['WS-COUNTS', 6, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "WS-REJECTS": ['WS-COUNTS', 9, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'M-REC': 21, 'T-REC': 26, 'RPT-LINE': 60, 'WS-FS': 2, 'WS-EOF': 1, 'WS-SHOWN': 9, 'WS-COUNTS': 12, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-ADDED", D("0"), False),
    ("WS-CHANGED", D("0"), False),
    ("WS-DELETED", D("0"), False),
    ("WS-REJECTS", D("0"), False),
]

CONDITIONS = {

}

FILES = [
    ["MASTER", "CUSTMAST", "indexed", "M-REC", 21, 'WS-FS', {'access': 'dynamic', 'key': 'M-ID', 'alt': [['M-REGION', True]]}],
    ["TRANS", "TRANSIN", "line", "T-REC", 26, None, {'access': 'sequential'}],
    ["REPORT-OUT", "RPTOUT", "line", "RPT-LINE", 60, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 45)
    S.open("MASTER", "io")  # L46
    if S.cmp(S.r("WS-FS"), "!=", '00'):  # L47
        S.display('OPEN FAILED ', S.r("WS-FS"))  # L48
        raise StopRun()  # L49
    S.open("TRANS", "input"); S.open("REPORT-OUT", "output")  # L51
    for _ in S.loop():  # L52
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("TRANS"):  # L53
            S.perform("APPLY-ONE")  # L55
        else:
            S.move('Y', "WS-EOF")  # L54
    S.perform("LIST-BY-REGION")  # L58
    S.display('ADDED ', S.r("WS-ADDED"), ' CHANGED ', S.r("WS-CHANGED"), ' DELETED ', S.r("WS-DELETED"), ' REJECTED ', S.r("WS-REJECTS"))  # L59
    S.close("MASTER"); S.close("TRANS"); S.close("REPORT-OUT")  # L61
    raise StopRun()  # L62


def p_apply_one():  # paragraph APPLY-ONE (line 63)
    S.move(S.r("T-ID"), "M-ID")  # L64
    if (S.cmp(S.r("T-ACTION"), "==", 'A')):  # L65
        S.move(S.r("T-REGION"), "M-REGION")  # L67
        S.move(S.r("T-AMOUNT"), "M-BALANCE")  # L68
        S.move(S.r("T-NAME"), "M-NAME")  # L69
        if not S.write("M-REC", None, None):  # L70
            S.compute([("WS-REJECTS", lambda: S.n("WS-REJECTS") + D("1"), False)], guarded=False)  # L71
        else:
            S.compute([("WS-ADDED", lambda: S.n("WS-ADDED") + D("1"), False)], guarded=False)  # L72
    elif (S.cmp(S.r("T-ACTION"), "==", 'C')):
        if S.read("MASTER"):  # L75
            S.compute([("M-BALANCE", lambda: S.n("M-BALANCE") + S.n("T-AMOUNT"), False)], guarded=False)  # L78
            S.rewrite("M-REC", None)  # L79
            S.compute([("WS-CHANGED", lambda: S.n("WS-CHANGED") + D("1"), False)], guarded=False)  # L80
        else:
            S.compute([("WS-REJECTS", lambda: S.n("WS-REJECTS") + D("1"), False)], guarded=False)  # L76
    elif (S.cmp(S.r("T-ACTION"), "==", 'D')):
        if not S.delete("MASTER"):  # L83
            S.compute([("WS-REJECTS", lambda: S.n("WS-REJECTS") + D("1"), False)], guarded=False)  # L84
        else:
            S.compute([("WS-DELETED", lambda: S.n("WS-DELETED") + D("1"), False)], guarded=False)  # L85
    else:
        S.compute([("WS-REJECTS", lambda: S.n("WS-REJECTS") + D("1"), False)], guarded=False)  # L88


def p_list_by_region():  # paragraph LIST-BY-REGION (line 90)
    S.move(LOW, "M-REGION")  # L91
    if not S.start("MASTER", ">=", "M-REGION"):  # L92
        S.move('Y', "WS-EOF")  # L93
    else:
        S.move('N', "WS-EOF")  # L94
    for _ in S.loop():  # L96
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read_next("MASTER"):  # L97
            S.move(S.r("M-BALANCE"), "WS-SHOWN")  # L100
            S.move(SPACE, "RPT-LINE")  # L101
            S.string([(S.r("M-REGION"), None), (' ', None), (S.r("M-ID"), None), (' ', None), (S.r("M-NAME"), None), (' ', None), (S.r("WS-SHOWN"), None), (' ', None), (S.r("WS-FS"), None)], S.r("RPT-LINE"), None)  # L102
            S.write("RPT-LINE", None, None)  # L104
        else:
            S.move('Y', "WS-EOF")  # L98


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("APPLY-ONE", p_apply_one),
    ("LIST-BY-REGION", p_list_by_region),
]
SECTIONS = {}


RUN_FILES = [['MASTER', 'CUSTMAST'], ['TRANS', 'TRANSIN'], ['REPORT-OUT', 'RPTOUT']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
