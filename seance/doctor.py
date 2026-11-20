"""Check that this machine can run Séance, and say how to fix what cannot:  python -m seance doctor

Nothing in the workspace is changed. The compile check builds a small program in a temporary folder and removes
it again; the workspace check writes and removes one empty file to see that the folders are writable.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__, config
from .recorder import ROOT, cobc_path

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DOCTOR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  RATE   PIC 9V999   VALUE 1.155.
       01  AMOUNT PIC S9(5)V99 VALUE -1234.56.
       01  RESULT PIC S9(7)V99.
       PROCEDURE DIVISION.
           COMPUTE RESULT ROUNDED = AMOUNT * RATE.
           DISPLAY "RESULT " RESULT.
           COMPUTE RESULT = AMOUNT * RATE.
           DISPLAY "TRUNCATED " RESULT.
           STOP RUN.
"""


@dataclass
class Check:
    level: str  # ok, warn, fail, skip
    name: str
    detail: str
    fix: str = ""


def _requirements(root: Path) -> list[tuple[str, str]]:
    path = root / "requirements.txt"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        m = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", line)
        if m:
            out.append((m.group(1), m.group(2).replace(" ", "")))
    return out


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _satisfies(version: str, spec: str) -> bool:
    have = _version_tuple(version)
    for part in filter(None, spec.split(",")):
        m = re.match(r"(>=|<=|==|<|>)(.+)", part)
        if not m:
            continue
        op, want = m.group(1), _version_tuple(m.group(2))
        n = max(len(have), len(want))
        a, b = have + (0,) * (n - len(have)), want + (0,) * (n - len(want))
        if not {">=": a >= b, "<=": a <= b, "==": a == b, "<": a < b, ">": a > b}[op]:
            return False
    return True


def check_python() -> Check:
    v = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info >= (3, 12):
        return Check("ok", "Python", f"{v} ({sys.executable})")
    return Check("fail", "Python", f"{v} is too old", "Install Python 3.12 or newer from python.org, then recreate .venv.")


def check_packages(root: Path) -> Check:
    found, problems = [], []
    for name, spec in _requirements(root):
        try:
            v = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name} is missing")
            continue
        (found if _satisfies(v, spec) else problems).append(f"{name} {v}" + ("" if _satisfies(v, spec) else f" (needs {spec})"))
    if problems:
        return Check("fail", "Python packages", "; ".join(problems), "Run: .venv\\Scripts\\python.exe -m pip install -e .")
    return Check("ok", "Python packages", ", ".join(found))


def check_gnucobol() -> Check:
    from .toolchain import cobc_version

    path = cobc_path()
    if not path:
        return Check("fail", "GnuCOBOL", "cobc was not found in tools\\gnucobol or on PATH", "Run: python -m seance setup")
    version = cobc_version(path)
    if not version:
        return Check("fail", "GnuCOBOL", f"{path} does not run", "Delete tools\\gnucobol and run: python -m seance setup")
    if "3.1.2" not in version:
        return Check("warn", "GnuCOBOL", f"{version} ({path})", "The samples and tests were recorded with GnuCOBOL 3.1.2. Other versions "
                     "can differ in edge cases; record your programs again with this one.")
    return Check("ok", "GnuCOBOL", f"{version} ({path})")


def check_round_trip() -> Check:
    """Compile a small program, run it, translate it, run the translation, and compare: the whole pipeline in one go."""
    if not cobc_path():
        return Check("skip", "Compile, run and compare", "needs GnuCOBOL")
    from types import SimpleNamespace

    from .cases import Case, compare, run_cobol, run_python
    from .model import load_model
    from .recorder import compile_legacy
    from .translate import translate

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="seance_doctor_") as tmp:
        root = Path(tmp)
        (root / "legacy" / "doctor").mkdir(parents=True)
        (root / "legacy" / "doctor" / "doctor.cbl").write_text(PROGRAM, encoding="utf-8")
        try:
            model = load_model("doctor", root)
            exe = compile_legacy("doctor", root)
            want = run_cobol(exe, model, Case(), 30)
            tr = translate("doctor", root)
            ns: dict = {"__name__": "seance_doctor", "__file__": str(root / "doctor.py")}
            exec(compile(tr.code, ns["__file__"], "exec"), ns)
            got = run_python(SimpleNamespace(main=ns["main"]), Case())
        except Exception as exc:  # any failure here is the finding
            return Check("fail", "Compile, run and compare", f"{type(exc).__name__}: {exc}"[:300],
                         "Run python -m seance setup, then this check again. If it still fails, report the message above.")
        diffs, _ = compare(model, want, got)
    took = time.monotonic() - t0
    if want.error or "RESULT" not in want.stdout:
        return Check("fail", "Compile, run and compare", f"the test program did not run: {want.error or want.stdout[:120]!r}",
                     "Run python -m seance setup, then this check again.")
    if diffs:
        return Check("fail", "Compile, run and compare", f"the translation differs from the COBOL: {diffs[0].expected!r} vs {diffs[0].actual!r}",
                     "This is a bug in Séance. Report it with the output of: python -m seance doctor --json")
    return Check("ok", "Compile, run and compare", f"a test program compiled, ran, and matched its Python translation ({took:.1f} s)")


def check_workspace(root: Path) -> Check:
    from .jobs import job_names
    from .programs import program_names

    bad = []
    for name in ("legacy", "fixtures", "migrated", "build"):
        d = root / name
        target = d if d.exists() else root  # a missing folder is created when it is first needed; its parent must be writable
        try:
            probe = target / ".seance_write_test"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            bad.append(f"{name}: {exc.strerror or exc}")
    if bad:
        return Check("fail", "Workspace", "; ".join(bad), "Run Séance from a folder you can write to.")
    n, j = len(program_names(root)), len(job_names(root))
    held = f"{n} program{'s' if n != 1 else ''}" + (f" and {j} job{'s' if j != 1 else ''}" if j else "")
    return Check("ok", "Workspace", f"{root} is writable ({held} in it)")


def check_app_files(root: Path) -> Check:
    missing = [p for p in ("web/index.html", "samples/catalog.json") if not (root / p).exists()]
    if missing:
        return Check("fail", "App files", "missing " + ", ".join(missing), "The folder is incomplete. Clone the repository again.")
    samples = len(json.loads((root / "samples" / "catalog.json").read_text(encoding="utf-8")).get("samples", []))
    return Check("ok", "App files", f"web/index.html and a sample library of {samples}")


def check_address(port: int = config.PORT) -> Check:
    where = f"127.0.0.1:{port}"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return Check("ok", "App address", f"{where} is free")
    try:
        with urllib.request.urlopen(f"http://{where}/api/about", timeout=2) as r:
            about = json.loads(r.read().decode("utf-8"))
        return Check("ok", "App address", f"Séance {about.get('version', '')} is already running at http://{where}")
    except (OSError, ValueError):
        return Check("warn", "App address", f"another program answers at {where}", f"Start Séance on another one: python -m seance serve --port {port + 1}")


def check_mcp(root: Path) -> Check:
    path = root / ".kiro" / "settings" / "mcp.json"
    fix = "Run: python -m seance setup --mcp-config   (writes this folder's paths into .kiro/settings/mcp.json, keeping other settings)"
    if not path.exists():
        return Check("warn", "Kiro MCP server", ".kiro/settings/mcp.json is missing", fix)
    try:
        entry = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {}).get("seance")
    except ValueError as exc:
        return Check("fail", "Kiro MCP server", f".kiro/settings/mcp.json is not valid JSON: {exc}", "Fix the file by hand; it was left alone.")
    if not entry:
        return Check("warn", "Kiro MCP server", "no server named seance in .kiro/settings/mcp.json", fix)
    if entry.get("disabled"):
        return Check("warn", "Kiro MCP server", "the seance server is disabled in .kiro/settings/mcp.json", "Set \"disabled\": false.")
    command = Path(entry.get("command", ""))
    resolved = command if command.is_absolute() else root / command
    if not resolved.exists():
        return Check("warn", "Kiro MCP server", f"its command {command} does not exist on this machine", fix)
    return Check("ok", "Kiro MCP server", f"starts with {command}")


def check_ui_tools() -> Check:
    try:
        v = metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return Check("skip", "UI checks", "Playwright is not installed (only needed for scripts/ui_check.py and scripts/audit_ui.py)")
    return Check("ok", "UI checks", f"Playwright {v} (scripts/ui_check.py drives Microsoft Edge)")


def run(root: Path = ROOT, compile_check: bool = True) -> list[Check]:
    checks = [check_python(), check_packages(root), check_gnucobol()]
    checks.append(check_round_trip() if compile_check else Check("skip", "Compile, run and compare", "skipped (--quick)"))
    checks += [check_workspace(root), check_app_files(root), check_address(), check_mcp(root), check_ui_tools()]
    return checks


def main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="seance doctor", description="Check that this machine can run Séance.")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--quick", action="store_true", help="skip compiling the test program")
    a = p.parse_args(argv)
    checks = run(compile_check=not a.quick)
    failed = sum(c.level == "fail" for c in checks)
    if a.json:
        print(json.dumps({"version": __version__, "ok": not failed, "checks": [asdict(c) for c in checks]}, indent=2))
        return 1 if failed else 0
    print(f"Séance {__version__} setup check")
    tag = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL", "skip": "--  "}
    for c in checks:
        print(f"  {tag[c.level]}  {c.name}: {c.detail}")
        if c.fix and c.level in ("warn", "fail"):
            print(f"        fix: {c.fix}")
    warned = sum(c.level == "warn" for c in checks)
    ok = sum(c.level == "ok" for c in checks)
    print(f"{ok} ok, {warned} warning{'s' if warned != 1 else ''}, {failed} problem{'s' if failed != 1 else ''}"
          + ("" if failed else ". Ready: python -m seance serve"))
    return 1 if failed else 0
