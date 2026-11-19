"""Indexed and relative files, CALL, SORT: checked against the real COBOL with fresh random runs."""

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
