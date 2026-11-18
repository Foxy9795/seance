"""Command line entry point: python -m seance <command> <program>."""

from __future__ import annotations

import argparse
import json
import sys

from .codegen import generate_records_module
from .programs import program_names
from .recorder import ROOT, compile_legacy, get_model, record_fixtures, run_legacy
from .report import to_dict, to_markdown, write_reports
from .spec import write_spec

COMMANDS = ["analyze", "spec", "generate", "record", "translate", "verify", "mutate", "compare", "export", "all"]


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _compare(program: str, implementation: str, lines: list[str]) -> dict:
    """Run the same input lines through the real COBOL and the Python migration."""
    from .verify import _modules, first_diff_field, run_python

    records, impl = _modules(program, implementation)
    model = get_model(program)
    out_layout = model.out_layout
    legacy = run_legacy(compile_legacy(program), lines, model)
    python = run_python(records, impl, lines)
    if len(legacy) != len(lines):
        raise ValueError(f"The COBOL wrote {len(legacy)} records for {len(lines)} inputs, so outputs cannot be paired.")
    rows = []
    for i, line in enumerate(lines):
        legacy_out = legacy[i]
        py_out = python[i]
        same = legacy_out == py_out
        rows.append({"input": line, "legacy": legacy_out, "python": py_out, "match": same, "field": None if same else first_diff_field(out_layout, legacy_out, py_out)})
    return {"rows": rows}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="seance")
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("program")
    p.add_argument("--impl", help="python module to verify (default migrated.<program>)")
    p.add_argument("--examples", type=int, default=100, help="property test batches")
    p.add_argument("--json", action="store_true", help="machine-readable output (verify, compare)")
    p.add_argument("--line", action="append", default=[], help="input record for compare (repeatable)")
    a = p.parse_args(argv)
    sys.path.insert(0, str(ROOT))

    if a.program not in program_names():
        print(f"unknown program {a.program!r}. Available: {', '.join(program_names())}", file=sys.stderr)
        return 2
    implementation = a.impl or f"migrated.{a.program}"

    if a.command == "analyze":
        model = get_model(a.program)
        print(f"{'fixed' if model.fixed else 'free'}-format source; reads {model.input.assign} ({model.input.organization}), writes {model.output.assign} ({model.output.organization})")
        for label, layout in (("input", model.in_layout), ("output", model.out_layout)):
            print(f"{label}: {layout.record_name}, {layout.width} chars")
            for f in layout.fields:
                print(f"  {f.name:<18} {f.kind:<8} digits={f.digits} scale={f.scale} sign={f.sign} cols={f.offset}-{f.offset + f.width}")
        for note in model.notes:
            print("note:", note)
        return 0

    if a.command == "translate":
        from .programs import draft_python

        result = draft_python(a.program, ROOT, overwrite=True)
        if a.json:
            _emit(result)
        else:
            print(f"wrote migrated/{a.program}.py: {result.get('statements')} statements, {len(result.get('gaps', []))} gaps" if result["translated"] else f"could not translate: {result.get('reason')}")
            for g in result.get("gaps", []):
                print(f"  line {g['line']}: {g['text']}  ({g['why']})")
        return 0

    if a.command == "mutate":
        from .mutate import run_mutants

        try:
            result = run_mutants(a.program, implementation)
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        if a.json:
            _emit(result)
        elif "error" in result:
            print(result["error"])
        else:
            print(f"caught {result['caught']} of {result['total']} planted bugs using {result['records']} saved records")
            for m in result["mutants"]:
                print(f"  {'caught  ' if m['caught'] else 'SURVIVED'} line {m['cobol_line'] or m['line']}: {m['change']}")
        return 0 if "error" not in result else 2

    if a.command == "export":
        from .export import bundle

        name, data = bundle(a.program, implementation)
        out = ROOT / "build" / name
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(data)
        print(f"wrote {out}")
        return 0

    if a.command == "compare":
        try:
            _emit(_compare(a.program, implementation, a.line))
            return 0
        except Exception as exc:  # report, do not traceback: this feeds the UI
            _emit({"error": f"{type(exc).__name__}: {exc}"})
            return 2

    if a.command in ("spec", "all"):
        print("spec", write_spec(a.program))
    if a.command in ("generate", "all"):
        print("generated", generate_records_module(a.program))
    if a.command in ("record", "all"):
        print("recorded", record_fixtures(a.program))
    if a.command in ("verify", "all"):
        from .verify import verify

        try:
            report = verify(a.program, implementation, a.examples)
        except Exception as exc:
            if a.json:
                _emit({"error": f"{type(exc).__name__}: {exc}"})
                return 2
            raise
        write_reports(report, ROOT)
        if a.json:
            body = to_dict(report)
            body["markdown"] = to_markdown(report)
            _emit(body)
        else:
            print(to_markdown(report))
        return 0 if report.matched else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

