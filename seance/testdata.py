"""Named sets of saved test records per program: generated ones and the files you upload."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import MAX_DATA_RECORDS
from .recorder import ROOT, LegacyRuntimeError, compile_legacy, get_model, run_legacy

DEFAULT_LABELS = {
    "edges": "Edge cases (zero, smallest and largest values, plus values the code tests for)",
    "random": "Random records",
}


def _manifest_path(program: str, root: Path = ROOT) -> Path:
    return root / "fixtures" / program / "sets.json"


def labels(program: str, root: Path = ROOT) -> dict[str, str]:
    path = _manifest_path(program, root)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = sorted(p.stem for p in (root / "fixtures" / program).glob("*.in"))
    return {n: saved.get(n, DEFAULT_LABELS.get(n, n)) for n in names}


def _save_label(program: str, name: str, label: str | None, root: Path = ROOT) -> None:
    path = _manifest_path(program, root)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if label is None:
        saved.pop(name, None)
    else:
        saved[name] = label
    path.write_text(json.dumps(saved, indent=2), encoding="utf-8")


def split_records(data: str, program: str, root: Path = ROOT) -> list[str]:
    """Text lines, or fixed-length records with no line breaks (the way mainframe files are)."""
    model = get_model(program, root)
    width = model.in_layout.width
    if "\n" not in data and "\r" not in data and width and len(data) > width and len(data) % width == 0:
        return [data[i : i + width] for i in range(0, len(data), width)]
    rows = data.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    return rows


def add_set(program: str, filename: str, data: str, root: Path = ROOT) -> dict:
    """Save an uploaded input file as a test set, with the outputs the real COBOL gives for it."""
    model = get_model(program, root)
    width = model.in_layout.width
    lines = [l.rstrip("\r") for l in split_records(data, program, root)]
    if not lines:
        raise ValueError("The file has no records.")
    if len(lines) > MAX_DATA_RECORDS:
        raise ValueError(f"The file has {len(lines)} records. The limit is {MAX_DATA_RECORDS}; split it into smaller files.")
    too_long = [i + 1 for i, l in enumerate(lines) if len(l.rstrip()) > width]
    if too_long:
        raise ValueError(f"Record {too_long[0]} is longer than the {width}-character input record ({len(too_long)} records are too long).")
    try:
        out = run_legacy(compile_legacy(program, root), [l.rstrip() for l in lines], model)
    except LegacyRuntimeError as exc:
        raise ValueError(str(exc)) from exc
    if len(out) != len(lines):
        raise ValueError(f"The COBOL wrote {len(out)} records for {len(lines)} inputs, so outputs cannot be paired.")
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename or "data").stem.lower()).strip("-")[:30] or "data"
    name = f"yours-{stem}"
    folder = root / "fixtures" / program
    folder.mkdir(parents=True, exist_ok=True)
    n = 2
    while (folder / f"{name}.in").exists():
        name = f"yours-{stem}-{n}"
        n += 1
    (folder / f"{name}.in").write_text("".join(l.rstrip() + "\n" for l in lines), encoding="latin-1")
    (folder / f"{name}.out").write_text("".join(l + "\n" for l in out), encoding="latin-1")
    _save_label(program, name, f"Your data: {Path(filename).name or 'uploaded file'}", root)
    return {"set": name, "records": len(lines), "label": labels(program, root)[name]}


def remove_set(program: str, name: str, root: Path = ROOT) -> None:
    if not re.fullmatch(r"yours-[a-z0-9-]{1,40}", name):
        raise ValueError("Only test data you uploaded can be removed.")
    for ext in (".in", ".out"):
        p = root / "fixtures" / program / f"{name}{ext}"
        if p.exists():
            p.unlink()
    _save_label(program, name, None, root)


def describe_sets(program: str, root: Path = ROOT) -> list[dict]:
    out = []
    for name, label in labels(program, root).items():
        p = root / "fixtures" / program / f"{name}.in"
        count = sum(1 for _ in p.open(encoding="latin-1")) if p.exists() else 0
        out.append({"set": name, "label": label, "records": count, "removable": name.startswith("yours-")})
    return out
