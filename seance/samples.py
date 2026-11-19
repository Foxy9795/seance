"""The sample library: programs that ship with Séance so the guide can show a real check.

They are not part of the workspace. Loading one copies it in as an ordinary program (COBOL, saved test data and
Python) marked with legacy/<name>/.sample, so it can be edited, checked and deleted like your own, and all samples
can be removed in one step.

    samples/catalog.json              what the guide offers
    samples/<name>/legacy/            the COBOL (or the JCL of a job), its copybooks and called programs
    samples/<name>/fixtures/          recorded runs of the real COBOL
    samples/<name>/migrated.py        the Python that matches it
    samples/<name>/naive.py           (some) a plausible hand-written port with a bug the check catches
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .programs import SAMPLE_MARKER, ProgramError, clear_reports, delete_program, is_sample, program_names
from .recorder import ROOT

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _load() -> dict:
    return json.loads((SAMPLES / "catalog.json").read_text(encoding="utf-8"))


def catalog(root: Path = ROOT) -> dict:
    """The groups and samples the guide shows, each with whether it is already in the workspace."""
    data = _load()
    have = set(program_names(root)) | _job_names(root)
    for s in data["samples"]:
        s["loaded"] = s["name"] in have
        s.setdefault("requires", [])
        s.setdefault("recommended", False)
        s.setdefault("bug_demo", False)
    return data


def _job_names(root: Path) -> set[str]:
    from .jobs import job_names

    return set(job_names(root))


def sample_names() -> list[str]:
    return [s["name"] for s in _load()["samples"]]


def installed(root: Path = ROOT) -> list[str]:
    """Workspace programs (and jobs) that came from the sample library."""
    base = root / "legacy"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / SAMPLE_MARKER).exists())


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, copy_function=shutil.copy2)  # copy2 keeps file times, so compiled programs stay valid


def install(name: str, root: Path = ROOT) -> dict:
    """Load a sample and anything it needs (a job needs the programs it runs). Returns what was added."""
    entries = {s["name"]: s for s in _load()["samples"]}
    if name not in entries:
        raise ProgramError(f"There is no sample named '{name}'.")
    order: list[str] = []

    def visit(n: str) -> None:
        for dep in entries[n].get("requires", []):
            visit(dep)
        if n not in order:
            order.append(n)

    visit(name)
    added, already = [], []
    for n in order:
        target = root / "legacy" / n
        if target.exists():
            if is_sample(n, root):
                already.append(n)
                continue
            raise ProgramError(f"Your workspace already has a program named '{n}', so the sample of that name was not loaded. "
                               f"Rename or delete yours first.")
        src = SAMPLES / n
        clear_reports(n, root)  # a report left by an earlier copy is not this copy's verdict
        try:
            _copy_tree(src / "legacy", target)
            (target / SAMPLE_MARKER).write_text("loaded from the sample library\n", encoding="utf-8")
            if (src / "fixtures").is_dir():
                _copy_tree(src / "fixtures", root / "fixtures" / n)
            (root / "migrated").mkdir(exist_ok=True)
            (root / "migrated" / "__init__.py").touch()
            for source, dest in (("migrated.py", f"{n}.py"), ("naive.py", f"{n}_naive.py")):
                if (src / source).exists():
                    shutil.copy2(src / source, root / "migrated" / dest)
            if (src / "migrated.py").exists():
                from .spec import write_spec

                try:
                    write_spec(n, root)  # the description is a convenience; the sample works without it
                except Exception:
                    pass
        except Exception:
            delete_program(n, root, keep_build=True)
            raise
        added.append(n)
    return {"name": name, "added": added, "already": already}


def remove_all(root: Path = ROOT, keep_build: bool = False) -> list[str]:
    """Delete every program that came from the sample library."""
    gone = installed(root)
    for n in gone:
        delete_program(n, root, keep_build=keep_build)
    return gone
