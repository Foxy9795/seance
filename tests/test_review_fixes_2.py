"""Fixes from the 2026-11-21 review that need no COBOL run: each was measured against GnuCOBOL 3.1.2 when it was made."""
from decimal import Decimal
from pathlib import Path

import pytest

from seance import special_names
from seance.cobol_src import expand_tabs, read_source
from seance.rt import Program


def test_tab_in_fixed_format_moves_to_column_8():
    assert expand_tabs("\t   MOVE 1 TO A.", True) == "       " + "   MOVE 1 TO A."
    assert expand_tabs("       \tX", True) == "       " + " X"  # past column 7: the next multiple of 8
    assert expand_tabs("a\tb", False) == "a       b"


def test_byte_order_mark_is_not_part_of_the_source(tmp_path):
    f = tmp_path / "p.cbl"
    f.write_bytes(b"\xef\xbb\xbf       IDENTIFICATION DIVISION.\n")
    assert read_source(f).startswith("       IDENTIFICATION")


def test_power_follows_libcob():
    assert Program.pow(Decimal(0), Decimal(-1)) == 0
    assert Program.pow(Decimal(0), Decimal(0)) == 1
    assert Program.pow(Decimal(2), Decimal(-1)) == Decimal("0.5")


def test_division_in_a_function_argument_keeps_38_extra_places():
    assert str(Program.xdiv(Decimal("12.34"), Decimal(3))) == "4.1133333333333333333333333333333333333333"


def test_ordinal_in_an_alphabet():
    eb = special_names.parse("ALPHABET EB IS EBCDIC SYMBOLIC CHARACTERS SC-A IS 194 IN EB")
    assert eb.symbolic["SC-A"] == "A"  # ordinal 194 of EBCDIC is code 193, which is A
    plain = special_names.parse("SYMBOLIC CHARACTERS SC-D IS 66")
    assert plain.symbolic["SC-D"] == "A"
    with pytest.raises(ValueError):
        special_names.parse("SYMBOLIC CHARACTERS SC-Z IS 0")


def test_two_different_stops_are_not_a_match():
    from seance.cases import Case, Result, compare, stop_kind
    from types import SimpleNamespace

    assert stop_kind("libcob: subscript out of bounds") == "subscript"
    assert stop_kind("CobolError: the program ran more than 5 loop steps; a loop") == "hang"
    model = SimpleNamespace(all_files=[])
    cobol = Result(error="libcob: subscript out of bounds")
    python = Result(error="CobolError: the program ran more than 2000000 loop steps; a loop probably never ends")
    diffs, _ = compare(model, cobol, python)
    assert diffs


def test_windows_line_ends_are_not_doubled():
    from seance.programs import _lf

    assert _lf("A\r\nB\rC\n") == "A\nB\nC\n"

PROBES = Path(__file__).parent / "probes"


def _both(src: Path):
    """The same program through GnuCOBOL and through its translation; the differences compare() finds."""
    import tempfile
    from types import SimpleNamespace

    from seance.cases import Case, compare, run_cobol, run_python
    from seance.model import load_model
    from seance.recorder import compile_legacy
    from seance.translate import translate

    root = Path(tempfile.mkdtemp(prefix="seance_probe_"))
    (root / "legacy" / "t1").mkdir(parents=True)
    (root / "legacy" / "t1" / "t1.cbl").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    model = load_model("t1", root)
    exe = compile_legacy("t1", root)
    tr = translate("t1", root)
    assert not tr.unsupported, tr.unsupported
    ns = {"__name__": "t1", "__file__": str(root / "t1.py")}
    exec(compile(tr.code, ns["__file__"], "exec"), ns)
    case = Case()
    want = run_cobol(exe, model, case, 20)
    got = run_python(SimpleNamespace(main=ns["main"], __file__=ns["__file__"]), case)
    diffs, _ = compare(model, want, got)
    return want, got, diffs


@pytest.mark.parametrize("name", sorted(p.stem for p in PROBES.glob("*.cbl")))
def test_probe_programs_match_gnucobol(name):
    """Each program in tests/probes was measured on GnuCOBOL 3.1.2 when its behaviour was added (INSPECT in one pass, SEARCH ALL as a
    binary search, SET on an index item, switches, negative zero, function arguments, symbolic characters, exponentiation)."""
    want, got, diffs = _both(PROBES / f"{name}.cbl")
    assert not diffs, (want.stdout, got.stdout)


def test_loops_written_over_two_lines_are_counted(tmp_path):
    from seance.model import load_model
    from seance.programs import _derived_purpose

    src = ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. LP.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n"
           "       01 N PIC 9 VALUE 0.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n           PERFORM BUMP\n               UNTIL N > 3\n"
           "           STOP RUN.\n       BUMP.\n           ADD 1 TO N.\n")
    (tmp_path / "legacy" / "lp").mkdir(parents=True)
    (tmp_path / "legacy" / "lp" / "lp.cbl").write_text(src, encoding="utf-8")
    assert "1 loop" in _derived_purpose(load_model("lp", tmp_path))