"""Command line entry point: python -m seance <command> <program>."""

from __future__ import annotations

import argparse
import json
import sys

from .programs import program_names
from .recorder import ROOT, compile_legacy, get_model
from .report import to_dict, to_markdown, write_reports
from .spec import write_spec

COMMANDS = ["analyze", "spec", "record", "translate", "verify", "mutate", "try", "export", "all"]
TRY_LIMIT = 200  # input lines per file in one try


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def _shown(model, result) -> dict:
    from .cases import _units, show

    outs = {}
    for name, data in result.outputs.items():
        f = next((x for x in model.all_files if x.assign == name), None)
        outs[name] = [show(u) for u in _units(f, data)]
    return {"outputs": outs, "stdout": result.stdout, "return_code": result.return_code, "error": result.error}


def try_input(program: str, implementation: str, body: dict) -> dict:
    """Run the COBOL and the Python on input a person typed (or on a saved set) and show both results."""
    from .cases import ENC, Case, compare, load_set, pack_file, run_cobol, run_python
    from .verify import load_implementation

    model = get_model(program)
    if body.get("set"):
        case, _, _ = load_set(program, body["set"])
    else:
        case = Case(stdin=[str(x) for x in body.get("stdin", [])][:TRY_LIMIT])
        files = body.get("files", {})
        for f in model.inputs:
            lines = [str(x) for x in files.get(f.assign, [])][:TRY_LIMIT]
            recs = [line.encode(ENC, errors="replace") for line in lines]
            case.records[f.assign] = recs
            case.files[f.assign] = pack_file(f, recs)
    impl = load_implementation(implementation)
    from .config import RUN_TIMEOUT

    cobol = run_cobol(compile_legacy(program), model, case, RUN_TIMEOUT)
    python = run_python(impl, case)
    diffs, units = compare(model, cobol, python)
    return {"cobol": _shown(model, cobol), "python": _shown(model, python), "diffs": [d.to_dict() for d in diffs[:50]],
            "compared": units, "match": not diffs}


def _analyze(program: str) -> None:
    from .layout import leaves

    model = get_model(program)
    print(f"{'fixed' if model.fixed else 'free'}-format source; {model.describe_io()}")
    for f in model.all_files:
        print(f"{f.assign} ({f.organization}, {', '.join(sorted(f.modes))}): {f.size} bytes per record")
        for lf in leaves(f.record) if f.record else []:
            it = lf.item
            print(f"  {lf.name:<22} {it.kind:<6} {it.usage:<7} digits={it.digits} scale={it.scale} bytes {lf.offset + 1}-{lf.offset + lf.width}")
    for item in model.unsupported:
        print("not runnable yet:", item)
    for note in model.notes:
        print("note:", note)


def _job_command(a) -> int:
    from .jobs import describe, record, verify_job

    try:
        if a.command == "analyze":
            for s in describe(a.program)["steps"]:
                print(f"{s['step']:<10} {s['pgm']:<10} " + ", ".join(f"{d['dd']}={d['what']}" for d in s["dds"]))
            return 0
        if a.command in ("record", "all"):
            print("recorded", record(a.program))
        if a.command in ("verify", "all"):
            report = verify_job(a.program, a.rounds)
            write_reports(report, ROOT)
            if a.json:
                body = to_dict(report, ROOT)
                body["markdown"] = to_markdown(report, ROOT)
                _emit(body)
            else:
                print(to_markdown(report, ROOT))
            return 0 if report.matched else 1
        if a.command not in ("record", "all", "verify"):
            raise ValueError(f"{a.command} is not available for a job; use analyze, record or verify")
        return 0
    except Exception as exc:
        if a.json:
            _emit({"error": str(exc)})
            return 2
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="seance")
    p.add_argument("command", choices=COMMANDS)
    p.add_argument("program")
    p.add_argument("--impl", help="python module to check (default migrated.<program>)")
    p.add_argument("--rounds", "--examples", type=int, default=40, dest="rounds", help="random runs")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    a = p.parse_args(argv)
    sys.path.insert(0, str(ROOT))

    from .jobs import job_names

    if a.program in job_names():
        return _job_command(a)
    if a.program not in program_names():
        print(f"unknown program {a.program!r}. Available: {', '.join(program_names() + job_names())}", file=sys.stderr)
        return 2
    implementation = a.impl or f"migrated.{a.program}"

    try:
        if a.command == "analyze":
            _analyze(a.program)
            return 0
        if a.command == "translate":
            from .programs import draft_python

            result = draft_python(a.program, ROOT, overwrite=True)
            if a.json:
                _emit(result)
            elif result["translated"]:
                print(f"wrote migrated/{a.program}.py: {result['statements']} statements, {len(result['gaps'])} gaps")
                for g in result["gaps"]:
                    print(f"  line {g['line']}: {g['text']}  ({g['why']})")
            else:
                print(f"could not translate: {result.get('reason')}")
            return 0
        if a.command == "mutate":
            from .mutate import run_mutants

            result = run_mutants(a.program, implementation)
            if a.json:
                _emit(result)
            elif "error" in result:
                print(result["error"])
            else:
                print(f"caught {result['caught']} of {result['total']} planted bugs using {result['records']} saved records")
                for m in result["mutants"]:
                    print(f"  {'caught  ' if m['caught'] else 'SURVIVED'} line {m['cobol_line'] or m['line']}: {m['change']}")
            return 0 if "error" not in result else 2
        if a.command == "try":
            _emit(try_input(a.program, implementation, json.loads(sys.stdin.read() or "{}")))
            return 0
        if a.command == "export":
            from .export import bundle

            name, data = bundle(a.program, implementation)
            out = ROOT / "build" / name
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(data)
            print(f"wrote {out}")
            return 0
        if a.command in ("spec", "all"):
            print("spec", write_spec(a.program))
        if a.command in ("record", "all"):
            from .cases import record_sets

            print("recorded", record_sets(a.program))
        if a.command in ("verify", "all"):
            from .verify import verify

            report = verify(a.program, implementation, a.rounds)
            write_reports(report, ROOT)
            if a.json:
                body = to_dict(report, ROOT)
                body["markdown"] = to_markdown(report, ROOT)
                _emit(body)
            else:
                print(to_markdown(report, ROOT))
            return 0 if report.matched else 1
        return 0
    except Exception as exc:  # report, do not traceback: this feeds the UI
        if a.json or a.command == "try":
            _emit({"error": f"{type(exc).__name__}: {exc}" if not isinstance(exc, (ValueError, RuntimeError)) else str(exc)})
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
