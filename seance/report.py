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


def receipt(r: Report, root: Path) -> dict:
    """What was checked: hashes of the COBOL and the Python, so the verdict cannot be reused for other code."""
    impl_path = root / (r.implementation.replace(".", "/") + ".py")
    return {
        "cobol_sha256": _sha(root / "legacy" / r.program / f"{r.program}.cbl") or _sha(root / "legacy" / r.program / f"{r.program}.jcl"),
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
    lines += ["", "## Needs human review"]
    lines += [f"- {x}" for x in r.review] or ["- Nothing flagged"]
    return "\n".join(lines) + "\n"


def write_reports(r: Report, root: Path) -> tuple[Path, Path]:
    out = root / "build" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    tag = r.implementation.replace(".", "_")
    j, m = out / f"{tag}.json", out / f"{tag}.md"
    j.write_text(json.dumps(to_dict(r, root), indent=2), encoding="utf-8")
    m.write_text(to_markdown(r, root), encoding="utf-8")
    return j, m
