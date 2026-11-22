"""Command line entry point: python -m seance <command> <program>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .programs import program_names
from .recorder import ROOT, compile_legacy, get_model
from .report import to_dict, to_markdown, write_reports
from .spec import write_spec

COMMANDS = ["analyze", "spec", "record", "translate", "verify", "mutate", "fill-gaps", "try", "export", "all"]
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


def _serve(argv: list[str]) -> int:
    """Start the app on this machine only, and open it in the browser."""
    import threading
    import webbrowser

    from . import config

    p = argparse.ArgumentParser(prog="seance serve", description="Start the Séance app.")
    p.add_argument("--port", type=int, default=config.PORT)
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    a = p.parse_args(argv)
    import uvicorn

    url = f"http://127.0.0.1:{a.port}"
    if not a.no_browser:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    print(f"Séance is running at {url}  (Ctrl+C to stop)")
    uvicorn.run("seance.api:app", host="127.0.0.1", port=a.port, log_level="warning")  # always local: it runs the code you give it
    return 0


def _bigcheck(argv: list[str]) -> int:
    """Run the real COBOL and the Python on one file of any size and compare every output byte. Nothing is saved: for a file too big
    to be a test set in the app (it keeps uploaded files in memory and in the saved set)."""
    import hashlib
    import importlib
    import time

    from .cases import Case, run_cobol, run_python
    from .recorder import LegacyRuntimeError, compile_legacy, get_model

    p = argparse.ArgumentParser(prog="seance bigcheck", description="Run the COBOL and the Python on one big input file and compare the outputs byte for byte.")
    p.add_argument("program")
    p.add_argument("file", help="the input file")
    p.add_argument("--input", metavar="ASSIGN", help="which input file of the program this is (when it has several)")
    p.add_argument("--code-page", metavar="CP", help="the file is EBCDIC from a mainframe, for example cp037")
    p.add_argument("--impl", metavar="MODULE", help="python module to check (default migrated.<program>)")
    p.add_argument("--keep", metavar="DIR", help="also write the COBOL's outputs to this folder")
    a = p.parse_args(argv)
    path = Path(a.file)
    if not path.is_file():
        print(f"{path} is not a file.", file=sys.stderr)
        return 2
    try:
        model = get_model(a.program)
    except Exception as exc:  # noqa: BLE001
        print(f"{a.program}: {exc}", file=sys.stderr)
        return 2
    inputs = model.inputs
    if not inputs:
        print(f"{a.program} reads no input file, so there is nothing to feed it.", file=sys.stderr)
        return 2
    f = next((x for x in inputs if a.input in (x.assign, x.name)), None) if a.input else (inputs[0] if len(inputs) == 1 else None)
    if f is None:
        print(("No input file is called " + a.input + ". " if a.input else "The program reads several files; say which one this is with --input. ")
              + "Its input files: " + ", ".join(x.assign for x in inputs), file=sys.stderr)
        return 2
    data = path.read_bytes()
    if a.code_page:
        from .ebcdic import file_to_ascii

        data = file_to_ascii(f.record, f.size, data, a.code_page) if f.organization != "line" else data.decode(a.code_page).encode("latin-1", errors="replace")
    if f.organization in ("sequential", "indexed", "relative") and len(data) % max(f.size, 1):
        print(f"The file is {len(data)} bytes, which is not a whole number of {f.size}-byte records for {f.assign}.", file=sys.stderr)
        return 2
    case = Case(files={f.assign: data}, stdin=[])
    print(f"{a.program}: {len(data):,} bytes into {f.assign}")
    try:
        exe = compile_legacy(a.program)
        t = time.time()
        cobol = run_cobol(exe, model, case, timeout=24 * 3600)
        t_cobol = time.time() - t
    except LegacyRuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"  COBOL   {t_cobol:8.1f} s   return code {cobol.return_code}   {cobol.error or ''}")
    t = time.time()
    py = run_python(importlib.import_module(a.impl or f"migrated.{a.program}"), case, limit=24 * 3600)
    print(f"  Python  {time.time() - t:8.1f} s   return code {py.return_code}   {py.error or ''}")
    if a.keep:
        Path(a.keep).mkdir(parents=True, exist_ok=True)
        for k, v in cobol.outputs.items():
            (Path(a.keep) / k).write_bytes(v)
    same = True
    for k in sorted(set(cobol.outputs) | set(py.outputs)):
        x, y = cobol.outputs.get(k, b""), py.outputs.get(k, b"")
        ok = x == y
        same &= ok
        print(f"  {k}: {len(x):,} bytes (COBOL) {len(y):,} bytes (Python) sha256 {hashlib.sha256(x).hexdigest()[:16]} / {hashlib.sha256(y).hexdigest()[:16]}  {'same' if ok else 'DIFFERENT'}")
        if not ok:
            at = next((i for i in range(min(len(x), len(y))) if x[i] != y[i]), min(len(x), len(y)))
            size = next((o.size for o in model.all_files if o.assign == k and o.size), 0)
            where = f" (record {at // size + 1}, byte {at % size + 1})" if size and next((o.organization for o in model.all_files if o.assign == k), "") != "line" else ""
            print(f"    first difference at byte {at:,}{where}")
            print(f"    COBOL : {x[max(0, at - 20):at + 40]!r}")
            print(f"    Python: {y[max(0, at - 20):at + 40]!r}")
    if cobol.stdout != py.stdout or cobol.return_code != py.return_code or bool(cobol.error) != bool(py.error):
        same = False
        print("  the console output or the return code differs")
    print("Spirit matched: every output byte is the same." if same else "Spirit restless: the Python gives a different answer.")
    return 0 if same else 1


def _check_all(argv: list[str]) -> int:
    """Check every program and job in the workspace: the command for a build pipeline. Exit code 1 when anything is restless."""
    import time

    from . import config
    from .jobs import job_names
    from .report import junit_xml

    p = argparse.ArgumentParser(prog="seance check-all", description="Check every program and job against the real COBOL.")
    p.add_argument("--rounds", type=int, default=config.DEFAULT_ROUNDS, help="random runs per program")
    p.add_argument("--junit", metavar="FILE", help="write JUnit XML for a CI system")
    p.add_argument("--only", metavar="NAMES", help="comma-separated program or job names")
    a = p.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    jobs = job_names()
    names = [n for n in program_names() + jobs if not a.only or n in {x.strip() for x in a.only.split(",")}]
    if not names:
        print("There is nothing to check: the workspace has no programs.", file=sys.stderr)
        return 2
    results, began = [], time.time()
    for n in names:
        t = time.time()
        try:
            if n in jobs:
                from .jobs import verify_job

                report = verify_job(n, a.rounds)
            else:
                from .verify import verify

                report = verify(n, None, a.rounds)
            write_reports(report, ROOT)
            differing = sum(s["differing"] for s in report.sets)
            results.append({"name": n, "matched": report.matched, "seconds": time.time() - t,
                            "summary": f"{differing} output line(s) differ" + (", and a random run fails" if report.random_failure else ""),
                            "detail": to_markdown(report, ROOT)[:4000], "lines": sum(s["compared"] for s in report.sets)})
        except Exception as exc:
            results.append({"name": n, "matched": False, "error": f"{type(exc).__name__}: {exc}", "seconds": time.time() - t, "summary": "could not run", "lines": 0})
        r = results[-1]
        print(f"{'Spirit matched ' if r['matched'] else 'Spirit restless'}  {n:<24} {r['lines']:>6} lines  {r['seconds']:.1f}s" + ("" if r["matched"] else f"  {r.get('error') or r['summary']}"), flush=True)
    if a.junit:
        Path(a.junit).write_text(junit_xml(results, time.time() - began), encoding="utf-8")
        print(f"JUnit report: {a.junit}")
    bad = [r for r in results if not r["matched"]]
    print(f"\n{len(results) - len(bad)} of {len(results)} matched.")
    return 1 if bad else 0


def _samples(argv: list[str]) -> int:
    from .programs import ProgramError
    from .samples import catalog, install, remove_all

    p = argparse.ArgumentParser(prog="seance samples", description="The sample library the guide loads from.")
    p.add_argument("action", choices=["list", "load", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("--all", action="store_true", help="with load: every sample in the library")
    a = p.parse_args(argv)
    try:
        if a.action == "list":
            for s in catalog()["samples"]:
                print(f"{'*' if s['loaded'] else ' '} {s['name']:<18} {s['summary']}")
            print("\n* already in the workspace")
        elif a.action == "load":
            if not a.name and not a.all:
                p.error("load needs a sample name, or --all")
            for name in [s["name"] for s in catalog()["samples"]] if a.all else [a.name]:
                r = install(name)
                print("loaded:", ", ".join(r["added"]) or "nothing new", f"(already there: {', '.join(r['already'])})" if r["already"] else "")
        else:
            gone = remove_all()
            print("removed:", ", ".join(gone) or "nothing (no sample programs are loaded)")
    except ProgramError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _setup(argv: list[str]) -> int:
    """GnuCOBOL 3.1.2 (downloaded and checked on Windows), and on request Kiro's MCP settings for this folder."""
    from .toolchain import ToolchainError, install, mcp_config, write_mcp_config

    p = argparse.ArgumentParser(prog="seance setup", description="Get GnuCOBOL 3.1.2: on Windows it is downloaded, checked against a fixed "
                                "SHA-256 and unpacked into tools/gnucobol. Nothing already installed is changed.")
    p.add_argument("--mcp-config", action="store_true", help="also write .kiro/settings/mcp.json with this folder's paths (other settings are kept)")
    p.add_argument("--print-mcp-config", action="store_true", help="print the MCP settings for this folder and change nothing")
    a = p.parse_args(argv)
    target = ROOT / ".kiro" / "settings" / "mcp.json"
    if a.print_mcp_config:
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
        print(json.dumps(mcp_config(ROOT, existing), indent=2))
        return 0
    try:
        r = install()
    except ToolchainError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"GnuCOBOL {'was already installed' if r['status'] == 'present' else 'is installed'}: {r['version']} ({r['cobc']})")
    if a.mcp_config:
        try:
            write_mcp_config(target, ROOT)
        except ToolchainError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"wrote {target}")
    print("Next: python -m seance doctor")
    return 0


OVERVIEW = """Séance {version}: rewrite COBOL in Python, and prove it gives the same answers.

Start here
  seance serve                     the app, at http://127.0.0.1:8000
  seance setup [--mcp-config]      GnuCOBOL 3.1.2 (downloaded and checked on Windows); Kiro's MCP settings
  seance doctor                    check this machine, with a fix for each problem

MCP (Kiro, VS Code, Cursor, Claude, Windsurf, Gemini, Antigravity, Codex)
  seance mcp-config --client NAME  the settings for that client (--mode local|portable|http, --write)
  seance mcp [--http]              run the MCP server (stdio, or HTTP on 127.0.0.1:8765)

Workspace
  seance samples list|load|remove  the sample library (load NAME, or load --all)
  seance check-all [--junit FILE]  check every program and job; exit code 1 if any is restless
seance bigcheck PROGRAM FILE     run the COBOL and the Python on one big input file (any size) and compare every byte

One program
  seance COMMAND PROGRAM [--impl MODULE] [--rounds N] [--json]
  COMMAND is one of: {commands}

  seance COMMAND --help shows the options of a command. The README has the full guide."""


def _home_problem() -> str | None:
    """Séance works on the folder it was cloned into (its workspace, page and samples live there). An installed copy
    without that folder cannot run, and says so instead of failing later."""
    missing = [p for p in ("web/index.html", "samples/catalog.json") if not (ROOT / p).exists()]
    if not missing:
        return None
    return (f"Séance could not find its folder: {', '.join(missing)} is missing under {ROOT}.\n"
            "Séance runs from a clone of its repository. Clone it, then install it in place: pip install -e .")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        from . import __version__

        print(OVERVIEW.format(version=__version__, commands=", ".join(COMMANDS)))
        return 0
    if argv[0] not in ("--version", "-V") and (problem := _home_problem()):
        print(problem, file=sys.stderr)
        return 2
    if argv and argv[0] in ("--version", "-V"):
        from . import __version__

        print(f"seance {__version__}")
        return 0
    if argv and argv[0] == "setup":
        return _setup(argv[1:])
    if argv and argv[0] == "doctor":
        from .doctor import main as doctor_main

        return doctor_main(argv[1:])
    if argv and argv[0] == "serve":
        return _serve(argv[1:])
    if argv and argv[0] == "samples":
        return _samples(argv[1:])
    if argv and argv[0] == "check-all":
        return _check_all(argv[1:])
    if argv and argv[0] == "bigcheck":
        return _bigcheck(argv[1:])
    if argv and argv[0] == "mcp-config":
        from .mcp_clients import main as mcp_config_main

        return mcp_config_main(argv[1:])
    if argv and argv[0] == "mcp":
        from .mcp_server import main as mcp_main

        return mcp_main(argv[1:])
    p = argparse.ArgumentParser(prog="seance", epilog="Also: 'seance serve' starts the app; 'seance setup' gets GnuCOBOL; 'seance doctor' checks this machine; "
           "'seance check-all [--junit FILE]' checks the whole workspace (for CI); 'seance samples list|load|remove' manages the sample library; "
           "'seance --version'.")
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
        if a.command == "fill-gaps":
            from .gapfill import fill_gaps
            result = fill_gaps(a.program, implementation)
            if a.json:
                _emit(result)
            elif "error" in result:
                print(result["error"])
            else:
                print(f"test strength: {result['before']['caught']} of {result['before']['total']} caught before, "
                      f"{result['after']['caught']} of {result['after']['total']} after ({result['after']['equivalent']} judged equivalent)")
                for r in result["results"]:
                    print(f"  {r['status'].upper():<10} line {r['cobol_line'] or r['line']}: {r['change']}")
                    print(f"             {r['note']}")
                for name in result["saved"]:
                    print(f"  saved test set {name}")
            return 0 if "error" not in result else 2
        if a.command == "mutate":
            from .mutate import run_mutants

            result = run_mutants(a.program, implementation)
            if a.json:
                _emit(result)
            elif "error" in result:
                print(result["error"])
            else:
                extra = f" ({result['equivalent']} judged equivalent)" if result.get("equivalent") else ""
                print(f"caught {result['caught']} of {result['total']} planted bugs using {result['records']} saved records{extra}")
                for m in result["mutants"]:
                    tag = "caught  " if m["caught"] else ("EQUIVALENT" if m.get("verdict") == "equivalent" else "SURVIVED")
                    print(f"  {tag} line {m['cobol_line'] or m['line']}: {m['change']}")
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
