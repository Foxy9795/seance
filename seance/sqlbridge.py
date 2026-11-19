"""SQLBRIDGE for the Python side: embedded SQL on SQLite, by the same rules as seance/native/sqlbridge.c.

The precompiled COBOL CALLs 'SQLBRIDGE' USING SQLCA OP CURSOR TEXT NPARAM PARAMS PNULLS NRES RESULTS RNULLS RLENS.
The translated Python makes the same CALL; seance.rt routes it here. Seeding the database before a run and dumping
it afterwards are here too, so both sides start from and are judged by exactly the same database.
"""

from __future__ import annotations

import sqlite3
import struct

PSIZE, MAXP = 256, 64
ENC = "latin-1"


def _set(ca, code: int, state: str, rows: int = 0) -> None:
    ca[0:8] = b"SQLCA   "
    ca[8:12] = struct.pack("<i", 136)
    ca[12:16] = struct.pack("<i", code)
    ca[16:18] = b"\x00\x00"
    ca[18:88] = b" " * 70
    ca[88:96] = b" " * 8
    ca[96:120] = b"\x00" * 24
    ca[104:108] = struct.pack("<i", rows)
    ca[120:131] = b" " * 11
    ca[131:136] = state.encode()


def _error(ca, exc: sqlite3.Error) -> None:
    rc = getattr(exc, "sqlite_errorcode", 1)
    primary = rc & 0xFF
    if rc in (1555, 2067):
        _set(ca, -803, "23505")
    elif rc == 1299:
        _set(ca, -407, "23502")
    elif primary == 19:
        _set(ca, -545, "23513")
    elif primary == 1:
        _set(ca, -104, "42601")
    else:
        _set(ca, -901, "58004")


def _num(b) -> int:
    return int("".join(c for c in bytes(b).decode(ENC) if c.isdigit()) or "0")


def _text_of(conn, v) -> str | None:
    """A value as SQLite's own text form, the same as sqlite3_column_text gives the COBOL side."""
    if v is None:
        return None
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return conn.execute("SELECT CAST(? AS TEXT)", (v,)).fetchone()[0]
    if isinstance(v, bytes):
        return v.decode(ENC)
    return str(v)


class Bridge:
    def __init__(self, seed: bytes | None):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        if seed:
            self.conn.executescript(seed.decode(ENC))
        self.conn.execute("BEGIN")
        self.cursors: dict[bytes, dict] = {}

    def _params(self, text, np, params, pnulls, extra=None):
        sql = bytes(text).decode(ENC).rstrip(" ")
        values = []
        for i in range(min(_num(np), MAXP)):
            if pnulls[i:i + 1] == b"Y":
                values.append(None)
                continue
            values.append(bytes(params[i * PSIZE:(i + 1) * PSIZE]).decode(ENC).strip(" "))
        if extra is not None:
            values.append(extra)
        return sql, values

    def _deliver(self, row, nres, skip_last, results, rnulls, rlens):
        cols = len(row) - (1 if skip_last else 0)
        for i in range(min(nres, MAXP)):
            out = b""
            t = _text_of(self.conn, row[i]) if i < cols else None
            if t is None:
                rnulls[i:i + 1] = b"Y"
            else:
                rnulls[i:i + 1] = b"N"
                out = t.encode(ENC, errors="replace")[:PSIZE]
            results[i * PSIZE:(i + 1) * PSIZE] = out.ljust(PSIZE, b" ")
            rlens[i * 4:i * 4 + 4] = b"%04d" % len(out)

    def call(self, ca, op, cursor, text, np, params, pnulls, nr, results, rnulls, rlens) -> None:
        op = bytes(op).decode(ENC).strip()
        key = bytes(cursor)[:30]
        nres = _num(nr)
        _set(ca, 0, "00000")
        if op == "NOOP":
            return
        if op == "COMMIT":
            self.conn.execute("COMMIT")
            self.conn.execute("BEGIN")
            return
        if op == "ROLLBACK":
            self.conn.execute("ROLLBACK")
            self.conn.execute("BEGIN")
            return
        if op in ("OPEN", "OPENU"):
            if key in self.cursors:
                return _set(ca, -502, "24502")
            sql, values = self._params(text, np, params, pnulls)
            try:
                cur = self.conn.execute(sql, values)
            except sqlite3.Error as exc:
                return _error(ca, exc)
            self.cursors[key] = {"cur": cur, "update": op == "OPENU", "rowid": 0}
            return
        if op == "FETCH":
            c = self.cursors.get(key)
            if c is None:
                return _set(ca, -501, "24501")
            try:
                row = c["cur"].fetchone()
            except sqlite3.Error as exc:
                return _error(ca, exc)
            if row is None:
                return _set(ca, 100, "02000")
            if c["update"]:
                c["rowid"] = row[-1]
            self._deliver(row, nres, c["update"], results, rnulls, rlens)
            return _set(ca, 0, "00000", 1)
        if op == "CLOSE":
            c = self.cursors.pop(key, None)
            if c is None:
                return _set(ca, -501, "24501")
            c["cur"].close()
            return
        extra = None
        if op == "CURRENT":
            c = self.cursors.get(key)
            if c is None:
                return _set(ca, -501, "24501")
            extra = c["rowid"]
        sql, values = self._params(text, np, params, pnulls, extra)
        readonly = sql.startswith(("SELECT", "WITH", "VALUES"))
        try:
            cur = self.conn.execute(sql, values)
            if readonly:
                row = cur.fetchone()
                if row is None:
                    return _set(ca, 100, "02000")
                self._deliver(row, nres, False, results, rnulls, rlens)
                if cur.fetchone() is not None:
                    return _set(ca, -811, "21000")
                return _set(ca, 0, "00000", 1)
            rows = self.conn.execute("SELECT changes()").fetchone()[0]
        except sqlite3.Error as exc:
            return _error(ca, exc)
        if rows == 0 and sql.startswith(("UPDATE", "DELETE")):
            return _set(ca, 100, "02000")
        _set(ca, 0, "00000", rows)

    def finish(self) -> bytes:
        try:
            self.conn.execute("COMMIT")
        except sqlite3.Error:
            pass
        return dump(self.conn)


# ---------------------------------------------------------------- seeding and dumping

def dump(conn) -> bytes:
    """Every table, rows sorted, as text lines: the database's state for comparison."""
    lines = []
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in tables:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
        lines.append(f"TABLE {t} ({', '.join(cols)})")
        order = ", ".join(f'"{c}"' for c in cols)
        for row in conn.execute(f'SELECT * FROM "{t}" ORDER BY {order}'):
            lines.append(" | ".join("NULL" if v is None else _text_of(conn, v) for v in row))
    return ("\n".join(lines) + "\n").encode(ENC, errors="replace")


def seed_file(path, seed: bytes) -> None:
    conn = sqlite3.connect(str(path), isolation_level=None)
    if seed:
        conn.executescript(seed.decode(ENC))
    conn.close()


def dump_file(path) -> bytes:
    conn = sqlite3.connect(str(path))
    try:
        return dump(conn)
    finally:
        conn.close()


def dsntiar(ca, msg, lrecl) -> None:
    """DB2's DSNTIAR: the SQLCA as a message line (the same text as seance/native/dsntiar.c)."""
    code = struct.unpack("<i", bytes(ca[12:16]))[0]
    area = int.from_bytes(bytes(msg[0:2]), "big")
    width = int.from_bytes(bytes(lrecl[0:4]), "big", signed=True)
    if width <= 0 or width > area:
        width = area
    text = f"DSNT408I SQLCODE = {code}, SQLSTATE = {bytes(ca[131:136]).decode(ENC)}".encode(ENC)[:width]
    msg[2:2 + area] = text.ljust(area, b" ")
