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


def test_table_sort_reproduces_the_c_runtime_order():
    rows = [s.encode() for s in "ZZZ1 YYY2 XXX1 WWW2 VVV1 UUU1 TTT2 SSS1 RRR2 QQQ1".split()]
    crt_qsort(rows, lambda a, b: (a[3] > b[3]) - (a[3] < b[3]))
    assert b"".join(rows) == b"ZZZ1SSS1XXX1UUU1VVV1QQQ1YYY2RRR2TTT2WWW2"  # what GnuCOBOL printed
