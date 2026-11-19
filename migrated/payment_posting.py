"""Python translation of legacy/payment_posting/payment_posting.cbl (PROGRAM-ID PAYPOST).

Written by the Séance translator on 2026-11-19. The program reads PAYIN, reads SQLDB, writes SQLDB.
Run it with main(IO(files={...}, stdin=[...])) or from the command line: python <this file> (see the README).
Each line ends with # Lnn, the COBOL line it came from. Data is kept byte for byte as COBOL lays it out.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from seance.rt import ALL, F, HIGH, IO, LOW, QUOTE, SPACE, ZERO, GoBack, NextSentence, Program, StopRun, run_cli

ITEMS = {
    "PAY-REC": ['PAY-REC', 0, 26, 'group', 'display', 0, 0, False, 'none', '', [], ['PAY-ACCT', 'PAY-OWNER', 'PAY-AMOUNT'], False, False],
    "PAY-ACCT": ['PAY-REC', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "PAY-OWNER": ['PAY-REC', 6, 12, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXX', [], [], False, False],
    "PAY-AMOUNT": ['PAY-REC', 18, 8, 'num', 'display', 7, 2, True, 'leading_sep', 'S99999V99', [], [], False, False],
    "SQLCA": ['SQLCA', 0, 136, 'group', 'display', 0, 0, False, 'none', '', [], ['SQLCAID', 'SQLCABC', 'SQLCODE', 'SQLERRM', 'SQLERRP', 'SQLERRD', 'SQLWARN', 'SQLSTATE'], False, False],
    "SQLCAID": ['SQLCA', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "SQLCABC": ['SQLCA', 8, 4, 'num', 'native', 9, 0, True, 'none', 'S999999999', [], [], False, False],
    "SQLCODE": ['SQLCA', 12, 4, 'num', 'native', 9, 0, True, 'none', 'S999999999', [], [], False, False],
    "SQLERRM": ['SQLCA', 16, 72, 'group', 'display', 0, 0, False, 'none', '', [], ['SQLERRML', 'SQLERRMC'], False, False],
    "SQLERRML": ['SQLCA', 16, 2, 'num', 'native', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "SQLERRMC": ['SQLCA', 18, 70, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "SQLERRP": ['SQLCA', 88, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "SQLERRD": ['SQLCA', 96, 4, 'num', 'native', 9, 0, True, 'none', 'S999999999', [(6, 4)], [], False, False],
    "SQLWARN": ['SQLCA', 120, 11, 'group', 'display', 0, 0, False, 'none', '', [], ['SQLWARN0', 'SQLWARN1', 'SQLWARN2', 'SQLWARN3', 'SQLWARN4', 'SQLWARN5', 'SQLWARN6', 'SQLWARN7', 'SQLWARN8', 'SQLWARN9', 'SQLWARNA'], False, False],
    "SQLWARN0": ['SQLCA', 120, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN1": ['SQLCA', 121, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN2": ['SQLCA', 122, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN3": ['SQLCA', 123, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN4": ['SQLCA', 124, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN5": ['SQLCA', 125, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN6": ['SQLCA', 126, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN7": ['SQLCA', 127, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN8": ['SQLCA', 128, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARN9": ['SQLCA', 129, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLWARNA": ['SQLCA', 130, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "SQLSTATE": ['SQLCA', 131, 5, 'alpha', 'display', 0, 0, False, 'none', 'XXXXX', [], [], False, False],
    "SQB-OP": ['SQB-OP', 0, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "SQB-CURSOR": ['SQB-CURSOR', 0, 30, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "SQB-TEXT": ['SQB-TEXT', 0, 4000, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [], [], False, False],
    "SQB-NPARAM": ['SQB-NPARAM', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "SQB-PARAMS": ['SQB-PARAMS', 0, 16384, 'group', 'display', 0, 0, False, 'none', '', [], ['SQB-PARAM'], False, False],
    "SQB-PARAM": ['SQB-PARAMS', 0, 256, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [(64, 256)], [], False, False],
    "SQB-PNULLS": ['SQB-PNULLS', 0, 64, 'group', 'display', 0, 0, False, 'none', '', [], ['SQB-PNULL'], False, False],
    "SQB-PNULL": ['SQB-PNULLS', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [(64, 1)], [], False, False],
    "SQB-NRES": ['SQB-NRES', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "SQB-RESULTS": ['SQB-RESULTS', 0, 16384, 'group', 'display', 0, 0, False, 'none', '', [], ['SQB-RES'], False, False],
    "SQB-RES": ['SQB-RESULTS', 0, 256, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', [(64, 256)], [], False, False],
    "SQB-RNULLS": ['SQB-RNULLS', 0, 64, 'group', 'display', 0, 0, False, 'none', '', [], ['SQB-RNULL'], False, False],
    "SQB-RNULL": ['SQB-RNULLS', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [(64, 1)], [], False, False],
    "SQB-RLENS": ['SQB-RLENS', 0, 256, 'group', 'display', 0, 0, False, 'none', '', [], ['SQB-RLEN'], False, False],
    "SQB-RLEN": ['SQB-RLENS', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [(64, 4)], [], False, False],
    "SQB-ED0": ['SQB-ED0', 0, 20, 'edited', 'display', 0, 0, False, 'none', '-------------------9', [], [], False, False],
    "SQB-ED1": ['SQB-ED1', 0, 22, 'edited', 'display', 0, 0, False, 'none', '-------------------9.9', [], [], False, False],
    "SQB-ED2": ['SQB-ED2', 0, 23, 'edited', 'display', 0, 0, False, 'none', '-------------------9.99', [], [], False, False],
    "SQB-ED3": ['SQB-ED3', 0, 24, 'edited', 'display', 0, 0, False, 'none', '-------------------9.999', [], [], False, False],
    "SQB-ED4": ['SQB-ED4', 0, 25, 'edited', 'display', 0, 0, False, 'none', '-------------------9.9999', [], [], False, False],
    "SQB-ED5": ['SQB-ED5', 0, 26, 'edited', 'display', 0, 0, False, 'none', '-------------------9.99999', [], [], False, False],
    "SQB-ED6": ['SQB-ED6', 0, 27, 'edited', 'display', 0, 0, False, 'none', '-------------------9.999999', [], [], False, False],
    "SQB-ED7": ['SQB-ED7', 0, 28, 'edited', 'display', 0, 0, False, 'none', '-------------------9.9999999', [], [], False, False],
    "SQB-ED8": ['SQB-ED8', 0, 29, 'edited', 'display', 0, 0, False, 'none', '-------------------9.99999999', [], [], False, False],
    "SQB-ED9": ['SQB-ED9', 0, 30, 'edited', 'display', 0, 0, False, 'none', '-------------------9.999999999', [], [], False, False],
    "DCL-ACCOUNTS": ['DCL-ACCOUNTS', 0, 35, 'group', 'display', 0, 0, False, 'none', '', [], ['ACCTNO', 'OWNER', 'BALANCE', 'CREDIT', 'ACCT-STATUS'], False, False],
    "ACCTNO": ['DCL-ACCOUNTS', 0, 6, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXX', [], [], False, False],
    "OWNER": ['DCL-ACCOUNTS', 6, 12, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXXXXXX', [], [], False, False],
    "BALANCE": ['DCL-ACCOUNTS', 18, 5, 'num', 'packed', 9, 2, True, 'none', 'S9999999V99', [], [], False, False],
    "CREDIT": ['DCL-ACCOUNTS', 23, 4, 'num', 'packed', 7, 2, True, 'none', 'S99999V99', [], [], False, False],
    "ACCT-STATUS": ['DCL-ACCOUNTS', 27, 8, 'alpha', 'display', 0, 0, False, 'none', 'XXXXXXXX', [], [], False, False],
    "WS-EOF": ['WS-EOF', 0, 1, 'alpha', 'display', 0, 0, False, 'none', 'X', [], [], False, False],
    "WS-CREDIT-IND": ['WS-CREDIT-IND', 0, 2, 'num', 'binary', 4, 0, True, 'none', 'S9999', [], [], False, False],
    "WS-COUNTS": ['WS-COUNTS', 0, 16, 'group', 'display', 0, 0, False, 'none', '', [], ['WS-INSERTED', 'WS-UPDATED', 'WS-FLAGGED', 'WS-ERRORS'], False, False],
    "WS-INSERTED": ['WS-COUNTS', 0, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-UPDATED": ['WS-COUNTS', 4, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-FLAGGED": ['WS-COUNTS', 8, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-ERRORS": ['WS-COUNTS', 12, 4, 'num', 'display', 4, 0, False, 'none', '9999', [], [], False, False],
    "WS-SHOWN": ['WS-SHOWN', 0, 11, 'edited', 'display', 0, 0, False, 'none', '-------9.99', [], [], False, False],
    "RETURN-CODE": ['_SPECIAL', 0, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
    "TALLY": ['_SPECIAL', 4, 2, 'num', 'native', 5, 0, False, 'none', '', [], [], False, False],
    "SORT-RETURN": ['_SPECIAL', 6, 4, 'num', 'binary', 9, 0, True, 'none', '', [], [], False, False],
}

RECORDS = {'PAY-REC': 26, 'SQLCA': 136, 'SQB-OP': 8, 'SQB-CURSOR': 30, 'SQB-TEXT': 4000, 'SQB-NPARAM': 4, 'SQB-PARAMS': 16384, 'SQB-PNULLS': 64, 'SQB-NRES': 4, 'SQB-RESULTS': 16384, 'SQB-RNULLS': 64, 'SQB-RLENS': 256, 'SQB-ED0': 20, 'SQB-ED1': 22, 'SQB-ED2': 23, 'SQB-ED3': 24, 'SQB-ED4': 25, 'SQB-ED5': 26, 'SQB-ED6': 27, 'SQB-ED7': 28, 'SQB-ED8': 29, 'SQB-ED9': 30, 'DCL-ACCOUNTS': 35, 'WS-EOF': 1, 'WS-CREDIT-IND': 2, 'WS-COUNTS': 16, 'WS-SHOWN': 11, '_SPECIAL': 10}

VALUES = [
    ("WS-EOF", 'N', False),
    ("WS-INSERTED", D("0"), False),
    ("WS-UPDATED", D("0"), False),
    ("WS-FLAGGED", D("0"), False),
    ("WS-ERRORS", D("0"), False),
]

CONDITIONS = {

}

FILES = [
    ["PAYMENTS", "PAYIN", "line", "PAY-REC", 26, None, {'access': 'sequential'}],
]

INDEXES = []

S = Program(ITEMS, RECORDS, VALUES, CONDITIONS, FILES, INDEXES, linkage=[])


def p_main_para():  # paragraph MAIN-PARA (line 37)
    pass  # CONTINUE  # L38
    S.open("PAYMENTS", "input")  # L39
    for _ in S.loop():  # L40
        if S.cmp(S.r("WS-EOF"), "==", 'Y'):
            break
        if S.read("PAYMENTS"):  # L41
            S.perform("POST-ONE")  # L43
        else:
            S.move('Y', "WS-EOF")  # L42
    S.close("PAYMENTS")  # L46
    S.perform("FLAG-OVER-LIMIT")  # L47
    S.perform("SQB-STMT-0001")  # L48
    if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L48
        return "SQL-FAILED"  # L48  # GO TO
    S.display('INSERTED ', S.r("WS-INSERTED"), ' UPDATED ', S.r("WS-UPDATED"), ' FLAGGED ', S.r("WS-FLAGGED"))  # L49
    raise StopRun()  # L51


def p_post_one():  # paragraph POST-ONE (line 52)
    S.move(S.r("PAY-ACCT"), "ACCTNO")  # L53
    S.perform("SQB-STMT-0002")  # L54
    if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L54
        return "SQL-FAILED"  # L54  # GO TO
    if S.cmp(S.r("SQLCODE"), "==", D("100")):  # L60
        S.move(S.r("PAY-OWNER"), "OWNER")  # L61
        S.move(S.r("PAY-AMOUNT"), "BALANCE")  # L62
        S.move('NEW', "ACCT-STATUS")  # L63
        S.move(D("-1"), "WS-CREDIT-IND")  # L64
        S.perform("SQB-STMT-0003")  # L65
        if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L65
            return "SQL-FAILED"  # L65  # GO TO
        S.compute([("WS-INSERTED", lambda: S.n("WS-INSERTED") + D("1"), False)], guarded=False)  # L71
    else:
        S.compute([("BALANCE", lambda: S.n("BALANCE") + S.n("PAY-AMOUNT"), False)], guarded=False)  # L73
        S.perform("SQB-STMT-0004")  # L74
        if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L74
            return "SQL-FAILED"  # L74  # GO TO
        S.compute([("WS-UPDATED", lambda: S.n("WS-UPDATED") + D("1"), False)], guarded=False)  # L80


def p_flag_over_limit():  # paragraph FLAG-OVER-LIMIT (line 82)
    S.perform("SQB-STMT-0005")  # L83
    if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L83
        return "SQL-FAILED"  # L83  # GO TO
    for _ in S.loop():  # L84
        if S.cmp(S.r("SQLCODE"), "!=", D("0")):
            break
        S.perform("SQB-STMT-0006")  # L85
        if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L85
            return "SQL-FAILED"  # L85  # GO TO
        if S.cmp(S.r("SQLCODE"), "==", D("0")):  # L89
            S.perform("SQB-STMT-0007")  # L90
            if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L90
                return "SQL-FAILED"  # L90  # GO TO
            S.compute([("WS-FLAGGED", lambda: S.n("WS-FLAGGED") + D("1"), False)], guarded=False)  # L94
            S.move(S.r("BALANCE"), "WS-SHOWN")  # L95
            S.display('OVER LIMIT ', S.r("ACCTNO"), ' ', S.r("WS-SHOWN"))  # L96
    S.perform("SQB-STMT-0008")  # L99
    if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L99
        return "SQL-FAILED"  # L99  # GO TO


def p_sql_failed():  # paragraph SQL-FAILED (line 100)
    S.compute([("WS-ERRORS", lambda: S.n("WS-ERRORS") + D("1"), False)], guarded=False)  # L101
    S.display('SQL ERROR ', S.r("SQLCODE"), ' STATE ', S.r("SQLSTATE"))  # L102
    S.perform("SQB-STMT-0009")  # L103
    if S.cmp(S.r("SQLCODE"), "<", D("0")):  # L103
        return "SQL-FAILED"  # L103  # GO TO
    S.move(D("8"), "RETURN-CODE")  # L104
    raise StopRun()  # L105


def p_sqb_end_of_program():  # paragraph SQB-END-OF-PROGRAM (line 106)
    raise GoBack()  # L107


def p_sqb_stmt_0001():  # paragraph SQB-STMT-0001 (line 108)
    S.move('COMMIT', "SQB-OP")  # L109
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L110
    pass  # CONTINUE  # L114


def p_sqb_stmt_0002():  # paragraph SQB-STMT-0002 (line 115)
    S.move('EXEC', "SQB-OP")  # L116
    S.move('', "SQB-CURSOR")  # L117
    S.move(SPACE, "SQB-TEXT")  # L118
    S.string([('SELECT BALANCE, CREDIT FROM ACCOUNTS WHE', None), ('RE ACCTNO = ?', None)], S.r("SQB-TEXT"), None)  # L119
    S.move(D("1"), "SQB-NPARAM")  # L124
    S.move(ALL('N'), "SQB-PNULLS")  # L125
    S.move(S.r("ACCTNO"), S.r("SQB-PARAM", int(D("1"))))  # L126
    S.move(D("2"), "SQB-NRES")  # L127
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L128
    if S.cmp(S.r("SQLCODE"), "==", D("0")) or S.cmp(S.r("SQLCODE"), "==", D("-811")):  # L132
        if S.cmp(S.r("SQB-RNULL", int(D("1"))), "==", 'N'):  # L133
            S.compute([("BALANCE", lambda: D(F.NUMVAL(S.text(S.r("SQB-RES", int(D("1")))))), False)], guarded=False)  # L134
        else:
            S.move(D("-305"), "SQLCODE")  # L136
            S.move('22002', "SQLSTATE")  # L137
        if S.cmp(S.r("SQB-RNULL", int(D("2"))), "==", 'N'):  # L139
            S.compute([("CREDIT", lambda: D(F.NUMVAL(S.text(S.r("SQB-RES", int(D("2")))))), False)], guarded=False)  # L140
            S.move(D("0"), "WS-CREDIT-IND")  # L141
        else:
            S.move(D("-1"), "WS-CREDIT-IND")  # L143
    pass  # CONTINUE  # L146


def p_sqb_stmt_0003():  # paragraph SQB-STMT-0003 (line 147)
    S.move('EXEC', "SQB-OP")  # L148
    S.move('', "SQB-CURSOR")  # L149
    S.move(SPACE, "SQB-TEXT")  # L150
    S.string([('INSERT INTO ACCOUNTS (ACCTNO, OWNER, BAL', None), ('ANCE, CREDIT, STATUS) VALUES (?, ?, ?, ?', None), (', ?)', None)], S.r("SQB-TEXT"), None)  # L151
    S.move(D("5"), "SQB-NPARAM")  # L157
    S.move(ALL('N'), "SQB-PNULLS")  # L158
    S.move(S.r("ACCTNO"), S.r("SQB-PARAM", int(D("1"))))  # L159
    S.move(S.r("OWNER"), S.r("SQB-PARAM", int(D("2"))))  # L160
    S.move(S.r("BALANCE"), "SQB-ED2")  # L161
    S.move(S.r("SQB-ED2"), S.r("SQB-PARAM", int(D("3"))))  # L162
    S.move(S.r("CREDIT"), "SQB-ED2")  # L163
    S.move(S.r("SQB-ED2"), S.r("SQB-PARAM", int(D("4"))))  # L164
    if S.cmp(S.r("WS-CREDIT-IND"), "<", D("0")):  # L165
        S.move('Y', S.r("SQB-PNULL", int(D("4"))))  # L166
    S.move(S.r("ACCT-STATUS"), S.r("SQB-PARAM", int(D("5"))))  # L168
    S.move(D("0"), "SQB-NRES")  # L169
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L170
    pass  # CONTINUE  # L174


def p_sqb_stmt_0004():  # paragraph SQB-STMT-0004 (line 175)
    S.move('EXEC', "SQB-OP")  # L176
    S.move('', "SQB-CURSOR")  # L177
    S.move(SPACE, "SQB-TEXT")  # L178
    S.string([('UPDATE ACCOUNTS SET BALANCE = ?, STATUS ', None), ("= 'ACTIVE' WHERE ACCTNO = ?", None)], S.r("SQB-TEXT"), None)  # L179
    S.move(D("2"), "SQB-NPARAM")  # L184
    S.move(ALL('N'), "SQB-PNULLS")  # L185
    S.move(S.r("BALANCE"), "SQB-ED2")  # L186
    S.move(S.r("SQB-ED2"), S.r("SQB-PARAM", int(D("1"))))  # L187
    S.move(S.r("ACCTNO"), S.r("SQB-PARAM", int(D("2"))))  # L188
    S.move(D("0"), "SQB-NRES")  # L189
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L190
    pass  # CONTINUE  # L194


def p_sqb_stmt_0005():  # paragraph SQB-STMT-0005 (line 195)
    S.move('OPENU', "SQB-OP")  # L196
    S.move('OVER', "SQB-CURSOR")  # L197
    S.move(SPACE, "SQB-TEXT")  # L198
    S.string([('SELECT ACCTNO, BALANCE, CREDIT, rowid FR', None), ('OM ACCOUNTS WHERE BALANCE < 0 - COALESCE', None), ('(CREDIT, 0) ORDER BY ACCTNO', None)], S.r("SQB-TEXT"), None)  # L199
    S.move(D("0"), "SQB-NPARAM")  # L205
    S.move(ALL('N'), "SQB-PNULLS")  # L206
    S.move(D("0"), "SQB-NRES")  # L207
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L208
    pass  # CONTINUE  # L212


def p_sqb_stmt_0006():  # paragraph SQB-STMT-0006 (line 213)
    S.move('FETCH', "SQB-OP")  # L214
    S.move('OVER', "SQB-CURSOR")  # L215
    S.move(D("3"), "SQB-NRES")  # L216
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L217
    if S.cmp(S.r("SQLCODE"), "==", D("0")):  # L221
        if S.cmp(S.r("SQB-RNULL", int(D("1"))), "==", 'N'):  # L222
            S.move(S.r("SQB-RES", int(D("1"))), "ACCTNO")  # L223
        else:
            S.move(D("-305"), "SQLCODE")  # L225
            S.move('22002', "SQLSTATE")  # L226
        if S.cmp(S.r("SQB-RNULL", int(D("2"))), "==", 'N'):  # L228
            S.compute([("BALANCE", lambda: D(F.NUMVAL(S.text(S.r("SQB-RES", int(D("2")))))), False)], guarded=False)  # L229
        else:
            S.move(D("-305"), "SQLCODE")  # L231
            S.move('22002', "SQLSTATE")  # L232
        if S.cmp(S.r("SQB-RNULL", int(D("3"))), "==", 'N'):  # L234
            S.compute([("CREDIT", lambda: D(F.NUMVAL(S.text(S.r("SQB-RES", int(D("3")))))), False)], guarded=False)  # L235
            S.move(D("0"), "WS-CREDIT-IND")  # L236
        else:
            S.move(D("-1"), "WS-CREDIT-IND")  # L238
    pass  # CONTINUE  # L241


def p_sqb_stmt_0007():  # paragraph SQB-STMT-0007 (line 242)
    S.move('CURRENT', "SQB-OP")  # L243
    S.move('OVER', "SQB-CURSOR")  # L244
    S.move(SPACE, "SQB-TEXT")  # L245
    S.string([("UPDATE ACCOUNTS SET STATUS = 'OVERLIM' W", None), ('HERE rowid = ?', None)], S.r("SQB-TEXT"), None)  # L246
    S.move(D("0"), "SQB-NPARAM")  # L251
    S.move(ALL('N'), "SQB-PNULLS")  # L252
    S.move(D("0"), "SQB-NRES")  # L253
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L254
    pass  # CONTINUE  # L258


def p_sqb_stmt_0008():  # paragraph SQB-STMT-0008 (line 259)
    S.move('CLOSE', "SQB-OP")  # L260
    S.move('OVER', "SQB-CURSOR")  # L261
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L262
    pass  # CONTINUE  # L266


def p_sqb_stmt_0009():  # paragraph SQB-STMT-0009 (line 267)
    S.move('ROLLBACK', "SQB-OP")  # L268
    S.call('SQLBRIDGE', [("reference", S.r("SQLCA")), ("reference", S.r("SQB-OP")), ("reference", S.r("SQB-CURSOR")), ("reference", S.r("SQB-TEXT")), ("reference", S.r("SQB-NPARAM")), ("reference", S.r("SQB-PARAMS")), ("reference", S.r("SQB-PNULLS")), ("reference", S.r("SQB-NRES")), ("reference", S.r("SQB-RESULTS")), ("reference", S.r("SQB-RNULLS")), ("reference", S.r("SQB-RLENS"))])  # L269
    pass  # CONTINUE  # L273


PARAGRAPHS = [
    ("MAIN-PARA", p_main_para),
    ("POST-ONE", p_post_one),
    ("FLAG-OVER-LIMIT", p_flag_over_limit),
    ("SQL-FAILED", p_sql_failed),
    ("SQB-END-OF-PROGRAM", p_sqb_end_of_program),
    ("SQB-STMT-0001", p_sqb_stmt_0001),
    ("SQB-STMT-0002", p_sqb_stmt_0002),
    ("SQB-STMT-0003", p_sqb_stmt_0003),
    ("SQB-STMT-0004", p_sqb_stmt_0004),
    ("SQB-STMT-0005", p_sqb_stmt_0005),
    ("SQB-STMT-0006", p_sqb_stmt_0006),
    ("SQB-STMT-0007", p_sqb_stmt_0007),
    ("SQB-STMT-0008", p_sqb_stmt_0008),
    ("SQB-STMT-0009", p_sqb_stmt_0009),
]
SECTIONS = {}


RUN_FILES = [['PAYMENTS', 'PAYIN'], ['SQLDB', 'SQLDB']]  # every file the run touches, in this program and the programs it calls


def main(io=None):
    """Run the whole program, like the COBOL batch job. io holds the input files and console input."""
    return S.run(io if io is not None else IO(), PARAGRAPHS, SECTIONS)


if __name__ == "__main__":
    raise SystemExit(run_cli(main, RUN_FILES))
