"""Python translation of legacy/account_report/account_report.cbl (PROGRAM-ID CBL0011).

Written by the Séance translator on 2026-11-18. The program reads ACCTREC, writes PRTLINE.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, Program, StopRun, run_cli

ITEMS = {
    "PRINT-REC": ['PRINT-REC', 0, 62, 'group', 'display', 0, 0, False, 'none', '', [], ['ACCT-NO-O', 'FILLER#23-1', 'LAST-NAME-O', 'FILLER#25-2', 'ACCT-LIMIT-O', 'FILLER#27-3', 'ACCT-BALANCE-O', 'FILLER#29-4'], False, False],
    "ACCT-NO-O": ['PRINT-REC', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "FILLER#23-1": ['PRINT-REC', 8, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "LAST-NAME-O": ['PRINT-REC', 10, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#25-2": ['PRINT-REC', 30, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "ACCT-LIMIT-O": ['PRINT-REC', 32, 13, 'edited', 'display', 0, 0, False, 'none', '$$,$$$,$$9.99', [], [], False, False],
    "FILLER#27-3": ['PRINT-REC', 45, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "ACCT-BALANCE-O": ['PRINT-REC', 47, 13, 'edited', 'display', 0, 0, False, 'none', '$$,$$$,$$9.99', [], [], False, False],
    "FILLER#29-4": ['PRINT-REC', 60, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "ACCT-FIELDS": ['ACCT-FIELDS', 0, 170, 'group', 'display', 0, 0, False, 'none', '', [], ['ACCT-NO', 'ACCT-LIMIT', 'ACCT-BALANCE', 'LAST-NAME', 'FIRST-NAME', 'CLIENT-ADDR', 'RESERVED', 'COMMENTS'], False, False],
    "ACCT-NO": ['ACCT-FIELDS', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "ACCT-LIMIT": ['ACCT-FIELDS', 8, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [], [], False, False],
    "ACCT-BALANCE": ['ACCT-FIELDS', 13, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [], [], False, False],
    "LAST-NAME": ['ACCT-FIELDS', 18, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FIRST-NAME": ['ACCT-FIELDS', 38, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "CLIENT-ADDR": ['ACCT-FIELDS', 53, 60, 'group', 'display', 0, 0, False, 'none', '', [], ['STREET-ADDR', 'CITY-COUNTY', 'USA-STATE'], False, False],
    "STREET-ADDR": ['ACCT-FIELDS', 53, 25, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "CITY-COUNTY": ['ACCT-FIELDS', 78, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "USA-STATE": ['ACCT-FIELDS', 98, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "RESERVED": ['ACCT-FIELDS', 113, 7, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXX', [], [], False, False],
    "COMMENTS": ['ACCT-FIELDS', 120, 50, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FLAGS": ['FLAGS', 0, 1, 'group', 'display', 0, 0, False, 'none', '', [], ['LASTREC'], False, False],
    "LASTREC": ['FLAGS', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "TLIMIT-TBALANCE": ['TLIMIT-TBALANCE', 0, 12, 'group', 'display', 0, 0, False, 'none', '', [], ['TLIMIT', 'TBALANCE'], False, False],
    "TLIMIT": ['TLIMIT-TBALANCE', 0, 6, 'num', 'packed', 11, 2, True, 'none', 'S999999999V99', [], [], False, False],
    "TBALANCE": ['TLIMIT-TBALANCE', 6, 6, 'num', 'packed', 11, 2, True, 'none', 'S999999999V99', [], [], False, False],
    "HEADER-1": ['HEADER-1', 0, 80, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#54-1', 'FILLER#55-2'], False, False],
    "FILLER#54-1": ['HEADER-1', 0, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#55-2": ['HEADER-1', 20, 60, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "HEADER-2": ['HEADER-2', 0, 83, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#58-3', 'HDR-YR', 'FILLER#60-4', 'FILLER#61-5', 'HDR-MO', 'FILLER#63-6', 'FILLER#64-7', 'HDR-DAY', 'FILLER#66-8'], False, False],
    "FILLER#58-3": ['HEADER-2', 0, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "HDR-YR": ['HEADER-2', 5, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "FILLER#60-4": ['HEADER-2', 9, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#61-5": ['HEADER-2', 11, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "HDR-MO": ['HEADER-2', 17, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#63-6": ['HEADER-2', 19, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#64-7": ['HEADER-2', 21, 4, 'alpha', 'display', 0, 0, False, 'none', 'XXXX', [], [], False, False],
    "HDR-DAY": ['HEADER-2', 25, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#66-8": ['HEADER-2', 27, 56, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "HEADER-3": ['HEADER-3', 0, 95, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#69-9', 'FILLER#70-10', 'FILLER#71-11', 'FILLER#72-12', 'FILLER#73-13', 'FILLER#74-14', 'FILLER#75-15', 'FILLER#76-16'], False, False],
    "FILLER#69-9": ['HEADER-3', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "FILLER#70-10": ['HEADER-3', 8, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#71-11": ['HEADER-3', 10, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "FILLER#72-12": ['HEADER-3', 20, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#73-13": ['HEADER-3', 35, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "FILLER#74-14": ['HEADER-3', 41, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "FILLER#75-15": ['HEADER-3', 47, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "FILLER#76-16": ['HEADER-3', 55, 40, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "HEADER-4": ['HEADER-4', 0, 100, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#79-17', 'FILLER#80-18', 'FILLER#81-19', 'FILLER#82-20', 'FILLER#83-21', 'FILLER#84-22', 'FILLER#85-23', 'FILLER#86-24'], False, False],
    "FILLER#79-17": ['HEADER-4', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "FILLER#80-18": ['HEADER-4', 8, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#81-19": ['HEADER-4', 10, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "FILLER#82-20": ['HEADER-4', 20, 15, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#83-21": ['HEADER-4', 35, 10, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXX', [], [], False, False],
    "FILLER#84-22": ['HEADER-4', 45, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "FILLER#85-23": ['HEADER-4', 47, 13, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXX', [], [], False, False],
    "FILLER#86-24": ['HEADER-4', 60, 40, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "TRAILER-1": ['TRAILER-1', 0, 100, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#89-25', 'FILLER#90-26', 'FILLER#91-27', 'FILLER#92-28', 'FILLER#93-29'], False, False],
    "FILLER#89-25": ['TRAILER-1', 0, 31, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#90-26": ['TRAILER-1', 31, 14, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#91-27": ['TRAILER-1', 45, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "FILLER#92-28": ['TRAILER-1', 46, 14, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#93-29": ['TRAILER-1', 60, 40, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "TRAILER-2": ['TRAILER-2', 0, 100, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#96-30', 'FILLER#97-31', 'FILLER#98-32', 'TLIMIT-O', 'FILLER#100-33', 'TBALANCE-O', 'FILLER#102-34'], False, False],
    "FILLER#96-30": ['TRAILER-2', 0, 22, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#97-31": ['TRAILER-2', 22, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "FILLER#98-32": ['TRAILER-2', 30, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "TLIMIT-O": ['TRAILER-2', 31, 14, 'edited', 'display', 0, 0, False, 'none', '$$$,$$$,$$9.99', [], [], False, False],
    "FILLER#100-33": ['TRAILER-2', 45, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "TBALANCE-O": ['TRAILER-2', 46, 14, 'edited', 'display', 0, 0, False, 'none', '$$$,$$$,$$9.99', [], [], False, False],
    "FILLER#102-34": ['TRAILER-2', 60, 40, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "WS-CURRENT-DATE-DATA": ['WS-CURRENT-DATE-DATA', 0, 16, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-CURRENT-DATE', 'WS-CURRENT-TIME'], False, False],
    "WS-CURRENT-DATE": ['WS-CURRENT-DATE-DATA', 0, 8, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-CURRENT-YEAR', 'WS-CURRENT-MONTH', 'WS-CURRENT-DAY'], False, False],
    "WS-CURRENT-YEAR": ['WS-CURRENT-DATE-DATA', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-CURRENT-MONTH": ['WS-CURRENT-DATE-DATA', 4, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "WS-CURRENT-DAY": ['WS-CURRENT-DATE-DATA', 6, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "WS-CURRENT-TIME": ['WS-CURRENT-DATE-DATA', 8, 8, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-CURRENT-HOUR', 'WS-CURRENT-MINUTE', 'WS-CURRENT-SECOND', 'WS-CURRENT-CENTISECOND'], False, False],
    "WS-CURRENT-HOUR": ['WS-CURRENT-DATE-DATA', 8, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "WS-CURRENT-MINUTE": ['WS-CURRENT-DATE-DATA', 10, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "WS-CURRENT-SECOND": ['WS-CURRENT-DATE-DATA', 12, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "WS-CURRENT-CENTISECOND": ['WS-CURRENT-DATE-DATA', 14, 2, 'num', 'display', 2, 0, False, 'none', '99', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'native', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
}

RECORDS = {'PRINT-REC': 62, 'ACCT-FIELDS': 170, 'FLAGS': 1, 'TLIMIT-TBALANCE': 12, 'HEADER-1': 80, 'HEADER-2': 83, 'HEADER-3': 95, 'HEADER-4': 100, 'TRAILER-1': 100, 'TRAILER-2': 100, 'WS-CURRENT-DATE-DATA': 16, '_SPECIAL': 6}

VALUES = [
    ("LASTREC", SPACE, False),
    ("TLIMIT", ZERO, False),
    ("TBALANCE", ZERO, False),
    ("FILLER#54-1", 'Financial Report for', False),
    ("FILLER#55-2", SPACE, False),
    ("FILLER#58-3", 'Year ', False),
    ("FILLER#60-4", SPACE, False),
    ("FILLER#61-5", 'Month ', False),
    ("FILLER#63-6", SPACE, False),
    ("FILLER#64-7", 'Day ', False),
    ("FILLER#66-8", SPACE, False),
    ("FILLER#69-9", 'Account ', False),
    ("FILLER#70-10", SPACE, False),
    ("FILLER#71-11", 'Last Name ', False),
    ("FILLER#72-12", SPACE, False),
    ("FILLER#73-13", 'Limit ', False),
    ("FILLER#74-14", SPACE, False),
    ("FILLER#75-15", 'Balance ', False),
    ("FILLER#76-16", SPACE, False),
    ("FILLER#79-17", '--------', False),
    ("FILLER#80-18", SPACE, False),
    ("FILLER#81-19", '----------', False),
    ("FILLER#82-20", SPACE, False),
    ("FILLER#83-21", '----------', False),
    ("FILLER#84-22", SPACE, False),
    ("FILLER#85-23", '-------------', False),
    ("FILLER#86-24", SPACE, False),
    ("FILLER#89-25", SPACE, False),
    ("FILLER#90-26", '--------------', False),
    ("FILLER#91-27", SPACE, False),
    ("FILLER#92-28", '--------------', False),
    ("FILLER#93-29", SPACE, False),
    ("FILLER#96-30", SPACE, False),
    ("FILLER#97-31", 'Totals =', False),
    ("FILLER#98-32", SPACE, False),
    ("FILLER#100-33", SPACE, False),
    ("FILLER#102-34", SPACE, False),
]

CONDITIONS = {

}

FILES = [
    ["PRINT-LINE", "PRTLINE", "sequential", "PRINT-REC", 62, None],
    ["ACCT-REC", "ACCTREC", "sequential", "ACCT-FIELDS", 170, None],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES)


def p_open_files():  # paragraph OPEN-FILES (line 118)
    S.open("ACCT-REC", "input")  # L119
    S.open("PRINT-LINE", "output")  # L120


def p_write_headers():  # paragraph WRITE-HEADERS (line 122)
    S.move(F.CURRENT_DATE(), "WS-CURRENT-DATE-DATA")  # L123
    S.move(S.r("WS-CURRENT-YEAR"), "HDR-YR")  # L124
    S.move(S.r("WS-CURRENT-MONTH"), "HDR-MO")  # L125
    S.move(S.r("WS-CURRENT-DAY"), "HDR-DAY")  # L126
    S.write("PRINT-REC", S.r("HEADER-1"), None)  # L127
    S.write("PRINT-REC", S.r("HEADER-2"), None)  # L128
    S.move(SPACE, "PRINT-REC")  # L129
    S.write("PRINT-REC", None, ("after", int(D("1"))))  # L130
    S.write("PRINT-REC", S.r("HEADER-3"), None)  # L131
    S.write("PRINT-REC", S.r("HEADER-4"), None)  # L132
    S.move(SPACE, "PRINT-REC")  # L133


def p_read_next_record():  # paragraph READ-NEXT-RECORD (line 135)
    S.perform("READ-RECORD")  # L136
    for _ in S.loop():  # L137
        if S.cmp(S.r("LASTREC"), "==", 'Y'):
            break
        S.perform("LIMIT-BALANCE-TOTAL")  # L138
        S.perform("WRITE-RECORD")  # L139
        S.perform("READ-RECORD")  # L140


def p_write_tlimit_tbalance():  # paragraph WRITE-TLIMIT-TBALANCE (line 143)
    S.move(S.r("TLIMIT"), "TLIMIT-O")  # L144
    S.move(S.r("TBALANCE"), "TBALANCE-O")  # L145
    S.write("PRINT-REC", S.r("TRAILER-1"), None)  # L146
    S.write("PRINT-REC", S.r("TRAILER-2"), None)  # L147


def p_close_stop():  # paragraph CLOSE-STOP (line 149)
    S.close("ACCT-REC")  # L150
    S.close("PRINT-LINE")  # L151
    raise StopRun()  # L152


def p_read_record():  # paragraph READ-RECORD (line 154)
    if S.read("ACCT-REC"):  # L155
        pass
    else:
        S.move('Y', "LASTREC")  # L156


def p_limit_balance_total():  # paragraph LIMIT-BALANCE-TOTAL (line 159)
    S.compute([("TLIMIT", lambda: S.n("TLIMIT") + S.n("ACCT-LIMIT"), False)], guarded=False)  # L160
    S.compute([("TBALANCE", lambda: S.n("TBALANCE") + S.n("ACCT-BALANCE"), False)], guarded=False)  # L161


def p_write_record():  # paragraph WRITE-RECORD (line 164)
    S.move(S.r("ACCT-NO"), "ACCT-NO-O")  # L165
    S.move(S.r("ACCT-LIMIT"), "ACCT-LIMIT-O")  # L166
    S.move(S.r("ACCT-BALANCE"), "ACCT-BALANCE-O")  # L167
    S.move(S.r("LAST-NAME").sub(D("1"), D("1")), S.r("LAST-NAME-O").sub(D("1"), D("1")))  # L169
    S.move(F.LOWER_CASE(S.text(S.r("LAST-NAME").sub(D("2"), D("19")))), S.r("LAST-NAME-O").sub(D("2"), D("19")))  # L170
    S.write("PRINT-REC", None, None)  # L172


PARAGRAPHS = [
    ("OPEN-FILES", p_open_files),
    ("WRITE-HEADERS", p_write_headers),
    ("READ-NEXT-RECORD", p_read_next_record),
    ("WRITE-TLIMIT-TBALANCE", p_write_tlimit_tbalance),
    ("CLOSE-STOP", p_close_stop),
    ("READ-RECORD", p_read_record),
    ("LIMIT-BALANCE-TOTAL", p_limit_balance_total),
    ("WRITE-RECORD", p_write_record),
]
SECTIONS = {}


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, FILES))
