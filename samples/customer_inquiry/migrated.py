"""Python translation of legacy/customer_inquiry/customer_inquiry.cbl (PROGRAM-ID CUSTINQ).

Written by the Séance translator on 2026-11-19. The program reads CICSDB, writes CICSDB.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "CIB-OP": ['CIB-OP', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "CIB-NAME": ['CIB-NAME', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "CIB-KEYLEN": ['CIB-KEYLEN', 0, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "CIB-DATALEN": ['CIB-DATALEN', 0, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "CIB-ITEM": ['CIB-ITEM', 0, 5, 'num', 'display', 5, 0, False, 'none', '99999', [], [], False, False],
    "CIB-DUMMY": ['CIB-DUMMY', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "CIB-SAVE-CALEN": ['CIB-SAVE-CALEN', 0, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "CIB-TEXT": ['CIB-TEXT', 0, 2000, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "DFHEIBLK": ['DFHEIBLK', 0, 85, 'group', 'display', 0, 0, False, 'none', '', [], ['EIBTIME', 'EIBDATE', 'EIBTRNID', 'EIBTASKN', 'EIBTRMID', 'DFHEIGDI', 'EIBCPOSN', 'EIBCALEN', 'EIBAID', 'EIBFN', 'EIBRCODE', 'EIBDS', 'EIBREQID', 'EIBRSRCE', 'EIBSYNC', 'EIBFREE', 'EIBRECV', 'EIBSEND', 'EIBATT', 'EIBEOC', 'EIBFMH', 'EIBCOMPL', 'EIBSIG', 'EIBCONF', 'EIBERR', 'EIBERRCD', 'EIBSYNRB', 'EIBNODAT', 'EIBRESP', 'EIBRESP2', 'EIBRLDBK'], False, False],
    "EIBTIME": ['DFHEIBLK', 0, 4, 'num', 'packed', 7, 0, True, 'none', 'S9999999', [], [], False, False],
    "EIBDATE": ['DFHEIBLK', 4, 4, 'num', 'packed', 7, 0, True, 'none', 'S9999999', [], [], False, False],
    "EIBTRNID": ['DFHEIBLK', 8, 4, 'alpha', 'display', 0, 0, False, 'none', 'XXXX', [], [], False, False],
    "EIBTASKN": ['DFHEIBLK', 12, 4, 'num', 'packed', 7, 0, True, 'none', 'S9999999', [], [], False, False],
    "EIBTRMID": ['DFHEIBLK', 16, 4, 'alpha', 'display', 0, 0, False, 'none', 'XXXX', [], [], False, False],
    "DFHEIGDI": ['DFHEIBLK', 20, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "EIBCPOSN": ['DFHEIBLK', 22, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "EIBCALEN": ['DFHEIBLK', 24, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "EIBAID": ['DFHEIBLK', 26, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBFN": ['DFHEIBLK', 27, 2, 'alpha', 'display', 0, 0, False, 'none', 'XX', [], [], False, False],
    "EIBRCODE": ['DFHEIBLK', 29, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "EIBDS": ['DFHEIBLK', 35, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "EIBREQID": ['DFHEIBLK', 43, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "EIBRSRCE": ['DFHEIBLK', 51, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "EIBSYNC": ['DFHEIBLK', 59, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBFREE": ['DFHEIBLK', 60, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBRECV": ['DFHEIBLK', 61, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBSEND": ['DFHEIBLK', 62, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBATT": ['DFHEIBLK', 63, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBEOC": ['DFHEIBLK', 64, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBFMH": ['DFHEIBLK', 65, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBCOMPL": ['DFHEIBLK', 66, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBSIG": ['DFHEIBLK', 67, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBCONF": ['DFHEIBLK', 68, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBERR": ['DFHEIBLK', 69, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBERRCD": ['DFHEIBLK', 70, 4, 'alpha', 'display', 0, 0, False, 'none', 'XXXX', [], [], False, False],
    "EIBSYNRB": ['DFHEIBLK', 74, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBNODAT": ['DFHEIBLK', 75, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "EIBRESP": ['DFHEIBLK', 76, 4, 'num', 'binary', 8, 0, True, 'none', 'S99999999', [], [], False, False],
    "EIBRESP2": ['DFHEIBLK', 80, 4, 'num', 'binary', 8, 0, True, 'none', 'S99999999', [], [], False, False],
    "EIBRLDBK": ['DFHEIBLK', 84, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHAID": ['DFHAID', 0, 30, 'group', 'display', 0, 0, False, 'none', '', [], ['DFHENTER', 'DFHCLEAR', 'DFHPA1', 'DFHPA2', 'DFHPA3', 'DFHPF1', 'DFHPF2', 'DFHPF3', 'DFHPF4', 'DFHPF5', 'DFHPF6', 'DFHPF7', 'DFHPF8', 'DFHPF9', 'DFHPF10', 'DFHPF11', 'DFHPF12', 'DFHPF13', 'DFHPF14', 'DFHPF15', 'DFHPF16', 'DFHPF17', 'DFHPF18', 'DFHPF19', 'DFHPF20', 'DFHPF21', 'DFHPF22', 'DFHPF23', 'DFHPF24', 'DFHNULL'], False, False],
    "DFHENTER": ['DFHAID', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHCLEAR": ['DFHAID', 1, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPA1": ['DFHAID', 2, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPA2": ['DFHAID', 3, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPA3": ['DFHAID', 4, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF1": ['DFHAID', 5, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF2": ['DFHAID', 6, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF3": ['DFHAID', 7, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF4": ['DFHAID', 8, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF5": ['DFHAID', 9, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF6": ['DFHAID', 10, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF7": ['DFHAID', 11, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF8": ['DFHAID', 12, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF9": ['DFHAID', 13, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF10": ['DFHAID', 14, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF11": ['DFHAID', 15, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF12": ['DFHAID', 16, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF13": ['DFHAID', 17, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF14": ['DFHAID', 18, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF15": ['DFHAID', 19, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF16": ['DFHAID', 20, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF17": ['DFHAID', 21, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF18": ['DFHAID', 22, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF19": ['DFHAID', 23, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF20": ['DFHAID', 24, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF21": ['DFHAID', 25, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF22": ['DFHAID', 26, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF23": ['DFHAID', 27, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHPF24": ['DFHAID', 28, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "DFHNULL": ['DFHAID', 29, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "CUSTMI": ['CUSTMI', 0, 26, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#3-1', 'CUSTNOI', 'ACTIONI', 'AMOUNTI'], False, False],
    "FILLER#3-1": ['CUSTMI', 0, 12, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXX', [], [], False, False],
    "CUSTNOI": ['CUSTMI', 12, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "ACTIONI": ['CUSTMI', 18, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "AMOUNTI": ['CUSTMI', 19, 7, 'num', 'display', 7, 2, False, 'none', '99999V99', [], [], False, False],
    "CUSTMO": ['CUSTMI', 0, 26, 'group', 'display', 0, 0, False, 'none', '', [], ['FILLER#8-2', 'CUSTNOO', 'ACTIONO', 'AMOUNTO'], False, False],
    "FILLER#8-2": ['CUSTMI', 0, 12, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXX', [], [], False, False],
    "CUSTNOO": ['CUSTMI', 12, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "ACTIONO": ['CUSTMI', 18, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "AMOUNTO": ['CUSTMI', 19, 7, 'num', 'display', 7, 2, False, 'none', '99999V99', [], [], False, False],
    "CUSTMSG": ['CUSTMSG', 0, 69, 'group', 'display', 0, 0, False, 'none', '', [], ['MSG-CUSTNO', 'FILLER#14-3', 'MSG-NAME', 'FILLER#16-4', 'MSG-BALANCE', 'FILLER#18-5', 'MSG-TEXT'], False, False],
    "MSG-CUSTNO": ['CUSTMSG', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "FILLER#14-3": ['CUSTMSG', 6, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "MSG-NAME": ['CUSTMSG', 7, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "FILLER#16-4": ['CUSTMSG', 27, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "MSG-BALANCE": ['CUSTMSG', 28, 10, 'edited', 'display', 0, 0, False, 'none', '------9.99', [], [], False, False],
    "FILLER#18-5": ['CUSTMSG', 38, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "MSG-TEXT": ['CUSTMSG', 39, 30, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "WS-RESP": ['WS-RESP', 0, 4, 'num', 'binary', 8, 0, True, 'none', 'S99999999', [], [], False, False],
    "WS-CUST-KEY": ['WS-CUST-KEY', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "WS-CUST-REC": ['WS-CUST-REC', 0, 38, 'group', 'display', 0, 0, False, 'none', '', [], ['CUST-NO', 'CUST-NAME', 'CUST-BALANCE', 'CUST-LAST-PAY'], False, False],
    "CUST-NO": ['WS-CUST-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "CUST-NAME": ['WS-CUST-REC', 6, 20, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "CUST-BALANCE": ['WS-CUST-REC', 26, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [], [], False, False],
    "CUST-LAST-PAY": ['WS-CUST-REC', 31, 7, 'num', 'display', 7, 2, False, 'none', '99999V99', [], [], False, False],
    "WS-COUNT-ITEM": ['WS-COUNT-ITEM', 0, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "WS-AUDIT": ['WS-AUDIT', 0, 13, 'group', 'display', 0, 0, False, 'none', '', [], ['AUD-CUSTNO', 'AUD-AMOUNT'], False, False],
    "AUD-CUSTNO": ['WS-AUDIT', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "AUD-AMOUNT": ['WS-AUDIT', 6, 7, 'num', 'display', 7, 2, False, 'none', '99999V99', [], [], False, False],
    "DFHCOMMAREA": ['DFHCOMMAREA', 0, 4, 'group', 'display', 0, 0, False, 'none', '', [], ['CA-STATE', 'CA-SCREENS'], False, False],
    "CA-STATE": ['DFHCOMMAREA', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "CA-SCREENS": ['DFHCOMMAREA', 1, 3, 'num', 'display', 3, 0, False, 'none', '999', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'CIB-OP': 8, 'CIB-NAME': 8, 'CIB-KEYLEN': 5, 'CIB-DATALEN': 5, 'CIB-ITEM': 5, 'CIB-DUMMY': 1, 'CIB-SAVE-CALEN': 2, 'CIB-TEXT': 2000, 'DFHEIBLK': 85, 'DFHAID': 30, 'CUSTMI': 26, 'CUSTMSG': 69, 'WS-RESP': 4, 'WS-CUST-KEY': 6, 'WS-CUST-REC': 38, 'WS-COUNT-ITEM': 2, 'WS-AUDIT': 13, 'DFHCOMMAREA': 4, '_SPECIAL': 10}

VALUES = [
    ("DFHENTER", "'", False),
    ("DFHCLEAR", '_', False),
    ("DFHPA1", '%', False),
    ("DFHPA2", '>', False),
    ("DFHPA3", ',', False),
    ("DFHPF1", '1', False),
    ("DFHPF2", '2', False),
    ("DFHPF3", '3', False),
    ("DFHPF4", '4', False),
    ("DFHPF5", '5', False),
    ("DFHPF6", '6', False),
    ("DFHPF7", '7', False),
    ("DFHPF8", '8', False),
    ("DFHPF9", '9', False),
    ("DFHPF10", ':', False),
    ("DFHPF11", '#', False),
    ("DFHPF12", '@', False),
    ("DFHPF13", 'A', False),
    ("DFHPF14", 'B', False),
    ("DFHPF15", 'C', False),
    ("DFHPF16", 'D', False),
    ("DFHPF17", 'E', False),
    ("DFHPF18", 'F', False),
    ("DFHPF19", 'G', False),
    ("DFHPF20", 'H', False),
    ("DFHPF21", 'I', False),
    ("DFHPF22", '¢', False),
    ("DFHPF23", '.', False),
    ("DFHPF24", '<', False),
    ("DFHNULL", LOW, False),
    ("FILLER#14-3", SPACE, False),
    ("FILLER#16-4", SPACE, False),
    ("FILLER#18-5", SPACE, False),
]

CONDITIONS = {

}

FILES = [

]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p__start_():  # statements before the first paragraph (line 0)
    S.perform("CIB-STMT-0011")  # L26


def p_main_para():  # paragraph MAIN-PARA (line 27)
    if S.cmp(S.r("EIBCALEN"), "==", D("0")):  # L28
        S.move(LOW, "CUSTMO")  # L29
        S.move('ENTER A CUSTOMER NUMBER', "MSG-TEXT")  # L30
        S.perform("SEND-SCREEN")  # L31
        S.move('S', "CA-STATE")  # L32
        S.move(D("0"), "CA-SCREENS")  # L33
        S.perform("CIB-STMT-0001")  # L34
    S.compute([("CA-SCREENS", lambda: S.n("CA-SCREENS") + D("1"), False)], guarded=False)  # L38
    if (S.cmp(S.r("EIBAID"), "==", S.r("DFHPF3"))):  # L40
        S.move('GOODBYE', "MSG-TEXT")  # L42
        S.perform("SEND-SCREEN")  # L43
        S.perform("CIB-STMT-0002")  # L44
    elif (S.cmp(S.r("EIBAID"), "==", S.r("DFHCLEAR"))):
        S.move(SPACE, "CUSTMSG")  # L46
        S.move('SCREEN CLEARED', "MSG-TEXT")  # L47
    elif (S.cmp(S.r("EIBAID"), "==", S.r("DFHENTER"))):
        S.perform("CIB-STMT-0003")  # L49
        if S.cmp(S.r("WS-RESP"), "==", D("0")):  # L52
            S.perform("LOOK-UP")  # L53
        else:
            S.move('NOTHING RECEIVED', "MSG-TEXT")  # L55
    else:
        S.move('INVALID KEY PRESSED', "MSG-TEXT")  # L58
    S.perform("SEND-SCREEN")  # L60
    S.perform("CIB-STMT-0004")  # L61


def p_look_up():  # paragraph LOOK-UP (line 64)
    S.move(S.r("CUSTNOI"), "WS-CUST-KEY", "MSG-CUSTNO")  # L65
    S.perform("CIB-STMT-0005")  # L66
    if (S.cmp(S.r("WS-RESP"), "==", D("0"))):  # L69
        S.move(S.r("CUST-NAME"), "MSG-NAME")  # L71
        if S.cmp(S.r("ACTIONI"), "==", 'P') and S.cmp(S.r("AMOUNTI"), ">", D("0")):  # L72
            S.compute([("CUST-BALANCE", lambda: S.n("CUST-BALANCE") - (S.n("AMOUNTI")), False)], guarded=False)  # L73
            S.move(S.r("AMOUNTI"), "CUST-LAST-PAY")  # L74
            S.perform("CIB-STMT-0006")  # L75
            S.move(S.r("CUST-NO"), "AUD-CUSTNO")  # L78
            S.move(S.r("AMOUNTI"), "AUD-AMOUNT")  # L79
            S.perform("CIB-STMT-0008")  # L80
            S.move('PAYMENT APPLIED', "MSG-TEXT")  # L83
        else:
            S.move('CUSTOMER FOUND', "MSG-TEXT")  # L85
        S.move(S.r("CUST-BALANCE"), "MSG-BALANCE")  # L87
    elif (S.cmp(S.r("WS-RESP"), "==", D("13"))):
        S.move(SPACE, "MSG-NAME")  # L89
        S.move(D("0"), "MSG-BALANCE")  # L90
        S.move('NO SUCH CUSTOMER', "MSG-TEXT")  # L91
    else:
        S.move('FILE ERROR', "MSG-TEXT")  # L93


def p_send_screen():  # paragraph SEND-SCREEN (line 95)
    S.perform("CIB-STMT-0010")  # L96


def p_cib_end_of_program():  # paragraph CIB-END-OF-PROGRAM (line 97)
    raise GoBack()  # L98


def p_cib_stmt_0001():  # paragraph CIB-STMT-0001 (line 99)
    S.move('RETURN', "CIB-OP")  # L100
    S.move('CINQ', "CIB-NAME")  # L101
    S.move(D("0"), "CIB-KEYLEN")  # L102
    S.move(D("4"), "CIB-DATALEN")  # L103
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("DFHCOMMAREA")), ("reference", S.r("CIB-ITEM"))])  # L104
    raise GoBack()  # L107
    pass  # CONTINUE  # L108


def p_cib_stmt_0002():  # paragraph CIB-STMT-0002 (line 109)
    S.move('RETURN', "CIB-OP")  # L110
    S.move(SPACE, "CIB-NAME")  # L111
    S.move(D("0"), "CIB-KEYLEN")  # L112
    S.move(D("0"), "CIB-DATALEN")  # L113
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-ITEM"))])  # L114
    raise GoBack()  # L117
    pass  # CONTINUE  # L118


def p_cib_stmt_0003():  # paragraph CIB-STMT-0003 (line 119)
    S.move('RECEIVE', "CIB-OP")  # L120
    S.move('CUSTM', "CIB-NAME")  # L121
    S.move(D("0"), "CIB-KEYLEN")  # L122
    S.move(D("26"), "CIB-DATALEN")  # L123
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("CUSTMI")), ("reference", S.r("CIB-ITEM"))])  # L124
    S.move(S.r("EIBRESP"), "WS-RESP")  # L127
    pass  # CONTINUE  # L128


def p_cib_stmt_0004():  # paragraph CIB-STMT-0004 (line 129)
    S.move('RETURN', "CIB-OP")  # L130
    S.move('CINQ', "CIB-NAME")  # L131
    S.move(D("0"), "CIB-KEYLEN")  # L132
    S.move(D("4"), "CIB-DATALEN")  # L133
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("DFHCOMMAREA")), ("reference", S.r("CIB-ITEM"))])  # L134
    raise GoBack()  # L137
    pass  # CONTINUE  # L138


def p_cib_stmt_0005():  # paragraph CIB-STMT-0005 (line 139)
    S.move('READ', "CIB-OP")  # L140
    S.move('CUSTFILE', "CIB-NAME")  # L141
    S.move(D("6"), "CIB-KEYLEN")  # L142
    S.move(D("38"), "CIB-DATALEN")  # L143
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("WS-CUST-KEY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("WS-CUST-REC")), ("reference", S.r("CIB-ITEM"))])  # L144
    S.move(S.r("EIBRESP"), "WS-RESP")  # L147
    pass  # CONTINUE  # L148


def p_cib_stmt_0006():  # paragraph CIB-STMT-0006 (line 149)
    S.move('REWRITE', "CIB-OP")  # L150
    S.move('CUSTFILE', "CIB-NAME")  # L151
    S.move(D("0"), "CIB-KEYLEN")  # L152
    S.move(D("38"), "CIB-DATALEN")  # L153
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("WS-CUST-REC")), ("reference", S.r("CIB-ITEM"))])  # L154
    S.move(S.r("EIBRESP"), "WS-RESP")  # L157
    pass  # CONTINUE  # L158


def p_cib_stmt_0007():  # paragraph CIB-STMT-0007 (line 159)
    S.move('ABEND', "CIB-OP")  # L160
    if (S.cmp(S.r("EIBRESP"), "==", D("44"))):  # L161
        S.move('AEYH', "CIB-NAME")  # L162
    else:
        S.move('AEIP', "CIB-NAME")  # L163
    S.move(D("0"), "CIB-KEYLEN", "CIB-DATALEN")  # L165
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-ITEM"))])  # L166
    pass  # CONTINUE  # L169


def p_cib_stmt_0008():  # paragraph CIB-STMT-0008 (line 170)
    S.move('WRITEQTS', "CIB-OP")  # L171
    S.move('PAYAUDIT', "CIB-NAME")  # L172
    S.move(D("0"), "CIB-KEYLEN")  # L173
    S.move(D("13"), "CIB-DATALEN")  # L174
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("WS-AUDIT")), ("reference", S.r("CIB-ITEM"))])  # L175
    S.move(S.r("CIB-ITEM"), "WS-COUNT-ITEM")  # L178
    if S.cmp(S.r("EIBRESP"), "!=", D("0")):  # L179
        S.perform("CIB-STMT-0007")  # L179
        raise GoBack()  # L179
    pass  # CONTINUE  # L180


def p_cib_stmt_0009():  # paragraph CIB-STMT-0009 (line 181)
    S.move('ABEND', "CIB-OP")  # L182
    if (S.cmp(S.r("EIBRESP"), "==", D("16"))):  # L183
        S.move('AEIP', "CIB-NAME")  # L184
    else:
        S.move('AEIP', "CIB-NAME")  # L185
    S.move(D("0"), "CIB-KEYLEN", "CIB-DATALEN")  # L187
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-ITEM"))])  # L188
    pass  # CONTINUE  # L191


def p_cib_stmt_0010():  # paragraph CIB-STMT-0010 (line 192)
    S.move('SEND', "CIB-OP")  # L193
    S.move(SPACE, "CIB-NAME")  # L194
    S.move(D("0"), "CIB-KEYLEN")  # L195
    S.move(D("69"), "CIB-DATALEN")  # L196
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("CUSTMSG")), ("reference", S.r("CIB-ITEM"))])  # L197
    if S.cmp(S.r("EIBRESP"), "!=", D("0")):  # L200
        S.perform("CIB-STMT-0009")  # L200
        raise GoBack()  # L200
    pass  # CONTINUE  # L201


def p_cib_stmt_0011():  # paragraph CIB-STMT-0011 (line 202)
    S.move('ENTRY', "CIB-OP")  # L203
    S.move(SPACE, "CIB-NAME")  # L204
    S.move(D("0"), "CIB-KEYLEN")  # L205
    S.move(D("4"), "CIB-DATALEN")  # L206
    S.call('CICSBRIDGE', [("reference", S.r("DFHEIBLK")), ("reference", S.r("CIB-OP")), ("reference", S.r("CIB-NAME")), ("reference", S.r("CIB-KEYLEN")), ("reference", S.r("CIB-DUMMY")), ("reference", S.r("CIB-DATALEN")), ("reference", S.r("DFHCOMMAREA")), ("reference", S.r("CIB-ITEM"))])  # L207
    pass  # CONTINUE  # L210


PARAGRAPHS = [
    ("(start)", p__start_),
    ("MAIN-PARA", p_main_para),
    ("LOOK-UP", p_look_up),
    ("SEND-SCREEN", p_send_screen),
    ("CIB-END-OF-PROGRAM", p_cib_end_of_program),
    ("CIB-STMT-0001", p_cib_stmt_0001),
    ("CIB-STMT-0002", p_cib_stmt_0002),
    ("CIB-STMT-0003", p_cib_stmt_0003),
    ("CIB-STMT-0004", p_cib_stmt_0004),
    ("CIB-STMT-0005", p_cib_stmt_0005),
    ("CIB-STMT-0006", p_cib_stmt_0006),
    ("CIB-STMT-0007", p_cib_stmt_0007),
    ("CIB-STMT-0008", p_cib_stmt_0008),
    ("CIB-STMT-0009", p_cib_stmt_0009),
    ("CIB-STMT-0010", p_cib_stmt_0010),
    ("CIB-STMT-0011", p_cib_stmt_0011),
]
SECTIONS = {}


RUN_FILES = [['CICSDB', 'CICSDB']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
