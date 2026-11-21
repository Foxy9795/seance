"""Render a verification Report as JSON and Markdown, with a receipt that ties it to exact files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .verify import Report


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None


def source_sha(program: str, root: Path) -> str | None:
    """Hash of the COBOL a check ran against: the main source plus every copybook and called program beside it.
    A program that is one file keeps the plain hash of that file."""
    base = root / "legacy" / program
    head = next((p for p in (base / f"{program}.cbl", base / f"{program}.jcl") if p.exists()), None)
    if head is None:
        return None
    others = sorted(p for p in base.iterdir() if p.is_file() and p != head and p.suffix.lower() in (".cbl", ".cob", ".cpy", ".copy", ".jcl"))
    if not others:
        return _sha(head)
    h = hashlib.sha256(head.read_bytes())
    for p in others:
        h.update(b"\0" + p.name.lower().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


def receipt(r: Report, root: Path) -> dict:
    """What was checked: hashes of the COBOL and the Python, so the verdict cannot be reused for other code."""
    impl_path = root / (r.implementation.replace(".", "/") + ".py")
    return {
        "cobol_sha256": source_sha(r.program, root),
        "python_sha256": _sha(impl_path) if not r.implementation.startswith("jobs.") else _job_python_sha(r, root),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "saved_records": sum(s["records"] for s in r.sets),
        "compared_lines": sum(s["compared"] for s in r.sets),
        "random_runs": r.random_runs,
        "evidence_sha256": _evidence(r.program, root),
    }


def _job_python_sha(r: Report, root: Path) -> str | None:
    from .jobs import python_sha

    return python_sha(r.program, root)


def _evidence(program: str, root: Path) -> str | None:
    """One hash over every saved input and expected output, so the receipt pins the exact test data."""
    base = root / "fixtures" / program
    if not base.exists():
        return None
    h = hashlib.sha256()
    for f in sorted(base.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(base).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def to_dict(r: Report, root: Path | None = None) -> dict:
    d = asdict(r)
    d["matched"] = r.matched
    d["verdict"] = "Spirit matched" if r.matched else "Spirit restless"
    if root is not None:
        d["receipt"] = receipt(r, root)
    return d


def _diff_md(d: dict) -> list[str]:
    where = "the run" if d["index"] < 0 else f"{d['stream']} line {d['index'] + 1}"
    out = [f"- {where}", f"  - COBOL:  `{d['expected']}`", f"  - Python: `{d['actual']}`"]
    bad = [f for f in d.get("fields", []) if not f["same"]]
    if bad:
        out.append("  - Fields that differ: " + ", ".join(f"{f['name']} ({f['expected']} vs {f['actual']})" for f in bad[:6]))
    return out


def to_markdown(r: Report, root: Path | None = None) -> str:
    verdict = "Spirit matched" if r.matched else "Spirit restless"
    lines = [f"# Séance report: {r.program}", "", f"Python checked: `{r.implementation}`", f"Verdict: **{verdict}**", ""]
    if root is not None:
        rc = receipt(r, root)
        lines += ["## Receipt", f"- COBOL source SHA-256: `{rc['cobol_sha256']}`", f"- Python SHA-256: `{rc['python_sha256']}`", f"- Test data SHA-256: `{rc['evidence_sha256']}`",
                  f"- Checked: {rc['checked_at']}", ""]
    lines.append("## Saved test sets")
    for s in r.sets:
        given = [f"{s['records']} input records"] if s["records"] else []
        given += [f"{s['console_lines']} console lines"] if s.get("console_lines") else []
        lines.append(f"- {s['label']}: {', '.join(given) or 'no input'}; {s['compared']} output lines compared, {s['differing']} differ")
    if r.coverage:
        c = r.coverage
        lines += ["", "## Coverage", f"- The saved runs reach {c['reached']} of {c['statements']} COBOL statements ({c['percent']}%)"]
    lines += ["", "## Random runs", f"- {r.random_runs} fresh runs of both programs on generated input"]
    if r.random_failure:
        lines.append("- Smallest failing case found:")
        for name, rows in r.random_failure["inputs"].items():
            lines.append(f"  - {name}: " + ", ".join(f"`{x}`" for x in rows[:5]) + (" ..." if len(rows) > 5 else ""))
        if r.random_failure["stdin"]:
            lines.append("  - console input: " + ", ".join(f"`{x}`" for x in r.random_failure["stdin"][:8]))
        for d in r.random_failure["diffs"][:3]:
            lines += ["  " + x for x in _diff_md(d)]
    elif r.random_runs:
        lines.append("- No differences found")
    else:
        lines.append("- Not needed: the program reads no input, so the saved run covers it")
    if r.diffs:
        total = sum(s["differing"] for s in r.sets)
        lines += ["", f"## Differences in saved sets ({total} lines differ, first {min(5, len(r.diffs))} shown)"]
        for d in r.diffs[:5]:
            lines += _diff_md(d)
    lines += ["", "## Notes"]
    lines += [f"- {x}" for x in r.review] or ["- Nothing flagged"]
    return "\n".join(lines) + "\n"


def write_reports(r: Report, root: Path) -> tuple[Path, Path]:
    out = root / "build" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    tag = r.implementation.replace(".", "_")
    j, m = out / f"{tag}.json", out / f"{tag}.md"
    body = to_dict(r, root)
    j.write_text(json.dumps(body, indent=2), encoding="utf-8")
    m.write_text(to_markdown(r, root), encoding="utf-8")
    _remember(out, tag, body)
    return j, m


HISTORY_KEEP = 200


def _remember(out: Path, tag: str, body: dict) -> None:
    """One line per check, kept in build/reports/history, so the verdicts of a program can be read back as an audit trail."""
    rc = body.get("receipt") or {}
    cov = body.get("coverage") or {}
    entry = {"at": rc.get("checked_at"), "verdict": body.get("verdict"), "matched": body.get("matched"), "compared": rc.get("compared_lines"),
             "differing": sum(s.get("differing", 0) for s in body.get("sets", [])), "random_runs": body.get("random_runs"), "coverage": cov.get("percent"),
             "random_failed": bool(body.get("random_failure")), "cobol": rc.get("cobol_sha256"), "python": rc.get("python_sha256"), "evidence": rc.get("evidence_sha256")}
    folder = out / "history"
    folder.mkdir(exist_ok=True)
    path = folder / f"{tag}.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines.append(json.dumps(entry))
    path.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n", encoding="utf-8")


def history(implementation: str, root: Path, limit: int = 30) -> list[dict]:
    path = root / "build" / "reports" / "history" / f"{implementation.replace('.', '_')}.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows[-limit:][::-1]


def junit_xml(results: list[dict], seconds: float = 0.0) -> str:
    """JUnit XML for CI systems: one test case per program. results: name, matched, summary, detail, error, seconds."""
    from xml.sax.saxutils import escape, quoteattr

    failures = sum(1 for r in results if not r.get("error") and not r["matched"])
    errors = sum(1 for r in results if r.get("error"))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuite name="seance" tests="{len(results)}" failures="{failures}" errors="{errors}" time="{seconds:.2f}">']
    for r in results:
        out.append(f'  <testcase classname="seance" name={quoteattr(r["name"])} time="{r.get("seconds", 0):.2f}">')
        if r.get("error"):
            out.append(f'    <error message={quoteattr(r["error"][:300])}>{escape(r["error"])}</error>')
        elif not r["matched"]:
            out.append(f'    <failure message={quoteattr(r["summary"])}>{escape(r.get("detail", ""))}</failure>')
        out.append("  </testcase>")
    out.append("</testsuite>")
    return "\n".join(out) + "\n"
