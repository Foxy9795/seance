"""MCP server that lets Kiro run the legacy COBOL program and the Séance verifier.

Start (stdio): python -m seance.mcp_server
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .codegen import generate_records_module
from .recorder import ROOT, LegacyRuntimeError, cobc_available, compile_legacy, get_model, record_fixtures, run_legacy
from .report import to_markdown, write_reports
from .spec import generate_spec
from .verify import verify

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

mcp = FastMCP("seance")

MAX_LINES = 500


def _programs() -> list[str]:
    return sorted(p.name for p in (ROOT / "legacy").iterdir() if (p / f"{p.name}.cbl").exists())


def _check(program: str) -> None:
    if program not in _programs():
        raise ValueError(f"unknown program {program!r}. Available: {', '.join(_programs())}")


@mcp.tool()
def list_programs() -> str:
    """List the legacy COBOL programs Séance knows about and whether the COBOL runtime is available."""
    runtime = "available" if cobc_available() else "MISSING (GnuCOBOL not found)"
    return f"COBOL runtime: {runtime}\nPrograms: {', '.join(_programs())}"


@mcp.tool()
def describe_program(program: str) -> str:
    """Plain-English spec of a legacy program: record layouts, behavior by paragraph with line numbers,
    where values silently round or truncate, and any statements that need human review."""
    _check(program)
    return generate_spec(program).markdown


@mcp.tool()
def describe_layout(program: str) -> str:
    """Input and output record layouts (field, columns, type), the source format and the file names the program uses."""
    _check(program)
    try:
        model = get_model(program)
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc
    out = [f"{'fixed' if model.fixed else 'free'}-format source; reads {model.input.assign}, writes {model.output.assign}"]
    for label, layout in (("INPUT", model.in_layout), ("OUTPUT", model.out_layout)):
        out.append(f"{label} {layout.record_name} ({layout.width} chars per record)")
        for f in layout.fields:
            kind = {"alpha": f"text({f.width})", "edited": f"edited picture {f.pic}"}.get(f.kind, f"number digits={f.digits} decimals={f.scale} sign={f.sign}")
            out.append(f"  {f.name:<18} columns {f.offset + 1}-{f.offset + f.width}  {kind}")
    return "\n".join(out)


@mcp.tool()
def run_legacy_program(program: str, input_lines: list[str]) -> str:
    """Run the ORIGINAL compiled COBOL program on input records (one per line) and return its output records.
    This is the ground truth for what the program does. Each line must fit the input record width."""
    _check(program)
    if not input_lines or len(input_lines) > MAX_LINES:
        raise ValueError(f"send between 1 and {MAX_LINES} lines")
    try:
        model = get_model(program)
        width = model.in_layout.width
        for i, line in enumerate(input_lines):
            if len(line.rstrip()) > width:
                raise ValueError(f"line {i + 1} is {len(line.rstrip())} chars, record width is {width}")
        output = run_legacy(compile_legacy(program), [l.rstrip() for l in input_lines], model)
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc
    return "\n".join(output)


@mcp.tool()
def generate_records(program: str) -> str:
    """Regenerate generated/<program>_records.py (parse/format classes) from the copybooks."""
    _check(program)
    return f"wrote {generate_records_module(program).relative_to(ROOT).as_posix()}"


@mcp.tool()
def record_legacy_fixtures(program: str) -> str:
    """Run the original program on generated edge-case and random inputs and store the results as fixtures."""
    _check(program)
    try:
        return f"recorded fixtures: {record_fixtures(program)}"
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def verify_migration(program: str, implementation: str = "", examples: int = 30) -> str:
    """Check a Python migration against the real COBOL program (recorded fixtures plus property-based tests).
    `implementation` is a module path such as migrated.payroll (default: migrated.<program>).
    Returns the Séance report. 'Spirit restless' means the Python is wrong, not the fixtures."""
    _check(program)
    if not 5 <= examples <= 200:
        raise ValueError("examples must be between 5 and 200")
    try:
        report = verify(program, implementation or None, examples)
    except (LegacyRuntimeError, ImportError) as exc:
        raise ValueError(str(exc)) from exc
    write_reports(report, ROOT)
    return to_markdown(report)


if __name__ == "__main__":
    mcp.run()
