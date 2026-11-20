"""Check the repository against the Kiroween submission rules and the project's own steering rules.

    python scripts/check_rules.py            print every check
    python scripts/check_rules.py --strict   warnings also fail

FAIL means a rule is broken. WARN means something only a person can settle (a write-up still to fill in, a path
that only works on one machine). The same checks run in the test suite (tests/test_rules.py).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# floats and round() that are allowed, and why. Money never goes through them.
FLOAT_OK = {
    "seance/codec.py": "COMP-1 and COMP-2 are IEEE floats in COBOL; the conversion mirrors GnuCOBOL's own",
    "seance/coverage.py": "a percentage shown to people",
    "seance/gapfill.py": "a time limit in seconds",
}
Result = tuple[str, str, str]  # level, rule, message


def _git_ignored(path: str) -> bool | None:
    try:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True).returncode == 0
    except OSError:
        return None


def kiroween() -> list[Result]:
    out: list[Result] = []
    ok = lambda rule, msg: out.append(("PASS", rule, msg))  # noqa: E731
    bad = lambda rule, msg: out.append(("FAIL", rule, msg))  # noqa: E731
    warn = lambda rule, msg: out.append(("WARN", rule, msg))  # noqa: E731

    kiro = ROOT / ".kiro"
    ignored = _git_ignored(".kiro/steering/product.md")
    if not kiro.is_dir():
        bad("/.kiro at the repo root", "the folder is missing")
    elif ignored:
        bad("/.kiro is not ignored", "a .gitignore rule hides .kiro; the submission must include it")
    else:
        ok("/.kiro at the repo root, not ignored", "present" + ("" if ignored is not None else " (git not available to confirm it is not ignored)"))

    spec_dirs = [d for d in (kiro / "specs").glob("*") if d.is_dir()] if (kiro / "specs").is_dir() else []
    for d in spec_dirs:
        missing = [n for n in ("requirements.md", "design.md", "tasks.md") if not (d / n).is_file()]
        (bad if missing else ok)(f"spec {d.name}", f"missing {', '.join(missing)}" if missing else "requirements, design and tasks")
    if not spec_dirs:
        bad("spec-driven development", "no spec under .kiro/specs")
    steering = sorted(p.name for p in (kiro / "steering").glob("*.md")) if (kiro / "steering").is_dir() else []
    (ok if len(steering) >= 2 else bad)("steering", ", ".join(steering) or "none")
    hooks = sorted(p.name for p in (kiro / "hooks").glob("*.hook")) if (kiro / "hooks").is_dir() else []
    (ok if hooks else bad)("hooks", ", ".join(hooks) or "none")
    mcp = kiro / "settings" / "mcp.json"
    if mcp.is_file():
        text = mcp.read_text(encoding="utf-8")
        servers = list(json.loads(text).get("mcpServers", {}))
        ok("MCP server configured", ", ".join(servers))
        if re.search(r"[A-Za-z]:\\\\Users\\\\|/home/\w+/|/Users/\w+/", text):
            warn("MCP config runs on other machines", "mcp.json holds an absolute path from this machine, so a judge who clones the repo "
                 "gets a server that does not start until they run: python -m seance setup --mcp-config")
    else:
        bad("MCP server configured", ".kiro/settings/mcp.json is missing")

    lic = ROOT / "LICENSE"
    if lic.is_file() and lic.read_text(encoding="utf-8").lstrip().startswith(("MIT License", "Apache License", "BSD")):
        ok("OSI-approved license", lic.read_text(encoding="utf-8").splitlines()[0])
    else:
        bad("OSI-approved license", "LICENSE is missing or is not a recognised open source license")

    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").is_file() else ""
    (ok if re.search(r"quick start", readme, re.I) and "GnuCOBOL" in readme else bad)("install and run instructions", "README Quick Start")

    demo = ROOT / "docs" / "hackathon" / "DEMO.md"
    if demo.is_file():
        times = [int(m) * 60 + int(s) for m, s in re.findall(r"^\|\s*(\d+):(\d\d)\s*\|", demo.read_text(encoding="utf-8"), re.M)]
        (ok if times and max(times) < 180 else bad)("demo video under 3 minutes", f"the script ends at {max(times) // 60}:{max(times) % 60:02d}" if times else "no timed script")
    else:
        bad("demo video script", "docs/hackathon/DEMO.md is missing")

    write = ROOT / "docs" / "hackathon" / "KIRO_WRITEUP.md"
    if write.is_file():
        left = len(re.findall(r"\[[^\]]{8,}\?\]|\[Confirm[^\]]*\]|\[Describe[^\]]*\]|\[Which[^\]]*\]", write.read_text(encoding="utf-8")))
        (warn if left else ok)("write-up on how Kiro was used", f"{left} bracketed question(s) only you can answer" if left else "complete")
    else:
        bad("write-up on how Kiro was used", "docs/hackathon/KIRO_WRITEUP.md is missing")

    catalog = json.loads((ROOT / "samples" / "catalog.json").read_text(encoding="utf-8"))
    for s in catalog.get("samples", []):
        if s.get("group") == "course":
            src = ROOT / "samples" / s["name"] / "legacy" / "SOURCE.md"
            (ok if src.is_file() and "CC-BY" in src.read_text(encoding="utf-8") else bad)(f"third-party program {s['name']}", "attributed with its license" if src.is_file() else "no SOURCE.md")
    return out


def steering() -> list[Result]:
    out: list[Result] = []
    # Money is Decimal: no float() or round() in the engine or in generated Python
    offenders = []
    files = [p for p in (ROOT / "seance").glob("*.py")]
    files += [p for p in (ROOT / "migrated").glob("*.py") if not p.stem.endswith("_naive")]
    files += list((ROOT / "samples").glob("*/migrated.py"))
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel in FLOAT_OK:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8-sig"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("float", "round"):
                offenders.append(f"{rel}:{n.lineno} {n.func.id}()")
    out.append(("FAIL" if offenders else "PASS", "money uses Decimal, never float or round()", "; ".join(offenders[:6]) or f"{len(files)} files scanned"))

    web = sorted(p.name for p in (ROOT / "web").iterdir())
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    external = re.findall(r"""(?:src|href)=["'](https?://[^"']+)""", html)
    no_build = not any((ROOT / n).exists() for n in ("package.json", "vite.config.js", "webpack.config.js"))
    out.append(("PASS" if web == ["index.html"] and not external and no_build else "FAIL", "frontend: one static HTML file, vanilla JS, no build step",
                f"files {web}; external URLs {external or 'none'}"))
    labels = all(s in html for s in ("Spirit matched", "Spirit restless"))
    out.append(("PASS" if labels else "FAIL", 'result labels "Spirit matched" / "Spirit restless"', "in the UI" if labels else "missing from web/index.html"))
    out.append(("PASS" if (ROOT / "tests" / "test_ui_contrast.py").is_file() else "FAIL", "WCAG AA contrast is tested", "tests/test_ui_contrast.py"))

    from seance.cli import COMMANDS

    stages = {"analyze", "record", "translate", "verify"}
    out.append(("PASS" if stages <= set(COMMANDS) else "FAIL", "every pipeline stage has a CLI entry point", ", ".join(sorted(stages)) if stages <= set(COMMANDS) else f"missing {stages - set(COMMANDS)}"))

    rules = (ROOT / ".kiro" / "steering" / "product.md").read_text(encoding="utf-8")
    out.append(("PASS" if "Python 3.12" in rules and sys.version_info >= (3, 12) else "FAIL", "Python 3.12 or newer", sys.version.split()[0]))
    from seance.mcp_server import mcp

    names = sorted(t.name for t in __import__("asyncio").run(mcp.list_tools()))
    needed = {"describe_program", "run_legacy_program", "verify_migration"}
    out.append(("PASS" if needed <= set(names) else "FAIL", "MCP tools the migration rules rely on", f"{len(names)} tools; {', '.join(sorted(needed))} present" if needed <= set(names) else f"missing {needed - set(names)}"))
    return out


def run() -> list[Result]:
    return kiroween() + steering()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    a = ap.parse_args(argv)
    results = run()
    for level, rule, msg in results:
        print(f"{level:<5} {rule}\n      {msg}")
    fails = sum(r[0] == "FAIL" for r in results)
    warns = sum(r[0] == "WARN" for r in results)
    print(f"\n{len(results)} checks: {len(results) - fails - warns} pass, {warns} warn, {fails} fail")
    return 1 if fails or (a.strict and warns) else 0


if __name__ == "__main__":
    raise SystemExit(main())
