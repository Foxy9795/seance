"""CICSBRIDGE for the Python side: the CICS commands Séance's CICS precompiler emits, by the same rules as
seance/native/cicsbridge.c. Everything a transaction touches lives in one SQLite database, so both sides start
from the same state and are compared on the state they leave:

    files(file, key, rec)        VSAM-style keyed files (keys compare byte by byte, like a KSDS)
    tsq(queue, item, data)       temporary storage queues
    term_in(seq, aid, data)      what the user types, screen by screen (consumed by RECEIVE)
    term_out(seq, kind, data)    what the program sends (SEND TEXT, SEND MAP)
    control(name, value)         the COMMAREA passed in, RETURN TRANSID / COMMAREA, ABEND code

CALL 'CICSBRIDGE' USING DFHEIBLK OP NAME KEYLEN KEY DATALEN DATA ITEM
    OP X(8), NAME X(8), KEYLEN / DATALEN / ITEM PIC 9(5); KEY and DATA are the program's own items.
"""

from __future__ import annotations

import sqlite3

ENC = "latin-1"
RESP = {"NORMAL": 0, "ERROR": 1, "NOTFND": 13, "DUPREC": 14, "INVREQ": 16, "NOTOPEN": 19, "ENDFILE": 20, "LENGERR": 22,
        "QZERO": 23, "ITEMERR": 26, "PGMIDERR": 27, "MAPFAIL": 36, "QIDERR": 44, "DISABLED": 84}
SCHEMA = """CREATE TABLE IF NOT EXISTS files (file TEXT, key BLOB, rec BLOB, PRIMARY KEY (file, key));
CREATE TABLE IF NOT EXISTS tsq (queue TEXT, item INTEGER, data BLOB, PRIMARY KEY (queue, item));
CREATE TABLE IF NOT EXISTS term_in (seq INTEGER PRIMARY KEY, aid TEXT, data BLOB, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS term_out (seq INTEGER PRIMARY KEY, kind TEXT, data BLOB);
CREATE TABLE IF NOT EXISTS control (name TEXT PRIMARY KEY, value BLOB);
"""
EIB_DATE = bytes.fromhex("0126304f")  # 0CYYDDD packed: 2026-10-31, day 304
EIB_TIME = bytes.fromhex("0235958f")  # 0HHMMSS packed: 23:59:58


NO_DATA_AIDS = (b"_", b"%", b">", b",")  # CLEAR, PA1, PA2, PA3


def _bytes(v) -> bytes:
    return v.encode(ENC) if isinstance(v, str) else bytes(v)


def _num(b) -> int:
    return int("".join(c for c in bytes(b).decode(ENC) if c.isdigit()) or "0")


def _put_num(view, n: int) -> None:
    view[0:len(view)] = str(n).zfill(len(view))[-len(view):].encode()


def _resp(eib, code: int) -> None:
    eib[76:80] = code.to_bytes(4, "big", signed=True)
    eib[80:84] = b"\x00\x00\x00\x00"


class Bridge:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.last: dict[str, bytes] = {}  # file -> key of the last READ (REWRITE / DELETE without RIDFLD)
        self.browse: dict[str, tuple[bytes, bool]] = {}  # file -> (position, inclusive)
        self.qpos: dict[str, int] = {}  # queue -> last item read by READQ NEXT

    def _get(self, name: str):
        r = self.conn.execute("SELECT value FROM control WHERE name = ?", (name,)).fetchone()
        return r[0] if r else None

    def _set(self, name: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO control VALUES (?, ?)", (name, value))

    def call(self, eib, op, name, keylen, key, datalen, data, item) -> None:
        op = bytes(op).decode(ENC).strip()
        nm = bytes(name).decode(ENC).strip()
        kl, dl = _num(keylen), _num(datalen)
        k = bytes(key[0:kl])
        _resp(eib, 0)
        c = self.conn
        if op == "ENTRY":
            area = self._get("commarea_in") or b""
            eib[0:4], eib[4:8] = EIB_TIME, EIB_DATE
            eib[8:12] = (self._get("transid") or b"TRN1").ljust(4, b" ")[:4]
            eib[12:16] = bytes.fromhex("0000001c")
            eib[16:20] = b"T001"
            eib[24:26] = len(area).to_bytes(2, "big")
            eib[26:27] = (self._get("aid") or b"'")[:1]
            if self._get("bind") is not None:  # a later turn of a conversation: started by the key on the next screen
                row = c.execute("SELECT seq, aid FROM term_in WHERE used = 0 ORDER BY seq LIMIT 1").fetchone()
                if row is not None:
                    if row[1]:
                        eib[26:27] = _bytes(row[1])[:1]
                    self._set("current_seq", str(row[0]).encode())
            n = min(len(area), dl)
            data[0:n] = area[:n]
            return
        if op in ("READ", "READGE", "READGEN"):
            if op == "READ":
                row = c.execute("SELECT key, rec FROM files WHERE file = ? AND key = ?", (nm, k)).fetchone()
            elif op == "READGE":
                row = c.execute("SELECT key, rec FROM files WHERE file = ? AND key >= ? ORDER BY key LIMIT 1", (nm, k)).fetchone()
            else:
                row = c.execute("SELECT key, rec FROM files WHERE file = ? AND substr(key, 1, ?) = ? ORDER BY key LIMIT 1", (nm, kl, k)).fetchone()
            if row is None:
                return _resp(eib, RESP["NOTFND"])
            rk, rec = bytes(row[0]), bytes(row[1])
            n = min(len(rec), dl)
            data[0:n] = rec[:n]
            _put_num(datalen, len(rec))
            self.last[nm] = rk
            if len(rec) > dl:
                _resp(eib, RESP["LENGERR"])
            return
        if op == "WRITE":
            try:
                c.execute("INSERT INTO files VALUES (?, ?, ?)", (nm, k, bytes(data[0:dl])))
            except sqlite3.IntegrityError:
                _resp(eib, RESP["DUPREC"])
            return
        if op == "REWRITE":
            if nm not in self.last:
                return _resp(eib, RESP["INVREQ"])
            c.execute("UPDATE files SET rec = ? WHERE file = ? AND key = ?", (bytes(data[0:dl]), nm, self.last.pop(nm)))
            return
        if op == "DELETE":
            target = k if kl else self.last.pop(nm, None)
            if target is None:
                return _resp(eib, RESP["INVREQ"])
            if c.execute("DELETE FROM files WHERE file = ? AND key = ?", (nm, target)).rowcount == 0:
                _resp(eib, RESP["NOTFND"])
            return
        if op == "STARTBR":
            if c.execute("SELECT 1 FROM files WHERE file = ? AND key >= ? LIMIT 1", (nm, k)).fetchone() is None:
                return _resp(eib, RESP["NOTFND"])
            self.browse[nm] = (k, True)
            return
        if op in ("READNEXT", "READPREV"):
            if nm not in self.browse:
                return _resp(eib, RESP["INVREQ"])
            pos, incl = self.browse[nm]
            if op == "READNEXT":
                q = "SELECT key, rec FROM files WHERE file = ? AND key " + (">=" if incl else ">") + " ? ORDER BY key LIMIT 1"
            else:
                q = "SELECT key, rec FROM files WHERE file = ? AND key " + ("<=" if incl else "<") + " ? ORDER BY key DESC LIMIT 1"
            row = c.execute(q, (nm, pos)).fetchone()
            if row is None:
                return _resp(eib, RESP["ENDFILE"])
            rk, rec = bytes(row[0]), bytes(row[1])
            n = min(len(rec), dl)
            data[0:n] = rec[:n]
            _put_num(datalen, len(rec))
            m = min(len(rk), len(key))
            key[0:m] = rk[:m]
            self.browse[nm] = (rk, False)
            self.last[nm] = rk
            return
        if op == "ENDBR":
            if self.browse.pop(nm, None) is None:
                _resp(eib, RESP["INVREQ"])
            return
        if op in ("SEND", "SENDMAP"):
            c.execute("INSERT INTO term_out (kind, data) VALUES (?, ?)", ("TEXT" if op == "SEND" else f"MAP {nm}", bytes(data[0:dl])))
            return
        if op == "RECEIVE":
            row = c.execute("SELECT seq, aid, data FROM term_in WHERE used = 0 ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return _resp(eib, RESP["MAPFAIL"])
            c.execute("UPDATE term_in SET used = 1 WHERE seq = ?", (row[0],))
            eib[26:27] = _bytes(row[1] or b"'")[:1]
            got = bytes(row[2] or b"")
            if not got or bytes(eib[26:27]) in NO_DATA_AIDS:  # CLEAR, PA keys, an empty screen: MAPFAIL
                return _resp(eib, RESP["MAPFAIL"])
            n = min(len(got), dl)
            data[0:n] = got[:n]
            if n < dl:
                data[n:dl] = b" " * (dl - n)
            _put_num(datalen, len(got))
            return
        if op == "WRITEQTS":
            top = c.execute("SELECT COALESCE(MAX(item), 0) FROM tsq WHERE queue = ?", (nm,)).fetchone()[0]
            c.execute("INSERT INTO tsq VALUES (?, ?, ?)", (nm, top + 1, bytes(data[0:dl])))
            _put_num(item, top + 1)
            return
        if op == "READQTS":
            if c.execute("SELECT 1 FROM tsq WHERE queue = ? LIMIT 1", (nm,)).fetchone() is None:
                return _resp(eib, RESP["QIDERR"])
            want = _num(item) or self.qpos.get(nm, 0) + 1
            row = c.execute("SELECT data FROM tsq WHERE queue = ? AND item = ?", (nm, want)).fetchone()
            if row is None:
                return _resp(eib, RESP["ITEMERR"])
            got = bytes(row[0])
            n = min(len(got), dl)
            data[0:n] = got[:n]
            self.qpos[nm] = want
            _put_num(item, want)
            return
        if op in ("WRITEQTD", "READQTD", "DELQTD"):  # transient data, kept in tsq under 'TD:' + name
            tq = "TD:" + nm
            if op == "WRITEQTD":
                top = c.execute("SELECT COALESCE(MAX(item), 0) FROM tsq WHERE queue = ?", (tq,)).fetchone()[0]
                c.execute("INSERT INTO tsq VALUES (?, ?, ?)", (tq, top + 1, bytes(data[0:dl])))
            elif op == "READQTD":
                row = c.execute("SELECT item, data FROM tsq WHERE queue = ? ORDER BY item LIMIT 1", (tq,)).fetchone()
                if row is None:
                    return _resp(eib, RESP["QZERO"])
                got = bytes(row[1])
                n = min(len(got), dl)
                data[0:n] = got[:n]
                _put_num(datalen, len(got))
                c.execute("DELETE FROM tsq WHERE queue = ? AND item = ?", (tq, row[0]))
            else:
                c.execute("DELETE FROM tsq WHERE queue = ?", (tq,))
            return
        if op == "DELQTS":
            if c.execute("DELETE FROM tsq WHERE queue = ?", (nm,)).rowcount == 0:
                _resp(eib, RESP["QIDERR"])
            self.qpos.pop(nm, None)
            return
        if op == "RETURN":
            self._set("return_transid", nm.encode(ENC))
            self._set("return_commarea", bytes(data[0:dl]))
            return
        if op == "ABEND":
            self._set("abend", nm.encode(ENC))
            return
        if op == "SYNCPNT":
            return
        _resp(eib, RESP["INVREQ"])


# ---------------------------------------------------------------- the pseudo-conversation around the program

MAX_TURNS = 60


def next_turn(conn: sqlite3.Connection) -> bool:
    """After a run: if the program RETURNed with a TRANSID and the user has typed more, start the next run with
    the COMMAREA it handed back (a pseudo-conversational transaction). If it RETURNed without one and screens are
    left, the user starts the transaction again: a fresh conversation, EIBCALEN 0. An ABEND ends the session."""
    cur = conn.execute("SELECT value FROM control WHERE name = 'current_seq'").fetchone()
    if cur and cur[0] is not None:  # the screen that started the task is gone once the task ends
        conn.execute("UPDATE term_in SET used = 1 WHERE seq = ?", (int(bytes(cur[0]).decode()),))
    row = conn.execute("SELECT value FROM control WHERE name = 'return_transid'").fetchone()
    transid = bytes(row[0]).decode(ENC).strip() if row and row[0] is not None else ""
    pending = conn.execute("SELECT COUNT(*) FROM term_in WHERE used = 0").fetchone()[0]
    abend = conn.execute("SELECT value FROM control WHERE name = 'abend'").fetchone()
    if not pending or abend:
        return False
    conn.execute("DELETE FROM control WHERE name = 'current_seq'")
    if transid:
        area = conn.execute("SELECT value FROM control WHERE name = 'return_commarea'").fetchone()
        conn.execute("INSERT OR REPLACE INTO control VALUES ('commarea_in', ?)", (bytes(area[0]) if area and area[0] is not None else b"",))
        conn.execute("INSERT OR REPLACE INTO control VALUES ('transid', ?)", (transid.encode(ENC),))
        conn.execute("INSERT OR REPLACE INTO control VALUES ('bind', X'31')")
    else:
        conn.execute("INSERT OR REPLACE INTO control VALUES ('commarea_in', X'')")
        conn.execute("DELETE FROM control WHERE name = 'bind'")
        starts = conn.execute("SELECT value FROM control WHERE name = 'conversations'").fetchone()
        k = int(bytes(starts[0]).decode() if starts and starts[0] is not None else "1") + 1
        conn.execute("INSERT OR REPLACE INTO control VALUES ('conversations', ?)", (str(k).encode(),))
    conn.execute("DELETE FROM control WHERE name IN ('return_transid', 'return_commarea')")
    turns = conn.execute("SELECT value FROM control WHERE name = 'turns'").fetchone()
    n = int(bytes(turns[0]).decode() if turns and turns[0] is not None else "1") + 1
    conn.execute("INSERT OR REPLACE INTO control VALUES ('turns', ?)", (str(n).encode(),))
    return n <= MAX_TURNS


def seed(conn: sqlite3.Connection, script: bytes) -> None:
    conn.executescript(SCHEMA)
    if script:
        conn.executescript(script.decode(ENC))
