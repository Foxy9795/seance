"""Draft Python for legacy/accounts/accounts.cbl (PROGRAM-ID ACCOUNTS).

Written by the Séance translator on 2026-11-18. Each line is tagged with the COBOL line it
came from. The per-record logic is paragraph 1000-PROCESS.
Every statement was translated.
This file is yours now: edit it, then run the check.
"""

from decimal import Decimal as D

from generated.accounts_records import InRecord, OutRecord
from seance.runtime import HIGH, LOW, QUOTE, SPACE, ZERO, Store

ITEMS = {
    "ACCT-REC": ("group", 0, 0, False, 0, '', None, ['ACCT-NO', 'ACCT-BALANCE', 'ACCT-LIMIT', 'ACCT-RATE', 'ACCT-TYPE', 'ACCT-MONTHS', 'FILLER-11-7']),
    "ACCT-NO": ("alpha", 0, 0, False, 8, 'XXXXXXXX', None, []),
    "ACCT-BALANCE": ("num", 9, 2, True, 9, 'S9999999V99', None, []),
    "ACCT-LIMIT": ("num", 9, 2, False, 9, '9999999V99', None, []),
    "ACCT-RATE": ("num", 4, 4, False, 4, 'V9999', None, []),
    "ACCT-TYPE": ("alpha", 0, 0, False, 1, 'X', None, []),
    "ACCT-MONTHS": ("num", 2, 0, False, 2, '99', None, []),
    "FILLER-11-7": ("alpha", 0, 0, False, 5, 'XXXXX', None, []),
    "OUT-REC": ("group", 0, 0, False, 0, '', None, ['OUT-ACCT-NO', 'OUT-NEW-BAL', 'OUT-FEE', 'OUT-INTEREST', 'OUT-STATUS', 'OUT-SHOWN']),
    "OUT-ACCT-NO": ("alpha", 0, 0, False, 8, 'XXXXXXXX', None, []),
    "OUT-NEW-BAL": ("num", 9, 2, True, 9, 'S9999999V99', None, []),
    "OUT-FEE": ("num", 5, 2, False, 5, '999V99', None, []),
    "OUT-INTEREST": ("num", 7, 2, False, 7, '99999V99', None, []),
    "OUT-STATUS": ("alpha", 0, 0, False, 10, 'XXXXXXXXXX', None, []),
    "OUT-SHOWN": ("edited", 0, 0, False, 14, '$$,$$$,$$9.99-', None, []),
    "WS-FLAGS": ("group", 0, 0, False, 0, '', None, ['WS-EOF']),
    "WS-EOF": ("alpha", 0, 0, False, 1, 'X', 'N', []),
    "WS-WORK": ("group", 0, 0, False, 0, '', None, ['WS-BAL', 'WS-MONTH-RATE', 'WS-I', 'WS-COUNT']),
    "WS-BAL": ("num", 13, 4, True, 13, 'S999999999V9999', None, []),
    "WS-MONTH-RATE": ("num", 7, 6, False, 7, '9V999999', None, []),
    "WS-I": ("num", 3, 0, False, 3, '999', None, []),
    "WS-COUNT": ("num", 7, 0, False, 7, '9999999', ZERO, []),
}

CONDITIONS = {
    "SAVINGS": ("ACCT-TYPE", [('S', None)]),
    "CHECKING": ("ACCT-TYPE", [('C', None)]),
    "END-OF-FILE": ("WS-EOF", [('Y', None)]),
}

IN_FIELDS = [('no', 'ACCT-NO'), ('balance', 'ACCT-BALANCE'), ('limit', 'ACCT-LIMIT'), ('rate', 'ACCT-RATE'), ('type', 'ACCT-TYPE'), ('months', 'ACCT-MONTHS')]
OUT_FIELDS = [('acct_no', 'OUT-ACCT-NO'), ('new_bal', 'OUT-NEW-BAL'), ('fee', 'OUT-FEE'), ('interest', 'OUT-INTEREST'), ('status', 'OUT-STATUS'), ('shown', 'OUT-SHOWN')]

S = Store(ITEMS, CONDITIONS)


def reset():
    """Run once per input file, like the COBOL start-up code before the read loop."""
    S.reset()
    S.started = True


def p_2000_interest():  # paragraph 2000-INTEREST
    S.compute([("WS-MONTH-RATE", lambda: S.n("ACCT-RATE") / D("12"), False)], guarded=False)  # L68
    S.compute([("WS-I", lambda: D("1"), False)])  # L69
    for _ in S.loop():
        if S.cmp(S["WS-I"], ">", S["ACCT-MONTHS"]):
            break
        S.compute([("WS-BAL", lambda: S.n("WS-BAL") * (D("1") + S.n("WS-MONTH-RATE")), True)], guarded=False)  # L70
        S.compute([("WS-I", lambda: S.n("WS-I") + D("1"), False)])
    if not S.compute([("OUT-INTEREST", lambda: S.n("WS-BAL") - S.n("ACCT-BALANCE"), True)], guarded=True):  # L72
        S.move(D("99999.99"), 'OUT-INTEREST')  # L73


def p_3000_fee():  # paragraph 3000-FEE
    if (S.cmp(S["WS-BAL"], ">=", D("2500"))):  # L76
        S.move(D("0"), 'OUT-FEE')  # L78
    elif (S.cmp(S["WS-BAL"], ">=", D("500"))):
        S.move(D("4.50"), 'OUT-FEE')  # L80
    else:
        S.move(D("12.00"), 'OUT-FEE')  # L82
    S.compute([("WS-BAL", lambda: S.n("WS-BAL") - (S.n("OUT-FEE")), False)], guarded=False)  # L84


def one_record():
    """The work the COBOL does for each record it reads."""
    S.initialize('OUT-REC')  # L40
    S.move(S["ACCT-NO"], 'OUT-ACCT-NO')  # L41
    S.move(S["ACCT-BALANCE"], 'WS-BAL')  # L42
    S.compute([("WS-COUNT", lambda: S.n("WS-COUNT") + D("1"), False)], guarded=False)  # L43
    if (S.cond("SAVINGS")):  # L44
        p_2000_interest()  # L46
    elif (S.cond("CHECKING")):
        p_3000_fee()  # L48
    else:
        S.move('UNKNOWN', 'OUT-STATUS')  # L50
    if S.cmp(S["WS-BAL"], "<", S.ZERO):  # L52
        if S.cmp(D("0") - S.n("WS-BAL"), ">", S["ACCT-LIMIT"]):  # L53
            S.move('OVER-LIMIT', 'OUT-STATUS')  # L54
        else:
            S.move('OVERDRAWN', 'OUT-STATUS')  # L56
    else:
        if S.cmp(S["OUT-STATUS"], "==", S.SPACE):  # L59
            S.move('OK', 'OUT-STATUS')  # L60
    S.compute([("OUT-NEW-BAL", lambda: S.n("WS-BAL"), False)], guarded=False)  # L63
    S.move(S["OUT-NEW-BAL"], 'OUT-SHOWN')  # L64
    S.write("OUT-REC")  # L65


def transform(rec: InRecord) -> OutRecord:
    if not S.started:
        reset()
    S.load(rec, IN_FIELDS)
    S.written.clear()
    one_record()
    return S.output(OutRecord, OUT_FIELDS)
