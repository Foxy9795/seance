"""Find GnuCOBOL and compile legacy programs. Running them on test cases is in seance.cases."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .cobol_src import source_fixes
from .model import ModelError, ProgramModel, load_model

ROOT = Path(__file__).resolve().parent.parent
GNUCOBOL = ROOT / "tools" / "gnucobol" / "gnucobol-3.1.2-windows-mingw-x64"


class LegacyRuntimeError(RuntimeError):
    pass


def cobol_env() -> dict[str, str]:
    env = dict(os.environ)
    if GNUCOBOL.exists():
        # the bundled GnuCOBOL first, and no repeated entries: cmd.exe cannot search a PATH longer than 8191 characters
        bin_dir = str(GNUCOBOL / "bin")
        seen, parts = set(), [bin_dir]
        for p in env.get("PATH", "").split(os.pathsep):
            if p and p.lower() not in seen and p.lower() != bin_dir.lower():
                seen.add(p.lower())
                parts.append(p)
        env["PATH"] = os.pathsep.join(parts)
        env["COB_CONFIG_DIR"] = str(GNUCOBOL / "share" / "gnucobol" / "config")
        env["COB_COPY_DIR"] = str(GNUCOBOL / "share" / "gnucobol" / "copy")
        env.setdefault("COB_LIBRARY_PATH", str(GNUCOBOL / "bin"))
    return env


def cobc_path() -> str | None:
    """Absolute path to cobc. Windows looks up bare names on the parent PATH, so resolve it ourselves."""
    return shutil.which("cobc", path=cobol_env()["PATH"])


def cobc_available() -> bool:
    return cobc_path() is not None


@lru_cache(maxsize=64)
def _model_cached(program: str, root: str, stamp: float) -> ProgramModel:
    return load_model(program, Path(root))


_PRECOMPILERS = [Path(__file__).with_name(n) for n in ("sqlpre.py", "cicspre.py", "cicsbridge.py")]


def _newest(src: Path) -> float:
    """The newest change to a program's sources or to the precompilers that rewrite them."""
    files = [p for p in src.glob("*") if p.is_file()] + [p for p in _PRECOMPILERS if p.exists()]
    return max((p.stat().st_mtime for p in files), default=0.0)


def get_model(program: str, root: Path = ROOT) -> ProgramModel:
    """Load the program model, re-reading it when any source file (or a precompiler) changed."""
    src = root / "legacy" / program
    stamp = _newest(src)
    try:
        return _model_cached(program, str(root), stamp)
    except ModelError as exc:
        raise LegacyRuntimeError(str(exc)) from exc


def _cobc(args: list[str], what: str) -> None:
    proc = subprocess.run([cobc_path(), *args], capture_output=True, text=True, env=cobol_env())
    if proc.returncode != 0:
        msgs = [l for l in proc.stderr.splitlines() if "error" in l.lower()][:6]
        raise LegacyRuntimeError(f"cobc could not compile {what}:\n"
                                 + "\n".join(m.split(": ", 1)[-1] if ": " in m else m for m in msgs or proc.stderr.splitlines()[:6]))


def _prepare(model: ProgramModel, out_dir: Path) -> Path:
    """A copy with the reported dialect fixes (the original is never changed; line numbers stay the same)."""
    fixed_text, _ = source_fixes((model.compile_source or model.source or model.path).read_text(encoding="utf-8", errors="replace"), model.fixed)
    prepared = out_dir / "src" / model.path.name
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_text(fixed_text, encoding="utf-8")
    return prepared


def compile_legacy(program: str, root: Path = ROOT) -> Path:
    """Compile the program, and every program it CALLs as a module next to it (found through COB_LIBRARY_PATH)."""
    model = get_model(program, root)
    src_dir = root / "legacy" / program
    exe = root / "build" / program / f"{program}{'.exe' if os.name == 'nt' else ''}"
    exe.parent.mkdir(parents=True, exist_ok=True)
    newest = _newest(src_dir)
    subs = [m for m in model._every()[1:] if not m.in_main]  # programs of the same file are inside the executable already
    module_ext = ".dll" if os.name == "nt" else ".so"
    modules = [exe.parent / f"{m.program_id}{module_ext}" for m in subs]
    if all(t.exists() and t.stat().st_mtime >= newest for t in [exe, *modules]):
        return exe
    if not cobc_available():
        raise LegacyRuntimeError("cobc not found. Put GnuCOBOL in tools\\gnucobol or on PATH.")
    includes = ["-I", str(src_dir)]
    if any(f.organization == "sqldb" for f in model.files):
        includes = ["-I", str(exe.parent / "sqlsrc")] + includes
        _sql_bridges(exe.parent)
    if model.cics:
        includes = ["-I", str(exe.parent / "cicssrc")] + includes
        _sql_bridges(exe.parent, ("cicsbridge",))
    for m, target in zip(subs, modules):
        _cobc(["-m", *m.compile_flags, *includes, "-o", str(target), str(_prepare(m, exe.parent))], f"{m.path.name}")
    _cobc(["-x", *model.compile_flags, *includes, "-o", str(exe), str(_prepare(model, exe.parent))], "it")
    return exe


def _sql_bridges(out_dir: Path, names=("sqlbridge", "dsntiar")) -> None:
    """Build SQLBRIDGE and DSNTIAR (C, on the SQLite library Python itself uses) next to the program."""
    import sys

    native = Path(__file__).resolve().parent / "native"
    dll = Path(sys.base_prefix) / "DLLs" / "sqlite3.dll"
    if not dll.exists():
        raise LegacyRuntimeError("sqlite3.dll was not found next to Python, so embedded SQL cannot run.")
    local = out_dir / "sqlite3.dll"
    if not local.exists():
        shutil.copy(dll, local)
    for name in names:
        target = out_dir / f"{name.upper()}{'.dll' if os.name == 'nt' else '.so'}"
        src = native / f"{name}.c"
        if target.exists() and target.stat().st_mtime >= src.stat().st_mtime:
            continue
        extra = ["-L", str(out_dir), "-lsqlite3"] if name in ("sqlbridge", "cicsbridge") else []
        _cobc(["-m", "-o", str(target), str(src), *extra], f"the {name} bridge")
