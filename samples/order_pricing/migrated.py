"""Python translation of legacy/order_pricing/order_pricing.cbl (PROGRAM-ID ORDPRICE).

Written by the Séance translator on 2026-11-19. The program reads ORDERIN, writes PRICEOUT, calls COUNTER, PRICER.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "ORDER-REC": ['ORDER-REC', 0, 15, 'group', 'display', 0, 0, False, 'none', '', [], ['O-ID', 'O-QTY', 'O-PRICE', 'O-CODE'], False, False],
    "O-ID": ['ORDER-REC', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "O-QTY": ['ORDER-REC', 5, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "O-PRICE": ['ORDER-REC', 8, 6, 'num', 'display', 6, 2, False, 'none', '9999V99', [], [], False, False],
    "O-CODE": ['ORDER-REC', 14, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "PRICED-REC": ['PRICED-REC', 0, 23, 'group', 'display', 0, 0, False, 'none', '', [], ['P-ID', 'FILLER#22-1', 'P-TOTAL', 'FILLER#24-2', 'P-RC', 'FILLER#26-3', 'P-SEEN'], False, False],
    "P-ID": ['PRICED-REC', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "FILLER#22-1": ['PRICED-REC', 5, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "P-TOTAL": ['PRICED-REC', 6, 10, 'edited', 'display', 0, 0, False, 'none', 'ZZZZZZ9.99', [], [], False, False],
    "FILLER#24-2": ['PRICED-REC', 16, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "P-RC": ['PRICED-REC', 17, 1, 'num', 'display', 1, 0, False, 'none', '9', [], [], False, False],
    "FILLER#26-3": ['PRICED-REC', 18, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "P-SEEN": ['PRICED-REC', 19, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-ARGS": ['WS-ARGS', 0, 19, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-QTY', 'WS-PRICE', 'WS-CODE', 'WS-TOTAL'], False, False],
    "WS-QTY": ['WS-ARGS', 0, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "WS-PRICE": ['WS-ARGS', 3, 6, 'num', 'display', 6, 2, False, 'none', '9999V99', [], [], False, False],
    "WS-CODE": ['WS-ARGS', 9, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-TOTAL": ['WS-ARGS', 10, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
    "WS-SEEN": ['WS-SEEN', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-MISSING": ['WS-MISSING', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-BLANK": ['WS-BLANK', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'ORDER-REC': 15, 'PRICED-REC': 23, 'WS-EOF': 1, 'WS-ARGS': 19, 'WS-SEEN': 4, 'WS-MISSING': 1, 'WS-BLANK': 5, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-MISSING", 'N', False),
    ("WS-BLANK", SPACE, False),
]

CONDITIONS = {

}

FILES = [
    ["ORDERS", "ORDERIN", "line", "ORDER-REC", 15, None, {'access': 'sequential'}],
    ["PRICED", "PRICEOUT", "line", "PRICED-REC", 23, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 39)
    S.open("ORDERS", "input"); S.open("PRICED", "output")  # L40
    for _ in S.loop():  # L41
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("ORDERS"):  # L42
            S.perform("PRICE-ONE")  # L44
        else:
            S.move('Y', "WS-EOF")  # L43
    if not S.call('NOSUCHPG', [("reference", S.r("WS-ARGS"))], on_exception=True):  # L47
        S.move('Y', "WS-MISSING")  # L48
    S.display('MISSING MODULE HANDLED: ', S.r("WS-MISSING"))  # L50
    S.cancel('COUNTER')  # L51
    S.call('COUNTER', [("reference", S.r("WS-SEEN")), ("reference", S.r("WS-BLANK"))])  # L52
    S.display('AFTER CANCEL: ', S.r("WS-SEEN"))  # L53
    S.close("ORDERS"); S.close("PRICED")  # L54
    raise GoBack()  # L55


def p_price_one():  # paragraph PRICE-ONE (line 56)
    S.move(S.r("O-QTY"), "WS-QTY")  # L57
    S.move(S.r("O-PRICE"), "WS-PRICE")  # L58
    S.move(S.r("O-CODE"), "WS-CODE")  # L59
    S.call('PRICER', [("reference", S.r("WS-ARGS"))])  # L60
    S.move(S.r("RETURN-CODE"), "P-RC")  # L61
    S.call('COUNTER', [("reference", S.r("WS-SEEN")), ("content", S.r("O-ID"))])  # L62
    S.move(S.r("O-ID"), "P-ID")  # L64
    S.move(S.r("WS-TOTAL"), "P-TOTAL")  # L65
    S.move(S.r("WS-SEEN"), "P-SEEN")  # L66
    S.write("PRICED-REC", None, None)  # L67


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("PRICE-ONE", p_price_one),
]
SECTIONS = {}


def _program_counter():
    """Called program COUNTER (legacy/order_pricing/counter.cbl). Lines end with # COUNTER Lnn."""
    ITEMS = {
        "LK-SEEN": ['LK-SEEN', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
        "LK-ID": ['LK-ID', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
        "WS-CALLS": ['WS-CALLS', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
        "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
        "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
        "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
    }

    RECORDS = {'LK-SEEN': 4, 'LK-ID': 5, 'WS-CALLS': 4, '_SPECIAL': 10}

    VALUES = [
        ("WS-CALLS", D("0"), False),
    ]

    CONDITIONS = {

    }

    FILES = [

    ]

    INDEXES = []

    S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=['LK-SEEN', 'LK-ID'], initial=False)


    def p_count_it():  # paragraph COUNT-IT (line 11)
        S.compute([("WS-CALLS", lambda: S.n("WS-CALLS") + D("1"), False)], guarded=False)  # COUNTER L12
        S.move(S.r("WS-CALLS"), "LK-SEEN")  # COUNTER L13
        if S.cmp(S.r("LK-ID"), "==", SPACE):  # COUNTER L14
            S.exit_program()  # EXIT PROGRAM  # COUNTER L15
        S.move('XXXXX', "LK-ID")  # COUNTER L17
        S.exit_program()  # EXIT PROGRAM  # COUNTER L18


    PARAGRAPHS = [
        ("COUNT-IT", p_count_it),
    ]
    SECTIONS = {}
    return S, PARAGRAPHS, SECTIONS



def _program_pricer():
    """Called program PRICER (legacy/order_pricing/pricer.cbl). Lines end with # PRICER Lnn."""
    ITEMS = {
        "LK-ARGS": ['LK-ARGS', 0, 19, 'group', 'display', 0, 0, False, 'none', '', [], ['LK-QTY', 'LK-PRICE', 'LK-CODE', 'LK-TOTAL'], False, False],
        "LK-QTY": ['LK-ARGS', 0, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
        "LK-PRICE": ['LK-ARGS', 3, 6, 'num', 'display', 6, 2, False, 'none', '9999V99', [], [], False, False],
        "LK-CODE": ['LK-ARGS', 9, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
        "LK-TOTAL": ['LK-ARGS', 10, 9, 'num', 'display', 9, 2, False, 'none', '9999999V99', [], [], False, False],
        "WS-RATE": ['WS-RATE', 0, 2, 'num', 'display', 2, 2, False, 'none', 'V99', [], [], False, False],
        "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
        "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
        "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
    }

    RECORDS = {'LK-ARGS': 19, 'WS-RATE': 2, '_SPECIAL': 10}

    VALUES = [
        ("WS-RATE", D("0"), False),
    ]

    CONDITIONS = {

    }

    FILES = [

    ]

    INDEXES = []

    S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=['LK-ARGS'], initial=True)


    def p_price_it():  # paragraph PRICE-IT (line 15)
        S.move(D("0"), "RETURN-CODE")  # PRICER L16
        if (S.cmp(S.r("LK-CODE"), "==", 'A')):  # PRICER L17
            S.move(D(".10"), "WS-RATE")  # PRICER L18
        elif (S.cmp(S.r("LK-CODE"), "==", 'B')):
            S.move(D(".25"), "WS-RATE")  # PRICER L19
        elif (S.cmp(S.r("LK-CODE"), "==", ' ')):
            S.move(D("0"), "WS-RATE")  # PRICER L20
        else:
            S.move(D("1"), "RETURN-CODE")  # PRICER L22
            S.move(D("0"), "WS-RATE")  # PRICER L23
        if not S.compute([("LK-TOTAL", lambda: S.n("LK-QTY") * S.n("LK-PRICE") * (D("1") - S.n("WS-RATE")), True)], guarded=True):  # PRICER L25
            S.move(D("0"), "LK-TOTAL")  # PRICER L28
            S.move(D("2"), "RETURN-CODE")  # PRICER L29
        raise GoBack()  # PRICER L31


    PARAGRAPHS = [
        ("PRICE-IT", p_price_it),
    ]
    SECTIONS = {}
    return S, PARAGRAPHS, SECTIONS



S.link({"COUNTER": _program_counter(), "PRICER": _program_pricer()})


RUN_FILES = [['ORDERS', 'ORDERIN'], ['PRICED', 'PRICEOUT']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
