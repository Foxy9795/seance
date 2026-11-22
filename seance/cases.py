"""Test cases for whole-program runs: generating them, running the COBOL and the Python on them, comparing.

A case is everything one run of the program consumes: the bytes of each input file and the lines typed at
the console. A result is everything it produces: each output file, everything DISPLAYed, the return code.
Cases are saved per test set under fixtures/<program>/<set>/ together with the COBOL's result.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .codec import ENC, decode, encode, store_into
from .layout import Item, Leaf, leaves
from .model import ROOT, FileDef, ProgramModel

FIXED_CLOCK = "2026/10/31 23:59:58.00"  # COB_CURRENT_DATE: the COBOL and the Python see the same date and time
CONSOLE = "console"


@dataclass
class Case:
    files: dict[str, bytes] = field(default_factory=dict)  # input file (ASSIGN name) -> bytes
    stdin: list[str] = field(default_factory=list)
    records: dict[str, list[bytes]] = field(default_factory=dict)  # the same input, as records (for shrinking)


@dataclass
class Result:
    outputs: dict[str, bytes] = field(default_factory=dict)
    stdout: str = ""
    return_code: int = 0
    error: str | None = None


@dataclass
class Diff:
    stream: str  # output file name, or "console"
    index: int  # record or line number, 0-based; -1 for the run as a whole
    expected: str
    actual: str
    fields: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"stream": self.stream, "index": self.index, "expected": self.expected, "actual": self.actual, "fields": self.fields}


def spec_of(it: Item) -> tuple:
    return (it.kind, it.usage, it.digits, it.scale, it.signed, it.sign, it.pic, it.size, it.justified, it.blank_zero)


# ---------------------------------------------------------------- running

def run_cobol(exe: Path, model: ProgramModel, case: Case, timeout: int = 60) -> Result:
    import os

    from . import keyed
    from .recorder import LegacyRuntimeError, cobc_path, cobol_env

    with tempfile.TemporaryDirectory(prefix="seance_") as tmp:
        work = Path(tmp)
        env = cobol_env()
        env["COB_CURRENT_DATE"] = FIXED_CLOCK
        env["TZ"] = "UTC0"
        # called programs are compiled as modules next to the main program
        env["COB_LIBRARY_PATH"] = os.pathsep.join(x for x in (str(exe.parent), env.get("COB_LIBRARY_PATH", "")) if x)
        paths, tools = {}, {}
        for f in model.all_files:
            target = work / f.assign
            paths[f.assign] = target
            if not f.literal:
                for n in {f.assign, f.raw_assign or f.assign}:
                    env[f"DD_{n}"] = str(target)
                    env[f"dd_{n}"] = str(target)
            if f.organization == "cicsdb":  # the CICS region's state: files, queues, terminal, COMMAREA
                import sqlite3

                from .cicsbridge import seed

                conn = sqlite3.connect(str(target), isolation_level=None)
                seed(conn, case.files.get(f.assign, b""))
                conn.close()
                env["SEANCE_CICSDB"] = str(target)
                continue
            if f.organization == "sqldb":  # the database: seeded before the run, dumped after
                from .sqlbridge import seed_file

                seed_file(target, case.files.get(f.assign, b""))
                env["SEANCE_SQLDB"] = str(target)
                continue
            if f.keyed:
                tools[f.assign] = keyed.tools(f, exe.parent, cobc_path(), cobol_env())
            if f.is_input and f.assign in case.files:
                if f.keyed:
                    keyed.load(tools[f.assign][0], case.files[f.assign], target, work, env)
                else:
                    target.write_bytes(case.files[f.assign])
        stdin = "".join(line + "\n" for line in case.stdin).encode(ENC, errors="replace")
        cicsdb = next((paths[f.assign] for f in model.all_files if f.organization == "cicsdb"), None)
        try:
            proc = subprocess.run([str(exe)], cwd=work, input=stdin, capture_output=True, env=env, timeout=timeout)
            while cicsdb is not None and proc.returncode == 0:  # the next screen of a pseudo-conversation
                import sqlite3

                from .cicsbridge import next_turn

                conn = sqlite3.connect(str(cicsdb), isolation_level=None)
                more = next_turn(conn)
                conn.close()
                if not more:
                    break
                again = subprocess.run([str(exe)], cwd=work, input=b"", capture_output=True, env=env, timeout=timeout)
                proc = subprocess.CompletedProcess(proc.args, again.returncode, proc.stdout + again.stdout, proc.stderr + again.stderr)
        except subprocess.TimeoutExpired:
            raise LegacyRuntimeError(
                f"The COBOL program did not finish within {timeout} seconds. A loop probably never ends, or it waits for more console input."
            ) from None
        outputs = {}
        for f in model.all_files:
            if not f.is_output or not paths[f.assign].exists():
                continue
            if f.organization in ("sqldb", "cicsdb"):
                from .sqlbridge import dump_file

                outputs[f.assign] = dump_file(paths[f.assign])
                continue
            if f.keyed:
                data = keyed.dump(tools[f.assign][1], paths[f.assign], work, env)
                if data is not None:
                    outputs[f.assign] = data
            else:
                outputs[f.assign] = paths[f.assign].read_bytes()
        err = proc.stderr.decode(ENC, errors="replace")
        error = None
        m = re.search(r"libcob: (?:error|.*?error): (.*)", err)
        if m and proc.returncode != 0:
            error = m.group(1).strip()
        return Result(outputs, proc.stdout.decode(ENC, errors="replace").replace("\r\n", "\n"), proc.returncode, error)


RUN_LIMIT_SECONDS = 120


def run_python(module, case: Case, limit: float | None = None) -> Result:
    """Run the Python on a case. It runs in a thread that is given `limit` seconds (RUN_LIMIT_SECONDS): an endless loop in the
    Python is a failed run that says so, not a checker that never returns."""
    import threading

    box: list[Result] = []

    def work() -> None:
        import decimal

        decimal.getcontext().prec = 60  # a thread starts with 28 digits; the program's numbers need the same 60 as the main thread's
        box.append(_run_python(module, case))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    limit = limit or RUN_LIMIT_SECONDS + 2.0 * sum(len(v) for v in case.files.values()) / 1e6  # the Python reads about half a MB a second
    t.join(limit)
    if box:
        return box[0]
    return Result(error=f"TimeoutError: the Python did not finish in {int(limit)} seconds")


def _run_python(module, case: Case) -> Result:
    from .rt import IO

    io = IO(dict(case.files), list(case.stdin))
    io.clock = FIXED_CLOCK  # the COBOL runs on COB_CURRENT_DATE = this; the Python is told the same moment
    main = getattr(module, "main", None)
    if main is None:
        return Result(error="the Python module has no main(io) function")
    try:
        out = main(io)
        io = out if out is not None else io
        if "CICSDB" in case.files:  # a pseudo-conversation: run again while the program asks for the next screen
            from .cicsbridge import next_turn
            from .sqlbridge import dump

            while getattr(io, "cics", None) is not None and int(io.return_code or 0) == 0 and next_turn(io.cics.conn):
                io.cics.last, io.cics.browse, io.cics.qpos = {}, {}, {}
                out = main(io)
                io = out if out is not None else io
            if getattr(io, "cics", None) is not None:
                io.outputs["CICSDB"] = dump(io.cics.conn)
        return Result(dict(io.outputs), io.stdout.replace("\r\n", "\n"), int(io.return_code or 0))
    except Exception as exc:  # the program's own failure is a result, not a crash of the checker
        if getattr(io, "cics", None) is not None:
            from .sqlbridge import dump

            io.outputs["CICSDB"] = dump(io.cics.conn)
        return Result(dict(io.outputs), io.stdout.replace("\r\n", "\n"), int(getattr(io, "return_code", 0) or 0), f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- comparing

def text_only(f: FileDef | None) -> bool:
    """True when every field of the record is text or DISPLAY digits. Only then can a 0x0A or 0x0C byte between records be the line
    or page break of a print file; in a record with packed, binary or floating-point fields those bytes are data."""
    return f is None or f.record is None or all(lf.item.usage == "display" for lf in leaves(f.record))
def text_only(f: FileDef | None) -> bool:
    """True when every field of the record is text or DISPLAY digits. Only then can a 0x0A or 0x0C byte between records be the line
    or page break of a print file; in a record with packed, binary or floating-point fields those bytes are data."""
    return f is None or f.record is None or all(lf.item.usage == "display" for lf in leaves(f.record))
def text_only(f: FileDef | None) -> bool:
    """True when every field of the record is text or DISPLAY digits. Only then can a 0x0A or 0x0C byte between records be the line
    or page break of a print file; in a record with packed, binary or floating-point fields those bytes are data."""
    return f is None or f.record is None or all(lf.item.usage == "display" for lf in leaves(f.record))
def _units(f: FileDef | None, data: bytes) -> list[bytes]:
    """Split an output stream into records or lines."""
    if f is not None and f.organization in ("sqldb", "cicsdb"):
        f = None
    if f is not None and f.keyed:
        step = f.size + (9 if f.organization == "relative" else 0)
        return [data[i:i + step] for i in range(0, len(data), step)]
    if f is not None and f.variable:
        out, i = [], 0
        while i < len(data):
            if data[i:i + 1] in (b"\n", b"\r", b"\f"):
                i += 1
                continue
            n = int.from_bytes(data[i:i + 2], "big")
            out.append(data[i + 4:i + 4 + n])
            i += 4 + n
        return out
    if f is not None and f.organization != "line" and (b"\n" in data or b"\f" in data) and text_only(f):
        return _record_units(f, data)
    if f is None or f.organization == "line":
        text = data.replace(b"\r\n", b"\n")
        rows = re.split(rb"\n", text)
        if rows and rows[-1] == b"":
            rows.pop()
        elif rows and text:
            rows[-1] += b"[no line end]"  # the last line was left open: the other side must leave it open too
        return rows
    size = f.size or len(data) or 1
    return [data[i:i + size] for i in range(0, len(data), size)]


def _record_units(f: FileDef, data: bytes) -> list[bytes]:
    """Records of a fixed-length file. WRITE ... ADVANCING puts line and page breaks between records in such a file
    (GnuCOBOL writes a bare \\n or \\f), so split at those first, then into records."""
    if b"\n" not in data and b"\f" not in data:
        return _units(f, data)
    size = f.size or 1
    out = []
    parts = re.split(rb"([\n\f])", data)
    for k in range(0, len(parts), 2):
        piece = parts[k]
        page = k > 0 and parts[k - 1] == b"\f"  # a page break stays visible: it starts the next record with a mark
        chunks = [piece[i:i + size] for i in range(0, len(piece), size)] or [b""]
        if page:
            chunks[0] = b"\f" + chunks[0]
        out += chunks
    while out and out[-1] == b"":
        out.pop()
    return out


def show(data: bytes) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 or 160 <= ord(ch) < 256 else "·" for ch in data.decode(ENC))


def decode_fields(f: FileDef, unit: bytes) -> list[tuple[str, str]]:
    rec = f.record
    if rec is None:
        return []
    out_slot = []
    if f.organization == "relative":
        out_slot, unit = [("(slot)", unit[:9].decode(ENC).lstrip("0") or "0")], unit[9:]
    data = unit.ljust(rec.size, b" ")
    out = []
    for lf in leaves(rec):
        raw = data[lf.offset:lf.offset + lf.width]
        it = lf.item
        if it.kind == "num":
            v = decode(spec_of(it), raw)
            out.append((lf.name, format(v, "f")))
        else:
            out.append((lf.name, show(raw)))
    return out_slot + out


def stop_kind(message: str) -> str | None:
    """What kind of stop an error message describes, whoever worded it: a hang, a bad subscript, a bad reference modification, or a file
    status. None when it is something else."""
    m = message.lower()
    if "loop steps" in m or m.startswith("timeouterror") or "did not finish" in m:
        return "hang"
    if "subscript" in m:
        return "subscript"
    if "offset" in m or "reference modification" in m or "ref-mod" in m or "length of" in m and "out of bounds" in m:
        return "reference modification"
    st = re.search(r"status\s*=\s*(\d\d)", m)
    if st:
        return f"file status {st.group(1)}"
    if "module" in m and "not found" in m:
        return "missing module"
    return None


def compare(model: ProgramModel, expected: Result, actual: Result, limit: int = 50) -> tuple[list[Diff], int]:
    """Differences between two results, and the number of output records/lines compared."""
    diffs: list[Diff] = []
    units = 0
    if (expected.error is None) != (actual.error is None):
        diffs.append(Diff("run", -1, expected.error or "finished normally", actual.error or "finished normally"))
    elif expected.error is not None:
        # Both stopped with an error. The COBOL's message is libcob's wording and the Python's is the runtime's, so the words are not
        # compared. What is compared is the kind of stop: the runtime's own CobolError stands for a libcob error, anything else
        # (ZeroDivisionError, KeyError, NotImplementedError ...) is the Python crashing where the COBOL stopped in an orderly way.
        if not actual.error.startswith("CobolError"):
            diffs.append(Diff("run", -1, expected.error, actual.error))
        else:
            # the status a file error carries is part of the stop: libcob says "(status = 35)", the runtime says the same
            e_code, a_code = (re.search(r"status\s*=\s*(\d\d)", m) for m in (expected.error, actual.error))
            e_kind, a_kind = stop_kind(expected.error), stop_kind(actual.error)
            if e_code and a_code and e_code.group(1) != a_code.group(1):
                diffs.append(Diff("run", -1, expected.error, actual.error))
            elif e_kind != a_kind and (e_kind or a_kind):  # a stop one side can name and the other cannot is not the same stop
                diffs.append(Diff("run", -1, f"stopped: {e_kind or expected.error}", f"stopped: {a_kind or actual.error}"))  # not the same stop
    elif expected.return_code != actual.return_code:
        diffs.append(Diff("run", -1, f"return code {expected.return_code}", f"return code {actual.return_code}"))
    streams = sorted(set(expected.outputs) | set(actual.outputs))
    for name in streams + [CONSOLE]:
        f = next((x for x in model.all_files if x.assign == name), None)
        if name == CONSOLE:
            e_units, a_units = _units(None, expected.stdout.encode(ENC, errors="replace")), _units(None, actual.stdout.encode(ENC, errors="replace"))
        else:
            if name not in expected.outputs or name not in actual.outputs:
                diffs.append(Diff(name, -1, "written" if name in expected.outputs else "not written", "written" if name in actual.outputs else "not written"))
                continue
            e_units, a_units = _units(f, expected.outputs[name]), _units(f, actual.outputs[name])
        units += max(len(e_units), len(a_units))
        for i in range(max(len(e_units), len(a_units))):
            e = e_units[i] if i < len(e_units) else None
            a = a_units[i] if i < len(a_units) else None
            if e == a:
                continue
            d = Diff(name, i, show(e) if e is not None else "(no line)", show(a) if a is not None else "(no line)")
            if f is not None and e is not None and a is not None and f.record is not None and f.organization != "line" or (
                    f is not None and f.organization == "line" and e is not None and a is not None):
                ef, af = decode_fields(f, e), decode_fields(f, a)
                d.fields = [{"name": n, "expected": ev, "actual": av, "same": ev == av} for (n, ev), (_, av) in zip(ef, af)]
            diffs.append(d)
    return diffs, units


def count_differing(diffs: list[Diff]) -> int:
    return len(diffs)


# ---------------------------------------------------------------- generating

def _edge_values(it: Item) -> list:
    if it.kind == "alpha":
        return [" " * it.size, "A" * min(it.size, 4), "Z" * it.size]
    if it.kind == "edited":
        return [Decimal(0), Decimal(1)]
    unit = Decimal(1).scaleb(-it.scale)
    top = it.max_value
    vals = [Decimal(0), unit, top, top - unit, Decimal(10) ** (it.digits - it.scale - 1) if it.digits > it.scale else unit]
    if it.signed:
        vals += [-unit, -top]
    return sorted(set(vals))


def _random_value(it: Item, rng: random.Random, n: int):
    if it.kind == "alpha":
        return (rng.choice("ABCDEFGHJKLMNPRSTW") + f"{n:04d}" + rng.choice(["", " X", "YZ"]))[: it.size]
    digits = it.digits if it.kind == "num" else 5
    scale = it.scale if it.kind == "num" else 2
    use = min(rng.choice([2, 3, 4, digits]) if rng.random() < 0.8 else digits, digits)
    raw = rng.randrange(0, 10**max(use, 1))
    if it.kind == "num" and it.signed and rng.random() < 0.3:
        raw = -raw
    return Decimal(raw).scaleb(-scale)


def encode_record(rec: Item, values: dict[int, object]) -> bytes:
    """Bytes of one record. values: leaf position -> value; unset text is spaces, unset numbers zero."""
    buf = bytearray(b" " * rec.size)
    for i, lf in enumerate(leaves(rec)):
        it = lf.item
        if lf.name == "FILLER":
            continue
        v = values.get(i)
        sp = spec_of(it)
        if v is None:
            v = Decimal(0) if it.kind in ("num", "edited") else ""
        if it.kind == "num":
            v = store_into(sp, Decimal(v), move=True)
        buf[lf.offset:lf.offset + lf.width] = encode(sp, v)
    return bytes(buf)


def pack_file(f: FileDef, records: list[bytes]) -> bytes:
    if f.organization == "relative":  # slot number, then the record: record n goes in slot n
        return b"".join(b"%09d" % (i + 1) + r.ljust(f.size, b" ")[:f.size] for i, r in enumerate(records))
    if f.organization == "line":
        return b"".join(r.rstrip(b" ").replace(b"\n", b" ").replace(b"\r", b" ") + b"\n" for r in records)
    if f.variable:
        return b"".join(len(r).to_bytes(2, "big") + b"\x00\x00" + r for r in records)
    size = f.size
    return b"".join(r.ljust(size, b" ")[:size] for r in records)


def file_records(f: FileDef, rows: list[dict[int, object]]) -> list[bytes]:
    return [encode_record(f.record, r) for r in rows]


def edge_rows(rec: Item, hints: dict[str, list]) -> list[dict[int, object]]:
    lv = leaves(rec)
    base0 = {}
    base1 = {}
    for i, lf in enumerate(lv):
        it = lf.item
        if it.kind == "alpha":
            base0[i] = base1[i] = "A" * min(it.size, 4)
        else:
            base0[i] = Decimal(0)
            base1[i] = Decimal(1).scaleb(-it.scale) if it.kind == "num" else Decimal(1)
    rows = [dict(base0), dict(base1)]
    for i, lf in enumerate(lv):
        if lf.name == "FILLER":
            continue
        for v in _edge_values(lf.item):
            for base in (base0, base1):
                r = dict(base)
                r[i] = v
                rows.append(r)
        for v in hints.get(lf.item.name, []):
            r = dict(base1)
            r[i] = v
            rows.append(r)
    top = {i: ("Z" * lf.item.size if lf.item.kind == "alpha" else (lf.item.max_value if lf.item.kind == "num" else Decimal(9))) for i, lf in enumerate(lv)}
    rows.append(top)
    out, seen = [], set()
    for r in rows:
        k = tuple(sorted((i, str(v)) for i, v in r.items()))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def random_rows(rec: Item, count: int, rng: random.Random, hints: dict[str, list]) -> list[dict[int, object]]:
    lv = leaves(rec)
    rows = []
    for n in range(count):
        r = {}
        for i, lf in enumerate(lv):
            if lf.name == "FILLER":
                continue
            h = hints.get(lf.item.name)
            r[i] = rng.choice(h) if h and rng.random() < 0.5 else _random_value(lf.item, rng, n)
        rows.append(r)
    return rows


def console_lines(model: ProgramModel, hints: dict[str, list], rng: random.Random | None, rounds: int = 3) -> list[str]:
    """Console input for programs that ACCEPT: values for each ACCEPT target, then the values the code tests for."""
    if not model.all_accepts:
        return []
    from .translate import build_names

    names, _ = build_names(model)

    def text(v) -> str:
        return format(v, "f") if isinstance(v, Decimal) else str(v)

    lines = []
    for k in range(rounds):
        for name in model.all_accepts:
            it = names.by_name.get(name, [None])[0]
            if it is None or it.kind != "num":
                lines.append(("A" if rng is None else rng.choice("ABCXYZ")) * min(it.size if it else 4, 5))
            else:
                v = Decimal(k + 1) if rng is None else Decimal(rng.randrange(0, 10 ** min(it.digits - it.scale, 4)))
                lines.append(text(v))
    # Then rounds that use the values the code tests for (such as 'NO' or 9 to quit), so input loops can end.
    most = max((len(hints.get(n, [])) for n in model.all_accepts), default=0)
    for j in range(most):
        for name in model.all_accepts:
            h = hints.get(name, [])
            lines.append(text(h[j % len(h)]) if h else lines[model.all_accepts.index(name)] if lines else "")
    return lines


def _text_pool(model: ProgramModel, rows_by_file: dict) -> dict[int, list[str]]:
    """Text values of the generated input records, by length: table keys drawn from them meet the input."""
    pool: dict[int, list[str]] = {}
    for f in model.inputs:
        if f.record is None:
            continue
        lv = leaves(f.record)
        for row in rows_by_file.get(f.name, []):
            for i, v in row.items():
                if i < len(lv) and lv[i].item.kind == "alpha" and isinstance(v, str) and v.strip():
                    pool.setdefault(lv[i].item.size, []).append(v)
    return pool


def table_rows(model: ProgramModel, rng: random.Random | None, count: int, pool: dict | None = None) -> dict[str, list[list]]:
    """Rows for each SQL table, from its column types: boundary values for the edge set, random ones otherwise.
    The first (key) column takes about half its values from input fields of the same length, so lookups hit."""
    pool = pool or {}
    out = {}
    for name, t in model.sql_tables.items():
        rows = []
        n = 6 if rng is None else count
        for k in range(n):
            row = []
            for ci, (col, typ, notnull) in enumerate(t.columns):
                u = typ.upper()
                m = re.match(r"(?:DECIMAL|DEC|NUMERIC)\s*\((\d+)(?:\s*,\s*(\d+))?\)", u)
                ln = re.match(r"(?:CHAR|CHARACTER|VARCHAR)\s*\((\d+)\)", u)
                if rng is not None and not notnull and rng.random() < 0.1:
                    row.append(None)
                elif m:
                    p, sc = int(m.group(1)), int(m.group(2) or 0)
                    top = 10 ** (p - sc) - Decimal(1).scaleb(-sc)
                    edge = [Decimal(0), Decimal(1).scaleb(-sc), top, -top, Decimal(1), Decimal(-1)]
                    v = edge[k % len(edge)] if rng is None else Decimal(rng.randrange(-(10 ** min(p, 7)), 10 ** min(p, 7))).scaleb(-sc)
                    row.append(format(v, "f"))
                elif re.match(r"(SMALLINT|INTEGER|INT|BIGINT)\b", u):
                    row.append(k + 1 if ci == 0 else (k if rng is None else rng.randrange(0, 1000)))
                else:
                    size = int(ln.group(1)) if ln else 10
                    if ci == 0:
                        v = f"K{k + 1:0{max(1, min(size - 1, 6))}d}"
                        same = pool.get(size, [])
                        if same and (k % 2 == 0 if rng is None else rng.random() < 0.5):
                            v = same[k % len(same)] if rng is None else rng.choice(same)
                    else:
                        v = ("A" * min(size, 4)) if rng is None else rng.choice(["SMITH", "JONES", "GARCIA", "LEE", "O'NEIL", "MÜLLER", "BROWN"])
                    row.append(v[:size])
            rows.append(row)
        out[name] = rows
    return out


def _area_bytes(it: Item, row: dict[int, object]) -> bytes:
    """Bytes of any data item (not only an 01) from leaf values, as encode_record does for records."""
    buf = bytearray(b" " * it.size)
    for i, lf in enumerate(leaves(it)):
        if lf.name == "FILLER":
            continue
        sp = spec_of(lf.item)
        v = row.get(i)
        if v is None:
            v = Decimal(0) if lf.item.kind in ("num", "edited") else ""
        if lf.item.kind == "num":
            v = store_into(sp, Decimal(v), move=True)
        buf[lf.offset:lf.offset + lf.width] = encode(sp, v)
    return bytes(buf)


AID_MIX = ["'"] * 6 + ["_", "@", "1", "%"]  # mostly ENTER, sometimes CLEAR, PF12, PF1, PA1
EDGE_AIDS = ["_", "@", "%", "1"]  # the edge set ends with these keys, then PF3


def cics_seed(model: ProgramModel, rng: random.Random | None, count: int) -> tuple[bytes, int]:
    """The CICS region a transaction starts in: file records, the screens the user will send, an empty COMMAREA."""
    from .cicspre import usage
    from .hints import value_hints
    from .translate import build_names

    names, _ = build_names(model)
    use = usage(model.path.read_text(encoding="utf-8", errors="replace"))
    hints = value_hints(model)

    def item(ref):
        if not ref:
            return None
        base = re.split(r"[\s(]", ref.strip(), 1)[0].upper()
        found = names.by_name.get(base)
        return found[0] if found else None

    lines, keys_by_len = [], {}
    n = 30 if rng is None else count
    for fname, f in sorted(use["files"].items()):
        area, keyit = item(f["area"]), item(f["key"])
        if area is None:
            continue
        kl = keyit.size if keyit is not None else min(8, area.size)
        rows = edge_rows(area, hints)[:n] if rng is None else random_rows(area, n, rng, hints)
        seen: set[bytes] = set()
        for i, r in enumerate(rows):
            rec = bytearray(_area_bytes(area, r))
            if bytes(rec[:kl]) in seen:  # the key starts the record (as in a KSDS); give every edge record its own
                rec[:kl] = str(i).zfill(kl)[-kl:].encode()
            if bytes(rec[:kl]) in seen:
                continue
            rec = bytes(rec)
            key = rec[:kl]
            seen.add(key)
            keys_by_len.setdefault(kl, []).append(key)
            if rng is None and i == len(rows) - 1:  # one record longer than the program's area: READ gives LENGERR
                long_key = str(len(rows)).zfill(kl)[-kl:].encode()
                if long_key not in seen:
                    long_rec = long_key + rec[kl:] + b"+"
                    lines.append(f"INSERT OR IGNORE INTO files VALUES ('{fname}', X'{long_key.hex()}', X'{long_rec.hex()}');")
                    keys_by_len[kl].insert(0, long_key)
            lines.append(f"INSERT OR IGNORE INTO files VALUES ('{fname}', X'{key.hex()}', X'{rec.hex()}');")
    screens = 0
    for ref in dict.fromkeys(use["receives"]):
        area = item(ref)
        if area is None:
            continue
        rows = edge_rows(area, hints)[:n] if rng is None else random_rows(area, n, rng, hints)
        if rng is None:
            aids = ["'"] * len(rows) + ["'"] + EDGE_AIDS + ["3"]
            rows = rows + [None] + rows[:len(EDGE_AIDS) + 1]  # None: ENTER with nothing typed
        else:
            aids = [rng.choice(AID_MIX) for _ in rows] + (["3"] if rng.random() < 0.5 else [])
            rows = rows + rows[:len(aids) - len(rows)]
        for k, r in enumerate(rows):
            if r is None:
                screens += 1
                lines.append(f"INSERT INTO term_in (seq, aid, data) VALUES ({screens}, X'27', X'');")
                continue
            data = bytearray(_area_bytes(area, r))
            for lf in leaves(area):  # typed keys that exist in the files, about half the time
                pool = keys_by_len.get(lf.width)
                if pool and lf.item.kind == "alpha" and (k % 2 == 0 if rng is None else rng.random() < 0.5):
                    data[lf.offset:lf.offset + lf.width] = pool[k % len(pool)] if rng is None else rng.choice(pool)
            aid = aids[k]
            screens += 1
            lines.append(f"INSERT INTO term_in (seq, aid, data) VALUES ({screens}, X'{aid.encode().hex()}', X'{bytes(data).hex()}');")
    lines.append("INSERT INTO control VALUES ('commarea_in', X'');")
    return ("\n".join(lines) + "\n").encode(ENC), screens + sum(1 for l in lines if l.startswith("INSERT OR IGNORE INTO files"))


def build_case(model: ProgramModel, rows_by_file: dict[str, list[dict[int, object]]], stdin: list[str],
               tables: dict[str, list[list]] | None = None, rng: random.Random | None = None, cics_count: int = 0) -> Case:
    case = Case(stdin=list(stdin))
    if model.cics:
        seed, n = cics_seed(model, rng, cics_count or 12)
        case.files["CICSDB"] = seed
        case.records["CICSDB"] = [b""] * n
    if model.sql_tables:
        from .sqlpre import schema_and_seed

        case.files["SQLDB"] = schema_and_seed(model.sql_tables, tables or {}).encode(ENC, errors="replace")
        case.records["SQLDB"] = [b""] * sum(len(v) for v in (tables or {}).values())
    for f in model.inputs:
        if f.record is None:
            continue
        recs = file_records(f, rows_by_file.get(f.name, []))
        case.records[f.assign] = recs
        case.files[f.assign] = pack_file(f, recs)
    return case


def key_links(model: ProgramModel) -> list[tuple[str, int, str, object]]:
    """Fields of one input file that the program MOVEs into the key of a keyed file it reads.

    Returns (file, leaf position, keyed file, key leaf position or "slot"). Generated transactions then use keys
    that exist in the generated master often enough to reach the "record found" paths.
    """
    moved: dict[str, set[str]] = {}
    for m in model._every():
        words = " ".join(t for _, t in m.proc_items).upper().split()
        for i, w in enumerate(words):
            if w == "MOVE" and i + 3 < len(words) and words[i + 2] == "TO":
                moved.setdefault(words[i + 1], set()).add(words[i + 3].rstrip("."))
    links = []
    for kf in model.inputs:
        if not kf.keyed or kf.record is None:
            continue
        targets: dict[str, object] = {}
        if kf.organization == "indexed":
            klv = leaves(kf.record)
            for key in [kf.record_key, *[k for k, _ in kf.alt_keys]]:
                pos = next((i for i, lf in enumerate(klv) if lf.item.name == key), None)
                if pos is not None:
                    targets[key] = pos
        elif kf.relative_key:
            targets[kf.relative_key] = "slot"
        for f in model.inputs:
            if f is kf or f.record is None:
                continue
            for i, lf in enumerate(leaves(f.record)):
                for key, pos in targets.items():
                    if key in moved.get(lf.item.name, set()):
                        links.append((f.name, i, kf.name, pos))
    return links


def apply_links(links, rows_by_file: dict, rng: random.Random, share: float = 0.6) -> None:
    for src, i, dst, pos in links:
        pool = rows_by_file.get(dst) or []
        if not pool:
            continue
        for row in rows_by_file.get(src, []):
            if rng.random() < share:
                row[i] = Decimal(rng.randrange(1, len(pool) + 1)) if pos == "slot" else rng.choice(pool).get(pos, row.get(i))


def generated_cases(model: ProgramModel, random_count: int = 300, seed: int = 1031) -> dict[str, Case]:
    from .hints import value_hints

    hints = value_hints(model)
    rng = random.Random(seed)
    links = key_links(model)
    edges = {f.name: edge_rows(f.record, hints) for f in model.inputs if f.record is not None}
    rand = {f.name: random_rows(f.record, random_count, rng, hints) for f in model.inputs if f.record is not None}
    apply_links(links, edges, random.Random(seed + 1))
    apply_links(links, rand, rng)
    sets = {"edges": build_case(model, edges, console_lines(model, hints, None), table_rows(model, None, 0, _text_pool(model, edges)))}
    if model.inputs or model.all_accepts:
        sets["random"] = build_case(model, rand, console_lines(model, hints, rng), table_rows(model, rng, 40, _text_pool(model, rand)),
                                    rng, 40)
    # Input files that are not there: reaches the code that handles a missing file, where the program checks for it
    if any(f.status or f.optional for f in model.inputs):
        sets["missing"] = Case(stdin=console_lines(model, hints, None))
    return sets


# ---------------------------------------------------------------- saving

def set_dir(program: str, name: str, root: Path = ROOT) -> Path:
    return root / "fixtures" / program / name


def save_set(program: str, name: str, case: Case, result: Result, label: str, root: Path = ROOT) -> None:
    d = set_dir(program, name, root)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    meta = {"label": label, "stdin": case.stdin, "inputs": {}, "outputs": {}, "return_code": result.return_code, "error": result.error,
            "records": sum(len(v) for v in case.records.values()) if case.records else 0, "console_lines": len(case.stdin)}
    for i, (assign, data) in enumerate(sorted(case.files.items())):
        fn = f"in{i}.dat"
        (d / fn).write_bytes(data)
        meta["inputs"][assign] = fn
    for i, (assign, data) in enumerate(sorted(result.outputs.items())):
        fn = f"out{i}.dat"
        (d / fn).write_bytes(data)
        meta["outputs"][assign] = fn
    (d / "console.txt").write_text(result.stdout, encoding="utf-8")
    from .report import source_sha

    meta["cobol_sha256"] = source_sha(program, root)  # the COBOL these answers came from: a later check refuses them for other COBOL
    (d / "set.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_set(program: str, name: str, root: Path = ROOT) -> tuple[Case, Result, dict]:
    d = set_dir(program, name, root)
    meta = json.loads((d / "set.json").read_text(encoding="utf-8"))
    case = Case({a: (d / fn).read_bytes() for a, fn in meta["inputs"].items()}, meta["stdin"])
    result = Result({a: (d / fn).read_bytes() for a, fn in meta["outputs"].items()}, (d / "console.txt").read_text(encoding="utf-8"),
                    meta["return_code"], meta.get("error"))
    return case, result, meta


def set_names(program: str, root: Path = ROOT) -> list[str]:
    base = root / "fixtures" / program
    if not base.exists():
        return []
    order = {"edges": 0, "random": 1, "missing": 2}
    names = [p.name for p in base.iterdir() if (p / "set.json").exists()]
    return sorted(names, key=lambda n: (order.get(n, 2), n))


DEFAULT_LABELS = {
    "edges": "Edge Cases (zero, smallest and largest values, plus values the code tests for)",
    "random": "Random Records",
    "missing": "Missing Input Files (how the program handles a file that is not there)",
}


def record_sets(program: str, root: Path = ROOT) -> dict[str, int]:
    """Generate the standard test sets, run the real COBOL on each, and save case + result."""
    from .config import RANDOM_RECORDS, RUN_TIMEOUT
    from .recorder import compile_legacy, get_model

    model = get_model(program, root)
    exe = compile_legacy(program, root)
    base = root / "fixtures" / program
    if base.exists():
        for p in base.iterdir():  # keep uploaded data and mainframe outputs; regenerate the rest
            if p.is_dir() and not p.name.startswith(("yours-", "golden-", "gap-")):
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
    counts = {}
    for name, case in generated_cases(model, RANDOM_RECORDS).items():
        result = run_cobol(exe, model, case, RUN_TIMEOUT)
        save_set(program, name, case, result, DEFAULT_LABELS.get(name, name), root)
        counts[name] = sum(len(v) for v in case.records.values()) or 1
    for name in set_names(program, root):  # uploaded data: refresh the COBOL's answers too
        if name.startswith(("yours-", "gap-")):
            case, _, meta = load_set(program, name, root)
            save_set(program, name, case, run_cobol(exe, model, case), meta["label"], root)
    return counts


def add_uploaded(program: str, filename: str, data: bytes, target_file: str | None, stdin: list[str] | None = None, root: Path = ROOT,
                 code_page: str | None = None) -> dict:
    """Save uploaded input data as a test set, with the real COBOL's answers for it.

    code_page: the file is EBCDIC from a mainframe (for example cp037); it is converted field by field first.
    The program's other inputs come from the first saved set, so one real file can be tried on its own.
    """
    from .config import MAX_DATA_RECORDS
    from .recorder import compile_legacy, get_model

    model = get_model(program, root)
    inputs = model.inputs
    if not inputs and not model.all_accepts:
        raise ValueError("This program reads no input files and no console input, so there is nothing to upload.")
    if inputs:
        f = next((x for x in inputs if x.assign == target_file or x.name == target_file), inputs[0] if len(inputs) == 1 or target_file is None else None)
        if f is None:
            raise ValueError(f"Unknown input file {target_file}.")
        if code_page:
            if f.organization == "line":
                data = data.decode(code_page).encode(ENC, errors="replace").replace(b"\x85", b"\n").replace(b"\x25", b"\n")
            else:
                from .ebcdic import file_to_ascii

                data = file_to_ascii(f.record, f.size, data, code_page)
        fixed = f.organization in ("sequential", "indexed", "relative")
        if fixed and data and len(data) % max(f.size, 1):
            raise ValueError(f"The file is {len(data)} bytes, which is not a whole number of {f.size}-byte records for {f.assign}.")
        units = [data[i:i + f.size] for i in range(0, len(data), f.size)] if fixed else _units(None, data)
        if f.organization == "relative":
            data = pack_file(f, units)
        n = len(units)
        if MAX_DATA_RECORDS and n > MAX_DATA_RECORDS:
            raise ValueError(f"The file has {n} records. The limit is {MAX_DATA_RECORDS}; split it into smaller files.")
        names = set_names(program, root)
        base = load_set(program, names[0], root)[0] if names else Case()
        case = Case({**base.files, f.assign: data}, list(stdin) if stdin is not None else list(base.stdin))
        case.records = {**base.records, f.assign: units}
    else:
        case = Case({}, list(stdin) if stdin is not None else data.decode(ENC).splitlines())
        n = len(case.stdin)
    from .config import RUN_TIMEOUT

    size_mb = sum(len(v) for v in case.files.values()) / 1e6
    result = run_cobol(compile_legacy(program, root), model, case, RUN_TIMEOUT + int(size_mb * 0.5))  # a big file gets time to match
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename or "data").stem.lower()).strip("-")[:30] or "data"
    name, k = f"yours-{stem}", 2
    while set_dir(program, name, root).exists():
        name, k = f"yours-{stem}-{k}", k + 1
    label = f"Your Data: {Path(filename).name or 'uploaded file'}"
    save_set(program, name, case, result, label, root)
    return {"set": name, "records": n, "label": label}


def _ascii(f: FileDef, data: bytes, code_page: str | None) -> bytes:
    """A file from the mainframe (EBCDIC) as the bytes GnuCOBOL reads and writes."""
    if not code_page:
        return data
    if f.organization == "line":
        return data.decode(code_page).encode(ENC, errors="replace").replace(b"\x85", b"\n").replace(b"\x25", b"\n")
    from .ebcdic import file_to_ascii
    return file_to_ascii(f.record, f.size, data, code_page)


def add_golden(program: str, filename: str, inputs: dict[str, bytes], outputs: dict[str, bytes], console_output: bytes | None = None,
               stdin: list[str] | None = None, root: Path = ROOT, code_page: str | None = None) -> dict:
    """Save a parallel run: input data plus the output your own mainframe produced for it. The Python is checked against
    what the mainframe wrote, not against GnuCOBOL. GnuCOBOL is run too, and the set records whether it agrees with the
    mainframe, since a difference there means the local COBOL is not a faithful stand-in for your system on this data.
    Output files you do not provide are taken from the GnuCOBOL run and marked as such.
    """
    from .config import MAX_DATA_RECORDS, RUN_TIMEOUT
    from .recorder import compile_legacy, get_model

    model = get_model(program, root)
    by_name = {f.assign: f for f in model.all_files}
    if not outputs and console_output is None:
        raise ValueError("Give at least one output file (or the console output) from the mainframe run.")
    names = set_names(program, root)
    base = load_set(program, names[0], root)[0] if names else Case()
    case = Case(dict(base.files), list(stdin) if stdin is not None else list(base.stdin), dict(base.records))
    count = 0
    for assign, raw in inputs.items():
        f = by_name.get(assign)
        if f is None or not f.is_input:
            raise ValueError(f"{assign} is not an input file of this program.")
        data = _ascii(f, raw, code_page)
        fixed = f.organization in ("sequential", "indexed", "relative")
        if fixed and data and len(data) % max(f.size, 1):
            raise ValueError(f"The input for {assign} is {len(data)} bytes, which is not a whole number of {f.size}-byte records.")
        units = [data[i:i + f.size] for i in range(0, len(data), f.size)] if fixed else _units(None, data)
        if MAX_DATA_RECORDS and len(units) > MAX_DATA_RECORDS:
            raise ValueError(f"The input for {assign} has {len(units)} records. The limit is {MAX_DATA_RECORDS}.")
        case.files[assign] = pack_file(f, units) if f.organization == "relative" else data
        case.records[assign] = units
        count += len(units)
    expected = Result()
    for assign, raw in outputs.items():
        f = by_name.get(assign)
        if f is None or not f.is_output:
            raise ValueError(f"{assign} is not an output file of this program.")
        data = _ascii(f, raw, code_page)
        if f.organization in ("sequential", "indexed", "relative") and data and len(data) % max(f.size, 1):
            raise ValueError(f"The output for {assign} is {len(data)} bytes, which is not a whole number of {f.size}-byte records.")
        expected.outputs[assign] = data
    cobol = run_cobol(compile_legacy(program, root), model, case, RUN_TIMEOUT)
    filled = sorted(set(cobol.outputs) - set(expected.outputs))
    for assign in filled:
        expected.outputs[assign] = cobol.outputs[assign]
    if console_output is not None:
        expected.stdout = console_output.decode(code_page or ENC, errors="replace").replace("\r\n", "\n")
    else:
        expected.stdout = cobol.stdout
    expected.return_code = 0
    diffs, _units_n = compare(model, expected, Result(cobol.outputs, cobol.stdout, cobol.return_code, cobol.error))
    stem = re.sub(r"[^a-z0-9]+", "-", Path(filename or "mainframe").stem.lower()).strip("-")[:30] or "mainframe"
    name, k = f"golden-{stem}", 2
    while set_dir(program, name, root).exists():
        name, k = f"golden-{stem}-{k}", k + 1
    label = f"Mainframe Output: {Path(filename).name or 'your run'}"
    save_set(program, name, case, expected, label, root)
    meta_path = set_dir(program, name, root) / "set.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({"golden": True, "cobol_agrees": not diffs, "cobol_differences": len(diffs), "provided": sorted(outputs), "filled_from_cobol": filled,
                 "records": count or meta.get("records", 0)})
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"set": name, "label": label, "records": meta["records"], "cobol_agrees": not diffs, "cobol_differences": len(diffs), "filled_from_cobol": filled}


def remove_uploaded(program: str, name: str, root: Path = ROOT) -> None:
    if not re.fullmatch(r"(yours|golden|gap)-[a-z0-9-]{1,40}", name):
        raise ValueError("Only test data you uploaded can be removed.")
    d = set_dir(program, name, root)
    if d.exists():
        shutil.rmtree(d)


def describe_sets(program: str, root: Path = ROOT) -> list[dict]:
    out = []
    for name in set_names(program, root):
        _, result, meta = load_set(program, name, root)
        out.append({"set": name, "label": meta["label"], "records": meta.get("records", 0), "console_lines": meta.get("console_lines", 0),
                    "removable": name.startswith(("yours-", "golden-", "gap-")),
                    "gap": name.startswith("gap-"), "golden": bool(meta.get("golden")), "cobol_agrees": meta.get("cobol_agrees"), "cobol_differences": meta.get("cobol_differences", 0),
                    "filled_from_cobol": meta.get("filled_from_cobol", []),
                    "cobol_error": meta.get("error")})
    return out
