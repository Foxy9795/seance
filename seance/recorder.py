"""Compile and run the original COBOL program to record what it really does."""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from .cobol_num import format_alpha, format_edited, format_numeric, edited_digits
from .copybook import Field, Layout
from .model import IOFile, ModelError, ProgramModel, load_model

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
        raise LegacyRuntimeError("cobc not found. Run tools setup or put GnuCOBOL on PATH.")
    proc = subprocess.run(
        [cobc_path(), "-x", *model.compile_flags, "-I", str(src_dir), "-o", str(exe), str(model.path)],
        capture_output=True,
        text=True,
        env=cobol_env(),
    )
    if proc.returncode != 0:
        raise LegacyRuntimeError(f"cobc failed:\n{proc.stderr.strip()}")
    return exe


# ---- running ---------------------------------------------------------------------------

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _bind(f: IOFile, work: Path, env: dict[str, str]) -> Path:
    """Make the program find our file. DD-style names go through DD_<name>, plain file names sit in the work dir."""
    if not _SAFE_NAME.match(f.assign) or f.assign.startswith("."):
        raise LegacyRuntimeError(f"Unsupported file name {f.assign!r} in ASSIGN. Use a plain name such as INPUT.DAT or ACCTREC.")
    path = work / f.assign
    if re.fullmatch(r"[A-Za-z0-9_]+", f.assign):
        env[f"DD_{f.assign}"] = str(path)
        env[f"dd_{f.assign}"] = str(path)
    return path


def run_legacy(exe: Path, input_lines: list[str], model: ProgramModel | None = None, timeout: int = 60) -> list[str]:
    """Run the compiled program on records given as text lines; return the output records as text lines."""
    model = model or get_model(exe.parent.name)
    in_w, out_w = model.in_layout.width, model.out_layout.width
    with tempfile.TemporaryDirectory(prefix="seance_") as tmp:
        work = Path(tmp)
        env = cobol_env()
        in_path, out_path = _bind(model.input, work, env), _bind(model.output, work, env)
        if model.input.organization == "line":
            payload = "".join(l.rstrip() + "\n" for l in input_lines)
        else:
            payload = "".join(l.ljust(in_w)[:in_w] for l in input_lines)
        in_path.write_bytes(payload.encode("latin-1", errors="replace"))
        proc = subprocess.run([str(exe)], cwd=work, capture_output=True, text=True, env=env, timeout=timeout)
        if proc.returncode != 0:
            raise LegacyRuntimeError(f"legacy program exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:400]}")
        if not out_path.exists():
            raise LegacyRuntimeError(f"legacy program did not write its output file {model.output.assign}")
        data = out_path.read_bytes().decode("latin-1")
        if model.output.organization == "line":
            rows = data.split("\n")
            if rows and rows[-1] == "":
                rows.pop()  # the newline after the last record
            return [r.rstrip("\r").rstrip() for r in rows]
        if out_w and len(data) % out_w:
            raise LegacyRuntimeError(f"output file length {len(data)} is not a multiple of the record width {out_w}")
        return [data[i : i + out_w].rstrip() for i in range(0, len(data), out_w)]


# ---- input generation from the record layout ----------------------------------------

def _numeric_view(f: Field) -> tuple[int, int, bool]:
    """(digits, scale, signed) for numeric and edited fields."""
    if f.kind == "edited":
        ints, decs = edited_digits(f.pic)
        from .cobol_num import edited_has_sign

        return ints + decs, decs, edited_has_sign(f.pic)
    return f.digits, f.scale, f.signed


def _format_record(layout: Layout, values: dict[str, object]) -> str:
    parts = []
    for f in layout.fields:
        v = values[f.py_name]
        if f.kind == "alpha":
            parts.append(format_alpha(str(v), f.width))
        elif f.kind == "edited":
            parts.append(format_edited(Decimal(v), f.pic).ljust(f.width)[: f.width])
        else:
            parts.append(format_numeric(Decimal(v), f.digits, f.scale, f.signed, f.sign))
    return "".join(parts).rstrip()


def numeric_edges(f: Field) -> list[Decimal]:
    digits, scale, signed = _numeric_view(f)
    unit = Decimal(1).scaleb(-scale)
    top = Decimal(10**digits - 1).scaleb(-scale)
    values = [Decimal(0), unit, top, top - unit, Decimal(10) ** (digits - scale - 1) if digits > scale else unit]
    if signed:
        values += [-unit, -top]
    return sorted(set(values)) + ([Decimal("-0").scaleb(-scale)] if signed else [])  # negative zero: its own edge case


def edge_inputs(layout: Layout) -> list[str]:
    """Boundary records: vary one field at a time over its edge values.

    Two bases are used: all zeros, and the smallest non-zero value for every
    field, so each edge is also exercised inside an otherwise realistic record.
    """
    def base(unit: bool) -> dict[str, object]:
        out: dict[str, object] = {}
        for f in layout.fields:
            if f.kind == "alpha":
                out[f.py_name] = "A" * min(f.width, 4)
            else:
                _, scale, _ = _numeric_view(f)
                out[f.py_name] = Decimal(1).scaleb(-scale) if unit else Decimal(0)
        return out

    records = []
    for unit in (False, True):
        records.append(base(unit))
        for f in layout.fields:
            if f.kind == "alpha":
                continue
            for v in numeric_edges(f):
                rec = base(unit)
                rec[f.py_name] = v
                records.append(rec)
    records.append({f.py_name: ("Z" * f.width if f.kind == "alpha" else numeric_edges(f)[-1]) for f in layout.fields})
    return _dedupe([_format_record(layout, r) for r in records])


def _dedupe(lines: list[str]) -> list[str]:
    seen, out = set(), []
    for l in lines:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


def random_inputs(layout: Layout, count: int = 300, seed: int = 1031) -> list[str]:
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        values: dict[str, object] = {}
        for f in layout.fields:
            if f.kind == "alpha":
                values[f.py_name] = f"{rng.choice('ABCDEFGHJK')}{i:04d}"[: f.width]
            else:
                digits, scale, signed = _numeric_view(f)
                use = rng.choice([2, 3, 4, digits]) if rng.random() < 0.8 else digits
                use = min(use, digits)
                raw = rng.randrange(0, 10**use)
                if signed and rng.random() < 0.3:
                    raw = -raw
                values[f.py_name] = Decimal(raw).scaleb(-scale)
        lines.append(_format_record(layout, values))
    return lines


def record_fixtures(program: str, root: Path = ROOT) -> dict[str, int]:
    """Generate inputs, run the legacy program, store (input, output) fixtures."""
    model = get_model(program, root)
    exe = compile_legacy(program, root)
    fx_dir = root / "fixtures" / program
    fx_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, lines in (("edges", edge_inputs(model.in_layout)), ("random", random_inputs(model.in_layout))):
        out = run_legacy(exe, lines, model)
        if len(out) != len(lines):
            raise LegacyRuntimeError(
                f"The program wrote {len(out)} output records for {len(lines)} input records. "
                "Séance needs one output record per input record. Programs with headers, totals or filtered records are not supported yet."
            )
        (fx_dir / f"{name}.in").write_text("".join(l + "\n" for l in lines), encoding="latin-1")
        (fx_dir / f"{name}.out").write_text("".join(l + "\n" for l in out), encoding="latin-1")
        counts[name] = len(lines)
    return counts
