"""Manage the set of legacy programs: discover, add your own, scaffold, delete."""

from __future__ import annotations

import keyword
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .cases import describe_sets, record_sets
from .model import ModelError, load_model
from .recorder import ROOT, LegacyRuntimeError, compile_legacy
from .spec import write_spec

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
COPYBOOK_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_SOURCE_BYTES = 200_000
SAMPLE_MARKER = ".sample"  # in legacy/<name>/ of a program loaded from the sample library

class ProgramError(ValueError):
    """A problem the user can fix (bad name, unsupported COBOL, COBOL does not compile)."""


@dataclass
class Implementation:
    module: str
    label: str
    role: str  # "yours", "reference" or "naive"
    editable: bool


def program_names(root: Path = ROOT) -> list[str]:
    base = root / "legacy"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if NAME_RE.fullmatch(p.name) and (p / f"{p.name}.cbl").exists())


def is_sample(name: str, root: Path = ROOT) -> bool:
    """True for a program loaded from the sample library (it is the user's copy, and can be removed in one step)."""
    return (root / "legacy" / name / SAMPLE_MARKER).exists()


def implementations(name: str, root: Path = ROOT) -> list[Implementation]:
    found = []
    if (root / "migrated" / f"{name}.py").exists():
        found.append(Implementation(f"migrated.{name}", "Your Python", "yours", True))
    if is_sample(name, root) and (root / "migrated" / f"{name}_naive.py").exists():  # the sample's deliberately buggy port
        found.append(Implementation(f"migrated.{name}_naive", "Hand-Written Port (Floats)", "naive", False))
    return found


def _purpose(model) -> str:
    from .cobol_src import normalize

    note = model.path.parent / "SOURCE.md"  # programs taken from a course or a book say what they are there
    if note.exists():
        paras = [p.strip() for p in note.read_text(encoding="utf-8").split("\n\n") if p.strip() and not p.startswith("#")]
        if paras:
            return paras[-1].replace("\n", " ")[:240]
    block = []
    for line in normalize(model.path.read_text(encoding="utf-8", errors="replace"), model.fixed):
        if not line.comment and re.match(r"^\s*(ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", line.text, re.I):
            break  # the purpose is in the header comments, not in commented-out code further down
        if line.comment:
            text = re.sub(r"^[-=*>\s]+|[-=*\s]+$", "", line.text)
            if text and not text.upper().startswith(("COPYRIGHT", "SPDX", "AUTHOR")):
                block.append(text)
        elif block and not re.match(r"^\s*(IDENTIFICATION|ID|PROGRAM-ID|AUTHOR|DATE-|INSTALLATION|SECURITY|REMARKS)", line.text, re.I):
            break
    return " ".join(block)[:240] or _derived_purpose(model)


def _derived_purpose(model) -> str:
    """No header comment to quote: say what the code does, from the code. Files read and written, then what the paragraphs hold."""
    from .cobol_src import normalize

    in_proc, paragraphs, texts = False, 0, []
    counts = {"decision": 0, "calculation": 0, "loop": 0, "call": 0, "sort": 0, "sql": 0}
    patterns = {"decision": r"\b(IF|EVALUATE)\b", "calculation": r"\b(COMPUTE|ADD|SUBTRACT|MULTIPLY|DIVIDE)\b",
                "loop": r"\bPERFORM\b[^.]{0,120}?\b(UNTIL|VARYING|TIMES)\b", "call": r"\bCALL\b", "sort": r"\b(SORT|MERGE)\b", "sql": r"\bEXEC\s+(SQL|CICS)\b"}
    for line in normalize(model.path.read_text(encoding="utf-8", errors="replace"), model.fixed):
        if line.comment:
            continue
        text = line.text.strip()
        if re.match(r"PROCEDURE\s+DIVISION", text, re.I):
            in_proc = True
            continue
        if not in_proc:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*\.", text) and not re.match(r"(STOP|GOBACK|EXIT|CONTINUE)\b", text, re.I):
            paragraphs += 1
        texts.append(text)
    whole = " ".join(texts)  # a PERFORM and its UNTIL are often on two lines
    for kind, rx in patterns.items():
        counts[kind] = len(re.findall(rx, whole, re.I))
    io = model.describe_io()
    head = (io[:1].upper() + io[1:] + ".") if io else "Runs without reading or writing a file."
    names = {"decision": "decision", "calculation": "calculation", "loop": "loop", "call": "CALL", "sort": "sort or merge", "sql": "SQL or CICS statement"}
    parts = [f"{n} {names[k]}{'' if n == 1 else 's'}" for k, n in counts.items() if n]
    body = f"{paragraphs} paragraph{'' if paragraphs == 1 else 's'}" if paragraphs else ""
    detail = ", ".join(x for x in [body, *parts] if x)
    return f"{head} {detail[:1].upper() + detail[1:]}." if detail else head


def last_check(implementation: str, root: Path = ROOT) -> dict | None:
    """The saved result of the last check of this Python, and whether the files changed since."""
    import hashlib
    import json

    p = root / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
    if not p.exists():
        return None
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
    rc = r.get("receipt") or {}
    program = r.get("program", "")
    impl_path = root / (implementation.replace(".", "/") + ".py")
    cbl = root / "legacy" / program / f"{program}.cbl"

    from .report import source_sha

    def sha(path: Path):
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None

    if implementation.startswith("jobs."):
        from .jobs import python_sha

        current = rc.get("python_sha256") == python_sha(program, root) and rc.get("cobol_sha256") == source_sha(program, root)
    else:
        current = rc.get("python_sha256") == sha(impl_path) and rc.get("cobol_sha256") == source_sha(program, root)
    cov = r.get("coverage") or {}
    return {"verdict": r.get("verdict"), "matched": r.get("matched"), "checked_at": rc.get("checked_at"), "current": current,
            "compared": rc.get("compared_lines"), "random_runs": rc.get("random_runs"), "coverage": cov.get("percent"),
            "differing": sum(s.get("differing", 0) for s in r.get("sets", []))}


def kinds_of(model) -> list[str]:
    """What kind of program this is, for badges and filters: sql, cics, indexed, relative, sort, calls, console."""
    orgs = {f.organization for f in model.all_files}
    kinds = []
    if "sqldb" in orgs or model.sql_tables:
        kinds.append("sql")
    if "cicsdb" in orgs or model.cics:
        kinds.append("cics")
    if "indexed" in orgs:
        kinds.append("indexed")
    if "relative" in orgs:
        kinds.append("relative")
    if "sort" in orgs:
        kinds.append("sort")
    if model._every()[1:]:
        kinds.append("calls")
    if model.all_accepts:
        kinds.append("console")
    return kinds


def program_info(name: str, root: Path = ROOT) -> dict:
    """Everything the UI shows about a program, read from the program itself."""
    impls = []
    for i in implementations(name, root):
        d = dict(i.__dict__)
        d["last_check"] = last_check(i.module, root)
        impls.append(d)
    info = {"name": name, "sample": is_sample(name, root), "implementations": impls, "kind": "program"}
    try:
        model = load_model(name, root)
        info.update({
            "title": model.program_id.upper() if model.program_id and model.program_id.lower().replace("-", "_") == name else name.replace("_", " ").title(),
            "program_id": model.program_id,
            "format": "fixed" if model.fixed else "free",
            "purpose": _purpose(model),
            "files": [{"name": f.name, "assign": f.assign, "role": "input" if f.is_input and not f.is_output else ("output" if f.is_output and not f.is_input else "both"),
                       "lines": f.organization == "line", "record": f.record.name if f.record else None, "size": f.size} for f in model.all_files],
            "console_input": model.all_accepts,
            "calls": [m.program_id for m in model._every()[1:]],
            "io": model.describe_io(),
            "unsupported": model.unsupported,
            "copybooks": sorted(f.name for f in (root / "legacy" / name).iterdir() if f.suffix.lower() in (".cpy", ".copy", ".cpb")),
            "notes": model.notes,
            "kinds": kinds_of(model),
            "error": None,
        })
    except ModelError as exc:
        info.update({"title": name.replace("_", " ").title(), "error": str(exc), "files": [], "console_input": [], "unsupported": [], "notes": [], "purpose": "",
                     "kinds": []})
    try:
        info["sets"] = describe_sets(name, root)
    except Exception:
        info["sets"] = []
    draft = root / "migrated" / f"{name}.py"
    info["draft"] = None
    if draft.exists():
        text = draft.read_text(encoding="utf-8-sig")
        translated = "Written by the Séance translator" in text
        info["draft"] = {"translated": translated, "gaps": len(re.findall(r"S\.unsupported\(", text))}
    return info


def suggest_name(cobol: str) -> str:
    """A program name from PROGRAM-ID: PAYROLL01 -> payroll01, ACCT-UPDATE -> acct_update."""
    m = re.search(r"PROGRAM-ID\.?\s+['\"]?([A-Za-z0-9-]+)", cobol, re.I)
    base = (m.group(1) if m else "program").lower().replace("-", "_")
    base = re.sub(r"[^a-z0-9_]", "", base)
    if not base or not base[0].isalpha():
        base = "p_" + base
    return base[:24]


def validate_name(name: str) -> None:
    if not NAME_RE.fullmatch(name) or keyword.iskeyword(name):
        raise ProgramError("Name must be 2-24 characters: lowercase letters, digits, underscores, starting with a letter, and not a Python keyword.")


def _stub(name: str, model) -> str:
    files = "\n".join(f"    {f.assign}: {'reads' if f.is_input else 'writes'} {f.record.name if f.record else ''} ({f.size} bytes)" for f in model.all_files)
    return f'''"""Migration of legacy/{name}/{name}.cbl. Read docs/specs/{name}.md first.

Files:
{files or "    (none)"}
"""

from decimal import Decimal

from seance.cobol_num import store  # mirror COBOL PIC storage: store(value, digits, scale, signed, rounded)
from seance.rt import IO


def main(io: IO) -> IO:
    """Do what the COBOL does: read io.lines(...) or io.records(...), write io.write_lines(...), io.print(...)."""
    raise NotImplementedError("Write the migration here, then run the check.")
'''


def scaffold(name: str, root: Path = ROOT, overwrite: bool = False) -> Path:
    target = root / "migrated" / f"{name}.py"
    if target.exists() and not overwrite:
        return target
    model = load_model(name, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").touch()
    target.write_text(_stub(name, model), encoding="utf-8")
    return target


def _rm(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def clear_reports(name: str, root: Path = ROOT) -> None:
    """Remove the saved check reports of a program (its Python, its hand-written port, or a job of that name)."""
    for stem in (f"migrated_{name}", f"migrated_{name}_naive", f"jobs_{name}"):
        _rm(root / "build" / "reports" / "history" / f"{stem}.jsonl")
        for ext in (".json", ".md"):
            _rm(root / "build" / "reports" / f"{stem}{ext}")


def delete_program(name: str, root: Path = ROOT, keep_build: bool = False) -> None:
    validate_name(name)
    if not (root / "legacy" / name).is_dir():
        raise ProgramError(f"There is no program named '{name}'.")
    for p in (
        root / "legacy" / name,
        root / "fixtures" / name,
        *([] if keep_build else [root / "build" / name]),
        root / "migrated" / f"{name}.py",
        root / "migrated" / f"{name}.py.bak",
        root / "migrated" / f"{name}_naive.py",
        root / "docs" / "specs" / f"{name}.md",
    ):
        _rm(p)
    clear_reports(name, root)


def _lf(text: str) -> str:
    """Text as lines ended by one newline: write_text turns each newline into CR LF on Windows, so a CR LF that came in would end up CR CR LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def create_program(name: str, cobol: str, copybooks: dict[str, str] | None = None, root: Path = ROOT,
                   programs: dict[str, str] | None = None) -> dict:
    """Add a program, then analyze, compile, record, describe and draft the Python. Cleans up on failure.

    programs: other COBOL programs this one CALLs (file stem -> source), compiled and translated with it."""
    copybooks = copybooks or {}
    programs = programs or {}
    name = (name or "").strip() or suggest_name(cobol)
    if not (name or "").strip():
        name = suggest_name(cobol)
    validate_name(name)
    if not cobol.strip():
        raise ProgramError("The COBOL source is empty.")
    total = len(cobol.encode("utf-8")) + sum(len(t.encode("utf-8")) for t in [*copybooks.values(), *programs.values()])
    if total > MAX_SOURCE_BYTES:
        raise ProgramError(f"The source is larger than {MAX_SOURCE_BYTES // 1000} KB.")
    for cb_name in [*copybooks, *programs]:
        if not COPYBOOK_RE.fullmatch(cb_name):
            raise ProgramError(f"Copybook name {cb_name!r} must be letters, digits, '-' or '_'.")
    if name in program_names(root) or (root / "legacy" / name).exists():
        raise ProgramError(f"A program named '{name}' already exists. Pick another name or delete it first.")
    if (root / "migrated" / f"{name}.py").exists():
        raise ProgramError(f"migrated/{name}.py already exists. Pick another name.")

    src = root / "legacy" / name
    created = [src, root / "fixtures" / name, root / "build" / name, root / "migrated" / f"{name}.py", root / "docs" / "specs" / f"{name}.md"]
    try:
        src.mkdir(parents=True)
        (src / f"{name}.cbl").write_text(_lf(cobol), encoding="utf-8")
        for cb_name, cb_text in copybooks.items():
            (src / f"{cb_name}.cpy").write_text(_lf(cb_text), encoding="utf-8")
        for sub_name, sub_text in programs.items():
            if sub_name.lower() == name.lower():
                raise ProgramError(f"A called program cannot have the same file name as the main program ({sub_name}).")
            (src / f"{sub_name.lower()}.cbl").write_text(_lf(sub_text), encoding="utf-8")
        try:
            model = load_model(name, root)
        except ModelError as exc:
            raise ProgramError(f"Séance cannot use this program yet:\n{exc}") from exc
        try:
            compile_legacy(name, root)
        except LegacyRuntimeError as exc:
            if model.unsupported:
                raise ProgramError(f"This program uses {', '.join(model.unsupported)}, which Séance cannot run yet.\n"
                                   f"GnuCOBOL said: {exc}") from exc
            raise ProgramError(f"The COBOL did not compile:\n{exc}") from exc
        try:
            counts = record_sets(name, root)
        except LegacyRuntimeError as exc:
            raise ProgramError(f"The COBOL compiled but could not be run on generated inputs:\n{exc}") from exc
        try:
            spec_path = write_spec(name, root)
        except Exception:  # the description is a convenience; do not lose the program over it
            spec_path = None
        draft = draft_python(name, root, overwrite=True)
        stub = root / "migrated" / f"{name}.py"
    except Exception:
        for p in created:
            _rm(p)
        raise
    return {
        "name": name,
        "format": "fixed" if model.fixed else "free",
        "io": model.describe_io(),
        "sets": counts,
        "unsupported": model.unsupported,
        "notes": model.notes,
        "spec": spec_path.relative_to(root).as_posix() if spec_path else None,
        "migration_stub": stub.relative_to(root).as_posix(),
        "draft": draft,
    }


def draft_python(name: str, root: Path = ROOT, overwrite: bool = False) -> dict:
    """Write migrated/<name>.py with the translator; fall back to an empty starter if it cannot translate."""
    from .translate import Unsupported, write_draft

    target = root / "migrated" / f"{name}.py"
    if target.exists() and overwrite:
        backup = target.with_suffix(".py.bak")
        backup.write_text(target.read_text(encoding="utf-8-sig"), encoding="utf-8")
    try:
        _, tr = write_draft(name, root, overwrite=True)
        return {"translated": True, "statements": tr.statements, "gaps": tr.unsupported}
    except (Unsupported, ModelError) as exc:
        scaffold(name, root, overwrite=True)
        return {"translated": False, "statements": 0, "gaps": [], "reason": str(exc)}
