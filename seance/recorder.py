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
    if not shutil.which("cobc") and GNUCOBOL.exists():
        env["PATH"] = f"{GNUCOBOL / 'bin'}{os.pathsep}{env['PATH']}"
        env["COB_CONFIG_DIR"] = str(GNUCOBOL / "share" / "gnucobol" / "config")
        env["COB_COPY_DIR"] = str(GNUCOBOL / "share" / "gnucobol" / "copy")
        env["COB_LIBRARY_PATH"] = str(GNUCOBOL / "bin")
    return env


def cobc_path() -> str | None:
    """Absolute path to cobc. Windows looks up bare names on the parent PATH, so resolve it ourselves."""
    return shutil.which("cobc", path=cobol_env()["PATH"])


def cobc_available() -> bool:
    return cobc_path() is not None


@lru_cache(maxsize=64)
def _model_cached(program: str, root: str, stamp: float) -> ProgramModel:
    return load_model(program, Path(root))


def get_model(program: str, root: Path = ROOT) -> ProgramModel:
    """Load the program model, re-reading it when any source file changed."""
    src = root / "legacy" / program
    stamp = max((p.stat().st_mtime for p in src.glob("*") if p.is_file()), default=0.0)
    try:
        return _model_cached(program, str(root), stamp)
    except ModelError as exc:
        raise LegacyRuntimeError(str(exc)) from exc


def compile_legacy(program: str, root: Path = ROOT) -> Path:
    model = get_model(program, root)
    src_dir = root / "legacy" / program
    exe = root / "build" / program / f"{program}{'.exe' if os.name == 'nt' else ''}"
    exe.parent.mkdir(parents=True, exist_ok=True)
    newest = max(p.stat().st_mtime for p in src_dir.glob("*") if p.is_file())
    if exe.exists() and exe.stat().st_mtime >= newest:
        return exe
    if not cobc_available():
        raise LegacyRuntimeError("cobc not found. Put GnuCOBOL in tools\\gnucobol or on PATH.")
    # Compile a copy with the reported dialect fixes (the original is never changed; line numbers stay the same).
    fixed_text, _ = source_fixes(model.path.read_text(encoding="utf-8", errors="replace"), model.fixed)
    prepared = exe.parent / "src" / model.path.name
    prepared.parent.mkdir(parents=True, exist_ok=True)
    prepared.write_text(fixed_text, encoding="utf-8")
    proc = subprocess.run(
        [cobc_path(), "-x", *model.compile_flags, "-I", str(src_dir), "-o", str(exe), str(prepared)],
        capture_output=True,
        text=True,
        env=cobol_env(),
    )
    if proc.returncode != 0:
        msgs = [l for l in proc.stderr.splitlines() if "error" in l.lower()][:6]
        raise LegacyRuntimeError("cobc could not compile it:\n" + "\n".join(m.split(": ", 1)[-1] if ": " in m else m for m in msgs or proc.stderr.splitlines()[:6]))
    return exe
