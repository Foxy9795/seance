"""Render a verification Report as JSON and Markdown."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .verify import Report


def to_dict(r: Report) -> dict:
    d = asdict(r)
    d["matched"] = r.matched
    d["verdict"] = "Spirit matched" if r.matched else "Spirit restless"
    return d


def _mm(m) -> str:
    return (
        f"- `{m.source}` record {m.index}, field **{m.field}**\n"
        f"  - input:    `{m.input}`\n"
        f"  - legacy:   `{m.expected}`\n"
        f"  - migrated: `{m.actual}`"
    )


def to_markdown(r: Report) -> str:
    lines = [f"# Séance report: {r.program}", "", f"Implementation: `{r.implementation}`", f"Verdict: **{to_dict(r)['verdict']}**", "", "## Recorded fixtures"]
    for name, info in r.fixtures.items():
        lines.append(f"- {name}: {info['records']} records, {info['mismatches']} mismatches")
    lines += ["", "## Property-based test", f"- {r.property_runs} generated batches compared against the legacy program"]
    if r.property_mismatch:
        lines += ["- Smallest failing input found:", _mm(r.property_mismatch)]
    else:
        lines.append("- No differences found")
    if r.mismatches:
        lines += ["", f"## Fixture mismatches ({len(r.mismatches)}, first 5 shown)"] + [_mm(m) for m in r.mismatches[:5]]
    lines += ["", "## Needs human review"]
    lines += [f"- {x}" for x in r.review] or ["- Nothing flagged"]
    return "\n".join(lines) + "\n"


def write_reports(r: Report, root: Path) -> tuple[Path, Path]:
    out = root / "build" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    tag = r.implementation.replace(".", "_")
    j, m = out / f"{tag}.json", out / f"{tag}.md"
    j.write_text(json.dumps(to_dict(r), indent=2), encoding="utf-8")
    m.write_text(to_markdown(r), encoding="utf-8")
    return j, m
