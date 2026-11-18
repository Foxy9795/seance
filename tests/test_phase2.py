import pytest

from seance import mcp_server
from seance.recorder import cobc_available
from seance.spec import generate_spec

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")


def test_spec_covers_every_statement():
    for program in ("payroll", "interest", "inventory", "loan", "accounts"):
        spec = generate_spec(program)
        assert spec.review == [], spec.review
        assert "Where values can silently change" in spec.markdown


def test_spec_links_lines_and_rounding():
    md = generate_spec("payroll").markdown
    assert "### PROCESS-PARA (line 33)" in md
    assert "rounded half away from zero" in md
    assert "with extra decimals cut off" in md


def test_unknown_program_is_rejected():
    with pytest.raises(ValueError, match="unknown program"):
        mcp_server.describe_program("nope")


def test_wrong_width_is_rejected():
    with pytest.raises(ValueError, match="record width"):
        mcp_server.run_legacy_program("payroll", ["X" * 40])


@needs_cobol
def test_run_legacy_program_returns_ground_truth():
    out = mcp_server.run_legacy_program("payroll", ["A1    075000001"])
    assert out == "A1    0000009300000009-00001166"


def test_tools_are_registered():
    import asyncio

    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"describe_program", "run_legacy_program", "verify_migration"} <= names


