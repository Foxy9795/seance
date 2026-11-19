"""MCP server that lets Kiro run the legacy COBOL program and the Séance checker.

Start (stdio): python -m seance.mcp_server
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .recorder import ROOT, LegacyRuntimeError, cobc_available, get_model
from .report import to_markdown, write_reports
from .spec import generate_spec
from .verify import verify

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

mcp = FastMCP("seance")

MAX_LINES = 500


def _programs() -> list[str]:
    from .programs import program_names

    return program_names(ROOT)


def _check(program: str) -> None:
    if program not in _programs():
        raise ValueError(f"unknown program {program!r}. Available: {', '.join(_programs())}")


def _model(program: str):
    try:
        return get_model(program)
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def list_programs() -> str:
    """List the legacy COBOL programs Séance knows about, what files each reads and writes, and whether the COBOL runtime is available."""
    runtime = "available" if cobc_available() else "MISSING (GnuCOBOL not found)"
    lines = [f"COBOL runtime: {runtime}"]
    for name in _programs():
        try:
            lines.append(f"- {name}: {get_model(name).describe_io()}")
        except LegacyRuntimeError as exc:
            lines.append(f"- {name}: cannot be read ({exc})")
    return "\n".join(lines)


@mcp.tool()
def list_samples() -> str:
    """List the sample programs that ship with Séance (not in the workspace until loaded), and which are already loaded."""
    from .samples import catalog
    lines = []
    for s in catalog(ROOT)["samples"]:
        lines.append(f"- {s['name']}{' (loaded)' if s['loaded'] else ''}: {s['summary']}")
    return "\n".join(lines)


@mcp.tool()
def load_sample(name: str) -> str:
    """Copy a sample program (with its saved test data and Python) into the workspace so it can be described, checked and edited."""
    from .programs import ProgramError
    from .samples import install
    try:
        result = install(name, ROOT)
    except ProgramError as exc:
        raise ValueError(str(exc)) from exc
    return f"loaded: {', '.join(result['added']) or 'nothing new'}" + (f" (already there: {', '.join(result['already'])})" if result["already"] else "")


@mcp.tool()
def describe_program(program: str) -> str:
    """Plain-English spec of a legacy program: record layouts, behavior by paragraph with line numbers,
    where values silently round or truncate, and any statements that need human review."""
    _check(program)
    return generate_spec(program).markdown


@mcp.tool()
def describe_layout(program: str) -> str:
    """Every file the program uses with its record layout (field, bytes, type, storage), plus console input."""
    _check(program)
    from .layout import leaves

    model = _model(program)
    out = [f"{'fixed' if model.fixed else 'free'}-format source; {model.describe_io()}"]
    for f in model.all_files:
        out.append(f"{f.assign} ({'text lines' if f.organization == 'line' else 'fixed records'}, {', '.join(sorted(f.modes))}): "
                   f"record {f.record.name if f.record else '?'}, {f.size} bytes")
        for lf in leaves(f.record) if f.record else []:
            it = lf.item
            kind = {"alpha": f"text({it.size})", "edited": f"edited picture {it.pic}"}.get(
                it.kind, f"number digits={it.digits} decimals={it.scale} signed={it.signed} storage={it.usage}")
            out.append(f"  {lf.name:<22} bytes {lf.offset + 1}-{lf.offset + lf.width}  {kind}")
    if model.all_accepts:
        out.append("Console input (ACCEPT): " + ", ".join(model.all_accepts))
    for item in model.unsupported:
        out.append(f"Not runnable yet: {item}")
    return "\n".join(out)


@mcp.tool()
def run_legacy_program(program: str, input_lines: list[str] | None = None, input_files: dict[str, list[str]] | None = None,
                       console_input: list[str] | None = None) -> str:
    """Run the ORIGINAL compiled COBOL program and return everything it produced: each output file, the console
    output and the return code. This is the ground truth for what the program does.
    input_lines: records for the program's only input file, one per line.
    input_files: records per input file name (the ASSIGN name), for programs with several inputs.
    console_input: lines typed at the console, for programs that ACCEPT."""
    _check(program)
    from .cases import ENC, Case, _units, pack_file, run_cobol, show
    from .recorder import compile_legacy

    model = _model(program)
    files = dict(input_files or {})
    if input_lines is not None:
        if len(model.inputs) != 1:
            raise ValueError(f"{program} has {len(model.inputs)} input files; use input_files with names {[f.assign for f in model.inputs]}")
        files[model.inputs[0].assign] = input_lines
    case = Case(stdin=list(console_input or [])[:MAX_LINES])
    for f in model.inputs:
        lines = files.get(f.assign, [])
        if len(lines) > MAX_LINES:
            raise ValueError(f"send at most {MAX_LINES} lines per file")
        recs = [line.encode(ENC, errors="replace") for line in lines]
        case.records[f.assign] = recs
        case.files[f.assign] = pack_file(f, recs)
    try:
        result = run_cobol(compile_legacy(program), model, case)
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc
    out = []
    for name, data in result.outputs.items():
        f = next((x for x in model.all_files if x.assign == name), None)
        out.append(f"== {name}")
        out += [show(u) for u in _units(f, data)]
    out.append("== console")
    out.append(result.stdout.rstrip("\n"))
    out.append(f"== return code {result.return_code}" + (f", runtime error: {result.error}" if result.error else ""))
    return "\n".join(out)


@mcp.tool()
def record_legacy_fixtures(program: str) -> str:
    """Run the original program on generated edge-case and random input and save the results as test sets."""
    _check(program)
    from .cases import record_sets

    try:
        return f"recorded test sets: {record_sets(program)}"
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def draft_python(program: str) -> str:
    """Translate the COBOL into a Python program at migrated/<program>.py (the old file is kept as .bak).
    Every line is tagged with its COBOL line. Statements it cannot translate raise NotImplementedError naming the
    line, and are listed in the result: replace those by hand, then call verify_migration."""
    _check(program)
    from .programs import draft_python as _draft
    result = _draft(program, ROOT, overwrite=True)
    if not result["translated"]:
        return f"Could not translate: {result.get('reason')}. An empty starter was written instead."
    lines = [f"Wrote migrated/{program}.py: {result['statements']} statements, {len(result['gaps'])} need a person."]
    lines += [f"  line {g['line']}: {g['text']} ({g['why']})" for g in result["gaps"]]
    return "\n".join(lines)


@mcp.tool()
def measure_test_strength(program: str, implementation: str = "") -> str:
    """Plant small bugs in the Python one at a time (> to >=, ROUNDED dropped, a constant changed) and replay the
    saved test sets. Reports how many were caught and the COBOL line of each survivor: a survivor is a spot the
    tests never exercise, so add data that reaches it."""
    _check(program)
    from .mutate import run_mutants

    r = run_mutants(program, implementation or None)
    if "error" in r:
        raise ValueError(r["error"])
    out = [f"Caught {r['caught']} of {r['total']} planted bugs with {r['records']} saved records."]
    for m in r["mutants"]:
        where = f"COBOL line {m['cobol_line']}" if m["cobol_line"] else f"Python line {m['line']}"
        out.append(f"  {'caught  ' if m['caught'] else 'SURVIVED'} {where}: {m['change']}")
    return "\n".join(out)


@mcp.tool()
def verify_migration(program: str, implementation: str = "", examples: int = 30) -> str:
    """Check a Python migration against the real COBOL program: saved test sets plus fresh random runs of both.
    `implementation` is a module path such as migrated.payroll (default: migrated.<program>).
    Returns the Séance report. 'Spirit restless' means the Python is wrong, not the test data."""
    _check(program)
    if not 5 <= examples <= 200:
        raise ValueError("examples must be between 5 and 200")
    try:
        report = verify(program, implementation or None, examples)
    except (LegacyRuntimeError, ImportError) as exc:
        raise ValueError(str(exc)) from exc
    write_reports(report, ROOT)
    return to_markdown(report, ROOT)


if __name__ == "__main__":
    mcp.run()
