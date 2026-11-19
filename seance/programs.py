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
USER_MARKER = ".user"

# A fixed-format program with DD-style file names and an FD that holds the records, the way most real programs look.
TEMPLATE = {
    "name": "discount",
    "cobol": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISCOUNT.
      * Order pricing: a percentage off the amount, rounded to cents.
      * A negative adjustment (a refund) keeps its sign.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDERS-IN  ASSIGN TO ORDERIN.
           SELECT ORDERS-OUT ASSIGN TO ORDEROUT.
       DATA DIVISION.
       FILE SECTION.
       FD  ORDERS-IN RECORDING MODE F.
       01  IN-REC.
           05  IN-ORDER-ID  PIC X(6).
           05  IN-AMOUNT    PIC S9(5)V99.
           05  IN-PCT       PIC 9(3)V99.
           05  FILLER       PIC X(4).
       FD  ORDERS-OUT RECORDING MODE F.
       01  OUT-REC.
           05  OUT-ORDER-ID  PIC X(6).
           05  OUT-DISCOUNT  PIC S9(5)V99.
           05  OUT-TOTAL     PIC S9(6)V99.
           05  OUT-SHOWN     PIC $$,$$$,$$9.99-.
       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-EOF        PIC X VALUE 'N'.
               88  AT-EOF    VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDERS-IN OUTPUT ORDERS-OUT
           PERFORM UNTIL AT-EOF
               READ ORDERS-IN
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END PERFORM PRICE-ORDER
               END-READ
           END-PERFORM
           CLOSE ORDERS-IN ORDERS-OUT
           STOP RUN.
       PRICE-ORDER.
           MOVE IN-ORDER-ID TO OUT-ORDER-ID
           COMPUTE OUT-DISCOUNT ROUNDED = IN-AMOUNT * IN-PCT / 100
           COMPUTE OUT-TOTAL = IN-AMOUNT - OUT-DISCOUNT
           MOVE OUT-TOTAL TO OUT-SHOWN
           WRITE OUT-REC.
""",
    "copybooks": [],
}


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


def is_user_program(name: str, root: Path = ROOT) -> bool:
    return (root / "legacy" / name / USER_MARKER).exists()


def implementations(name: str, root: Path = ROOT) -> list[Implementation]:
    found = []
    if (root / "migrated" / f"{name}.py").exists():
        mine = is_user_program(name, root)
        found.append(Implementation(f"migrated.{name}", "Your Python" if mine else "Reference Python", "yours" if mine else "reference", mine))
    if (root / "examples" / "naive" / f"{name}_naive.py").exists():
        found.append(Implementation(f"examples.naive.{name}_naive", "Naive Draft (Floats)", "naive", False))
    return found


def _purpose(model) -> str:
    from .cobol_src import normalize

    note = model.path.parent / "SOURCE.md"  # shipped examples describe themselves there
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
    return " ".join(block)[:240]


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

    def sha(path: Path):
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else None

    current = rc.get("python_sha256") == sha(impl_path) and rc.get("cobol_sha256") == sha(cbl)
    return {"verdict": r.get("verdict"), "matched": r.get("matched"), "checked_at": rc.get("checked_at"), "current": current}


def program_info(name: str, root: Path = ROOT) -> dict:
    """Everything the UI shows about a program, read from the program itself."""
    impls = []
    for i in implementations(name, root):
        d = dict(i.__dict__)
        d["last_check"] = last_check(i.module, root)
        impls.append(d)
    info = {"name": name, "user_added": is_user_program(name, root), "implementations": impls}
    try:
        model = load_model(name, root)
        info.update({
            "title": name.replace("_", " ").title(),
            "program_id": model.program_id,
            "format": "fixed" if model.fixed else "free",
            "purpose": _purpose(model),
            "files": [{"name": f.name, "assign": f.assign, "role": "input" if f.is_input and not f.is_output else ("output" if f.is_output and not f.is_input else "both"),
                       "lines": f.organization == "line", "record": f.record.name if f.record else None, "size": f.size} for f in model.all_files],
            "console_input": model.all_accepts,
            "io": model.describe_io(),
            "unsupported": model.unsupported,
            "notes": model.notes,
            "error": None,
        })
    except ModelError as exc:
        info.update({"title": name.replace("_", " ").title(), "error": str(exc), "files": [], "console_input": [], "unsupported": [], "notes": [], "purpose": ""})
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


def delete_program(name: str, root: Path = ROOT) -> None:
    validate_name(name)
    if not is_user_program(name, root):
        raise ProgramError("Only programs you added can be deleted.")
    for p in (
        root / "legacy" / name,
        root / "fixtures" / name,
        root / "build" / name,
        root / "migrated" / f"{name}.py",
        root / "migrated" / f"{name}.py.bak",
        root / "docs" / "specs" / f"{name}.md",
    ):
        _rm(p)


def create_program(name: str, cobol: str, copybooks: dict[str, str] | None = None, root: Path = ROOT,
                   programs: dict[str, str] | None = None) -> dict:
    """programs: other COBOL programs this one CALLs (file stem -> source), compiled and translated with it."""
    """Add a program, then analyze, compile, record, describe and draft the Python. Cleans up on failure."""
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
        (src / f"{name}.cbl").write_text(cobol, encoding="utf-8")
        for cb_name, cb_text in copybooks.items():
            (src / f"{cb_name}.cpy").write_text(cb_text, encoding="utf-8")
        for sub_name, sub_text in programs.items():
            if sub_name.lower() == name.lower():
                raise ProgramError(f"A called program cannot have the same file name as the main program ({sub_name}).")
            (src / f"{sub_name.lower()}.cbl").write_text(sub_text, encoding="utf-8")
        (src / USER_MARKER).write_text("added through the UI\n", encoding="utf-8")
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
