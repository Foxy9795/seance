"""Indexed and relative files, CALL, SORT, embedded SQL, CICS and JCL jobs: checked against the real COBOL with fresh random runs."""

import pytest

from seance.recorder import cobc_available, get_model
from seance.rt import crt_qsort
from seance.verify import verify

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")


@needs_cobol
@pytest.mark.parametrize("program", ["customer_master", "order_pricing", "transaction_sort", "seat_bookings"])
def test_feature_examples_match_on_random_runs(program):
    report = verify(program, None, 6)
    assert report.matched, report.review


def test_called_programs_are_found_in_the_folder():
    model = get_model("order_pricing")
    subs = {m.program_id: m for m in model.subprograms}
    assert set(subs) == {"PRICER", "COUNTER"}
    assert subs["PRICER"].initial and subs["PRICER"].using == ["LK-ARGS"]
    assert any("NOSUCHPG" in n for n in model.notes), "a CALL to a missing program is reported"


def test_indexed_file_keys_are_read():
    f = next(f for f in get_model("customer_master").files if f.organization == "indexed")
    assert f.record_key == "M-ID" and f.alt_keys == [("M-REGION", True)] and f.access == "dynamic"


def test_ebcdic_record_converts_field_by_field():
    from decimal import Decimal

    from seance.cases import spec_of
    from seance.codec import decode
    from seance.ebcdic import record_to_ascii
    from seance.layout import leaves

    rec = next(f for f in get_model("accounts").files if f.assign == "ACCTIN").record
    lv = {lf.name: lf for lf in leaves(rec)}
    ebc = bytearray(b"\x40" * rec.size)
    ebc[0:8] = "AC-00042".encode("cp037")
    bal = lv["ACCT-BALANCE"]  # S9(7)V99, sign in the last digit: -123.45 is F0...F1F2F3F4 D5
    ebc[bal.offset:bal.offset + bal.width] = bytes([0xF0] * 4 + [0xF1, 0xF2, 0xF3, 0xF4, 0xD5])
    out = record_to_ascii(rec, bytes(ebc))
    assert out[0:8] == b"AC-00042"
    assert decode(spec_of(bal.item), out[bal.offset:bal.offset + bal.width]) == Decimal("-123.45")

    packed = next(f for f in get_model("account_report").files if f.assign == "ACCTREC").record
    raw = bytearray("12345678".encode("cp037") + b"\x00\x00\x12\x34\x5c" + b"\x40" * (packed.size - 13))
    assert record_to_ascii(packed, bytes(raw))[8:13] == b"\x00\x00\x12\x34\x5c", "packed bytes are left alone"


def test_table_sort_reproduces_the_c_runtime_order():
    rows = [s.encode() for s in "ZZZ1 YYY2 XXX1 WWW2 VVV1 UUU1 TTT2 SSS1 RRR2 QQQ1".split()]
    crt_qsort(rows, lambda a, b: (a[3] > b[3]) - (a[3] < b[3]))
    assert b"".join(rows) == b"ZZZ1SSS1XXX1UUU1VVV1QQQ1YYY2RRR2TTT2WWW2"  # what GnuCOBOL printed


# ---------------------------------------------------------------- SQL, CICS and JCL (each runs on the real COBOL)

@needs_cobol
@pytest.mark.parametrize("program", ["payment_posting", "customer_inquiry"])
def test_sql_and_cics_examples_match_on_random_runs(program):
    report = verify(program, None, 4)
    assert report.matched, report.review


@needs_cobol
def test_jcl_job_matches_step_by_step():
    from seance.jobs import verify_job

    report = verify_job("nightly_batch", 2)
    assert report.matched, report.review


def test_cics_commands_become_calls_on_the_same_lines():
    from seance.cicspre import DFHAID, Generator, parse_options, precompile_text

    words, opts = parse_options("READ FILE('CUSTFILE') INTO(WS-REC)\n     RIDFLD(WS-KEY) UPDATE RESP(WS-RESP)")
    assert words == ["READ"] and opts["FILE"] == "'CUSTFILE'" and "UPDATE" in opts and opts["UPDATE"] is None
    assert "DFHENTER      PIC X VALUE X'27'" in DFHAID, "ENTER is an apostrophe; QUOTE would be a double quote"

    class Item:
        size = 4
    gen = Generator(True, {"WS-REC": Item, "WS-KEY": Item, "WS-RESP": Item})
    src = ("           EXEC CICS READ FILE('CUSTFILE') INTO(WS-REC)\n"
           "                RIDFLD(WS-KEY) RESP(WS-RESP)\n"
           "           END-EXEC\n"
           "           IF WS-RESP = DFHRESP(NOTFND) CONTINUE END-IF\n")
    out = precompile_text(src, gen, True)
    assert out.count("\n") == src.count("\n"), "line numbers must not move"
    assert "PERFORM CIB-STMT-0001" in out and "EXEC" not in out and "WS-RESP = 13" in out
    assert any("CALL 'CICSBRIDGE'" in p for p in gen.paras)


def test_pseudo_conversation_turns_and_fresh_starts():
    import sqlite3

    from seance.cicsbridge import next_turn, seed

    conn = sqlite3.connect(":memory:")
    seed(conn, b"INSERT INTO term_in (seq, aid, data) VALUES (1, X'27', X'41'), (2, X'33', X'42');")
    conn.execute("INSERT OR REPLACE INTO control VALUES ('return_transid', X'43494E51')")  # RETURN TRANSID('CINQ')
    assert next_turn(conn)
    ctl = dict(conn.execute("SELECT name, value FROM control"))
    assert ctl["transid"] == b"CINQ" and ctl["bind"] == b"1" and ctl["turns"] == b"2"
    conn.execute("UPDATE term_in SET used = 1 WHERE seq = 1")
    assert next_turn(conn), "RETURN without TRANSID while screens are left: the user starts again"
    ctl = dict(conn.execute("SELECT name, value FROM control"))
    assert "bind" not in ctl and ctl["commarea_in"] == b"" and ctl["conversations"] == b"2"
    conn.execute("UPDATE term_in SET used = 1")
    assert not next_turn(conn), "no screens left: the session ends"
