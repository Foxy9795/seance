"""Batch jobs: read JCL, run every step on the real COBOL and on the Python, compare what the job leaves behind.

A job is a folder legacy/<job>/<job>.jcl whose steps run programs from the workspace (EXEC PGM=NAME, matched by
PROGRAM-ID or folder name) or one of the standard utilities. DD statements map data sets to the DD names the
programs ASSIGN to. Both runs go through the same job runner; only the step runner differs (compiled COBOL with
DD_ variables, or the translated Python with the same files). What is compared: every data set that exists when
the job ends, each step's SYSOUT, and each step's return code.

Supported JCL: JOB, EXEC PGM= with COND=, IF/THEN/ELSE/ENDIF on RC and step.RC, DD with DSN=, DISP=, DCB=(LRECL=),
LRECL=, SYSOUT=, DUMMY, DD * / DD DATA in-stream data, concatenation, temporary &&data sets, // comments.
Utilities: IEFBR14, IEBGENER, SORT/DFSORT/ICEMAN (SORT FIELDS=, FIELDS=COPY, INCLUDE/OMIT COND=, SUM FIELDS=NONE).
The utilities run as the same Python code for both sides: they are plumbing between COBOL steps, not code under test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .model import ROOT

UTILITIES = {"IEFBR14", "IEBGENER", "SORT", "DFSORT", "ICEMAN", "SYNCSORT"}
SYSOUT = "SYSOUT"


class JclError(ValueError):
    pass


@dataclass
class DD:
    name: str
    dsn: str | None = None
    disp: tuple = ("NEW", "KEEP", "KEEP")
    sysout: bool = False
    dummy: bool = False
    inline: list[str] | None = None
    lrecl: int | None = None
    concat: list["DD"] = field(default_factory=list)
    line: int = 0


@dataclass
class Step:
    name: str
    pgm: str
    dds: dict[str, DD] = field(default_factory=dict)
    cond: list[tuple[int, str, str | None]] = field(default_factory=list)
    when: list[tuple[str, bool]] = field(default_factory=list)  # IF expressions that must hold (expr, wanted)
    line: int = 0
    parm: str | None = None


@dataclass
class Job:
    name: str
    path: Path
    steps: list[Step]
    notes: list[str] = field(default_factory=list)

    def programs(self) -> list[str]:
        return sorted({s.pgm for s in self.steps if s.pgm not in UTILITIES})


# ---------------------------------------------------------------- parsing

def _split(text: str) -> list[str]:
    out, depth, quote, cur = [], 0, False, ""
    for ch in text:
        if ch == "'":
            quote = not quote
        if not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(cur)
                cur = ""
                continue
        cur += ch
    if cur:
        out.append(cur)
    return [x.strip() for x in out]


def _unparen(v: str) -> list[str]:
    v = v.strip()
    if v.startswith("(") and v.endswith(")"):
        return _split(v[1:-1])
    return [v]


def _operands(field_text: str) -> str:
    """The operand field ends at the first blank outside quotes; what follows is a comment."""
    quote = False
    for i, ch in enumerate(field_text):
        if ch == "'":
            quote = not quote
        elif ch == " " and not quote:
            return field_text[:i]
    return field_text


def parse(text: str, path: Path | None = None) -> Job:
    raw = text.splitlines()
    stmts: list[tuple[int, str, str, str]] = []  # line, name, op, operands
    i = 0
    pending_inline: DD | None = None
    inline_target: list[str] | None = None
    while i < len(raw):
        line = raw[i].rstrip("\r")
        no = i + 1
        i += 1
        if inline_target is not None:
            if line.startswith("/*") or (line.startswith("//") and not line.startswith("//*")):
                inline_target = None
                if line.startswith("/*"):
                    continue
            else:
                inline_target.append(line[:80].rstrip())
                continue
        if not line.strip() or line.startswith("//*") or line.startswith("/*"):
            continue
        if not line.startswith("//"):
            raise JclError(f"line {no}: a JCL statement must start with //")
        body = line[2:72] if len(line) > 72 else line[2:]
        if not body.strip():
            continue  # the null statement ends the job
        name = ""
        if body[0] != " ":
            name, _, body = body.partition(" ")
        parts = body.strip().split(None, 1)
        op = parts[0].upper() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        operands = _operands(rest.strip()) if op not in ("IF", "ELSE", "ENDIF") else rest.strip()
        while operands.endswith(",") and i < len(raw) and raw[i].startswith("//") and not raw[i].startswith("//*"):
            cont = raw[i][2:72].strip()
            i += 1
            operands += _operands(cont)
        stmts.append((no, name.upper(), op, operands))
        if op == "DD" and re.match(r"^(\*|DATA)(,|$)", operands.upper()):
            inline_target = []
            stmts[-1] = (no, name.upper(), op, operands + "\x00INLINE")
            stmts.append((no, "", "\x00DATA", inline_target))  # type: ignore[arg-type]

    job = Job(path.stem if path else "job", path or Path("job.jcl"), [])
    conds: list[tuple[str, bool]] = []
    current: Step | None = None
    last_dd: DD | None = None
    for no, name, op, operands in stmts:
        if op == "\x00DATA":
            if last_dd is not None:
                last_dd.inline = operands  # type: ignore[assignment]
            continue
        if op == "JOB":
            job.name = name or job.name
        elif op == "IF":
            m = re.match(r"^(.*?)\s*THEN\b", operands, re.I)
            if not m:
                raise JclError(f"line {no}: IF needs THEN")
            conds.append((m.group(1).strip(), True))
        elif op == "ELSE":
            if not conds:
                raise JclError(f"line {no}: ELSE without IF")
            expr, _ = conds[-1]
            conds[-1] = (expr, False)
        elif op == "ENDIF":
            if not conds:
                raise JclError(f"line {no}: ENDIF without IF")
            conds.pop()
        elif op == "EXEC":
            ops = _split(operands)
            kv = {}
            for o in ops:
                k, eq, v = o.partition("=")
                if eq:
                    kv[k.upper()] = v
                else:
                    kv.setdefault("PROC", o)
            if "PGM" not in kv:
                raise JclError(f"line {no}: EXEC of a procedure ({kv.get('PROC')}) is not supported yet; use EXEC PGM=")
            current = Step(name or f"STEP{len(job.steps) + 1}", kv["PGM"].upper(), line=no, when=list(conds))
            if "COND" in kv:
                items = _unparen(kv["COND"])
                groups = [items] if items and not items[0].startswith("(") else [_unparen(x) for x in items]
                for g in groups:
                    if g and g[0].upper() in ("EVEN", "ONLY"):
                        job.notes.append(f"line {no}: COND={g[0]} (abend handling) is ignored; Séance steps do not abend.")
                        continue
                    current.cond.append((int(g[0]), g[1].upper(), g[2].upper() if len(g) > 2 else None))
            if "PARM" in kv:
                current.parm = kv["PARM"].strip("'")
                job.notes.append(f"line {no}: PARM= is not passed to the program yet.")
            job.steps.append(current)
            last_dd = None
        elif op == "DD":
            if current is None:
                raise JclError(f"line {no}: DD before any EXEC")
            inline = operands.endswith("\x00INLINE")
            operands = operands.replace("\x00INLINE", "")
            dd = DD(name or (last_dd.name if last_dd else ""), line=no)
            for o in _split(operands):
                k, eq, v = o.partition("=")
                k = k.upper()
                if not eq:
                    if k == "DUMMY":
                        dd.dummy = True
                    continue
                if k in ("DSN", "DSNAME"):
                    dd.dsn = v.upper()
                elif k == "DISP":
                    d = [x.upper() for x in _unparen(v)] + [""] * 3
                    status = d[0] or "NEW"
                    normal = d[1] or ("PASS" if (dd.dsn or "").startswith("&&") else "KEEP")
                    dd.disp = (status, normal, d[2] or normal)
                elif k == "SYSOUT":
                    dd.sysout = True
                elif k == "LRECL":
                    dd.lrecl = int(v)
                elif k == "DCB":
                    m = re.search(r"LRECL=(\d+)", v.upper())
                    if m:
                        dd.lrecl = int(m.group(1))
            if inline:
                dd.inline = []
            if not name and last_dd is not None:  # a concatenated data set
                last_dd.concat.append(dd)
                continue
            current.dds[dd.name] = dd
            last_dd = dd
    if not job.steps:
        raise JclError("the job has no EXEC steps")
    return job


def load_job(name: str, root: Path = ROOT) -> Job:
    path = root / "legacy" / name / f"{name}.jcl"
    job = parse(path.read_text(encoding="utf-8", errors="replace"), path)
    job.name = name
    return job


# ---------------------------------------------------------------- conditions

_OPS = {"GT": ">", "GE": ">=", "LT": "<", "LE": "<=", "EQ": "==", "NE": "!=", ">": ">", "<": "<", "=": "==", ">=": ">=", "<=": "<=",
        "¬=": "!=", "^=": "!="}


def _cmp(a: int, op: str, b: int) -> bool:
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "==": a == b, "!=": a != b}[_OPS[op.upper()]]


def bypassed_by_cond(step: Step, rcs: dict[str, int]) -> bool:
    """COND=(code,op[,step]): skip the step when 'code op RC' holds for that step (or any earlier step)."""
    for code, op, target in step.cond:
        pool = [rcs[target]] if target and target in rcs else ([] if target else list(rcs.values()))
        if any(_cmp(code, op, rc) for rc in pool):
            return True
    return False


def eval_if(expr: str, rcs: dict[str, int]) -> bool:
    text = expr.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    tokens = re.findall(r"[A-Z0-9#@$]+(?:\.[A-Z0-9#@$]+)*\.RC|\bRC\b|¬=|\^=|>=|<=|[<>=()&|]|\b(?:AND|OR|NOT|GT|GE|LT|LE|EQ|NE)\b|\d+", text.upper())
    py = []
    for t in tokens:
        if t.endswith(".RC") and t != "RC":
            py.append(str(rcs.get(t.split(".")[-2], 0)))
        elif t == "RC":
            py.append(str(max(rcs.values(), default=0)))
        elif t in ("AND", "&"):
            py.append(" and ")
        elif t in ("OR", "|"):
            py.append(" or ")
        elif t == "NOT":
            py.append(" not ")
        elif t in _OPS:
            py.append(_OPS[t])
        else:
            py.append(t)
    try:
        return bool(eval("".join(py), {"__builtins__": {}}, {}))  # only digits, comparisons and and/or/not reach here
    except Exception as exc:
        raise JclError(f"cannot evaluate IF ({expr})") from exc


def should_run(step: Step, rcs: dict[str, int]) -> bool:
    if bypassed_by_cond(step, rcs):
        return False
    return all(eval_if(expr, rcs) == wanted for expr, wanted in step.when)


# ---------------------------------------------------------------- data sets and utilities

@dataclass
class DataSet:
    data: bytes
    lrecl: int | None = None  # fixed-length records of this size; None: text lines

    def records(self) -> list[bytes]:
        if self.lrecl is None:
            rows = self.data.replace(b"\r\n", b"\n").split(b"\n")
            return rows[:-1] if rows and rows[-1] == b"" else rows
        return [self.data[i:i + self.lrecl] for i in range(0, len(self.data), self.lrecl)]

    @staticmethod
    def of(records: list[bytes], lrecl: int | None) -> "DataSet":
        if lrecl is None:
            return DataSet(b"".join(r.rstrip(b" ") + b"\n" for r in records), None)
        return DataSet(b"".join(r[:lrecl].ljust(lrecl, b" ") for r in records), lrecl)


def _sort_key_value(rec: bytes, start: int, length: int, fmt: str):
    raw = rec[start - 1:start - 1 + length]
    if fmt == "ZD":
        text = raw.decode("latin-1")
        neg = text[-1:] in "pqrstuvwxy}" or text[-1:] == "-"
        digits = "".join(c if c.isdigit() else str("pqrstuvwxy".index(c)) if c in "pqrstuvwxy" else "0" for c in text if c not in "+-")
        n = int(digits or "0")
        return -n if neg else n
    if fmt == "PD":
        h = raw.hex()
        n = int("".join(c if c.isdigit() else "0" for c in h[:-1]) or "0")
        return -n if h[-1:] in ("d", "b") else n
    if fmt in ("BI", "FI"):
        return int.from_bytes(raw, "big", signed=fmt == "FI")
    return raw  # CH, AC: byte order


def _cond_value(tok: str) -> bytes | int:
    m = re.match(r"^C'(.*)'$", tok, re.S)
    if m:
        return m.group(1).encode("latin-1")
    m = re.match(r"^X'([0-9A-F]*)'$", tok, re.I)
    if m:
        return bytes.fromhex(m.group(1))
    return int(tok)


def _control(lines: list[str]) -> dict[str, str]:
    """DFSORT control statements: KEYWORD operands, with continuation by a trailing comma."""
    text = " ".join(l[:71].strip() for l in lines if l.strip() and not l.lstrip().startswith("*"))
    out = {}
    for m in re.finditer(r"\b(SORT|MERGE|INCLUDE|OMIT|SUM|OPTION|OUTREC|INREC|RECORD)\s+(\S+(?:\s*,\s*\S+)*)", text, re.I):
        out[m.group(1).upper()] = m.group(2).replace(" ", "")
    return out


def _filter(records: list[bytes], spec: str) -> list[bytes]:
    m = re.match(r"COND=\((.*)\)(?:,FORMAT=(\w+))?$", spec, re.I)
    if not m:
        raise JclError(f"cannot read INCLUDE/OMIT {spec}")
    fmt_all = (m.group(2) or "CH").upper()
    parts = _split(m.group(1))
    tests, joins, i = [], [], 0
    while i < len(parts):
        if parts[i].upper() in ("AND", "OR", "&", "|"):
            joins.append("and" if parts[i].upper() in ("AND", "&") else "or")
            i += 1
            continue
        if i + 3 < len(parts) and parts[i + 2].upper() in _OPS:
            start, length, op, val, fmt = int(parts[i]), int(parts[i + 1]), parts[i + 2], parts[i + 3], fmt_all
            i += 4
        else:
            start, length, fmt, op, val = int(parts[i]), int(parts[i + 1]), parts[i + 2].upper(), parts[i + 3], parts[i + 4]
            i += 5
        tests.append((start, length, fmt, op, val))

    def ok(rec):
        results = []
        for start, length, fmt, op, val in tests:
            a = _sort_key_value(rec, start, length, fmt)
            b = _cond_value(val)
            if isinstance(a, bytes) and isinstance(b, bytes):
                b = b[:length].ljust(length, b" ")
            elif isinstance(a, bytes):
                b = str(b).encode().rjust(length, b"0")
            results.append({">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "==": a == b, "!=": a != b}[_OPS[op.upper()]])
        value = results[0] if results else True
        for j, r in zip(joins, results[1:]):
            value = (value and r) if j == "and" else (value or r)
        return value
    return [r for r in records if ok(r)]


def run_utility(step: Step, inputs: dict[str, DataSet]) -> tuple[dict[str, DataSet], str, int]:
    """IEFBR14, IEBGENER and SORT. Returns (outputs by DD name, SYSOUT text, return code)."""
    pgm = step.pgm
    if pgm == "IEFBR14":
        return {}, "", 0
    if pgm == "IEBGENER":
        src = inputs.get("SYSUT1")
        if src is None:
            return {}, "IEBGENER: SYSUT1 is missing\n", 12
        out_dd = step.dds.get("SYSUT2")
        lrecl = (out_dd.lrecl if out_dd and out_dd.lrecl else src.lrecl)
        return {"SYSUT2": DataSet.of(src.records(), lrecl)}, "", 0
    # SORT family
    ctl = _control((step.dds.get("SYSIN").inline or []) if "SYSIN" in step.dds and step.dds["SYSIN"].inline is not None else [])
    src = inputs.get("SORTIN")
    if src is None:
        ins = [inputs[k] for k in sorted(inputs) if k.startswith("SORTIN")]
        if not ins:
            return {}, "SORT: SORTIN is missing\n", 16
        src = DataSet(b"".join(d.data for d in ins), ins[0].lrecl)
    records = src.records()
    if "INCLUDE" in ctl:
        records = _filter(records, ctl["INCLUDE"])
    if "OMIT" in ctl:
        keep = set(map(id, _filter(records, ctl["OMIT"])))
        records = [r for r in records if id(r) not in keep]
    spec = ctl.get("SORT") or ctl.get("MERGE") or "FIELDS=COPY"
    m = re.match(r"FIELDS=(\(.*\)|COPY)(?:,FORMAT=(\w+))?", spec, re.I)
    if not m:
        raise JclError(f"cannot read SORT {spec}")
    if m.group(1).upper() != "COPY":
        parts = _split(m.group(1)[1:-1])
        fmt_all = (m.group(2) or "CH").upper()
        keys, i = [], 0
        while i < len(parts):
            start, length = int(parts[i]), int(parts[i + 1])
            if i + 3 < len(parts) + 1 and i + 2 < len(parts) and parts[i + 2].upper() in ("A", "D"):
                fmt, order, i = fmt_all, parts[i + 2].upper(), i + 3
            else:
                fmt, order, i = parts[i + 2].upper(), parts[i + 3].upper(), i + 4
            keys.append((start, length, fmt, order == "A"))
        from functools import cmp_to_key

        def cmp(a, b):
            for start, length, fmt, asc in keys:
                x, y = _sort_key_value(a, start, length, fmt), _sort_key_value(b, start, length, fmt)
                if x != y:
                    return (-1 if x < y else 1) * (1 if asc else -1)
            return 0
        records = sorted(records, key=cmp_to_key(cmp))  # DFSORT keeps equal keys in input order with EQUALS
        if ctl.get("SUM", "").upper() == "FIELDS=NONE":
            out, last = [], None
            for r in records:
                k = tuple(_sort_key_value(r, s, l, f) for s, l, f, _ in keys)
                if k != last:
                    out.append(r)
                    last = k
            records = out
    out_dd = step.dds.get("SORTOUT")
    lrecl = out_dd.lrecl if out_dd and out_dd.lrecl else src.lrecl
    return {"SORTOUT": DataSet.of(records, lrecl)}, f"SORT: {len(records)} records written\n", 0


# ---------------------------------------------------------------- running a job

@dataclass
class JobResult:
    datasets: dict[str, bytes] = field(default_factory=dict)  # every data set left when the job ends
    sysout: dict[str, str] = field(default_factory=dict)  # step -> what it DISPLAYed (and utility messages)
    rcs: dict[str, int | None] = field(default_factory=dict)  # step -> return code; None when bypassed
    error: str | None = None
    lrecl: dict[str, int | None] = field(default_factory=dict)  # data set -> record length (None: text lines)


def _input_for(dd: DD, datasets: dict[str, DataSet]) -> DataSet | None:
    parts = [dd] + dd.concat
    chunks, lrecl = [], None
    for p in parts:
        if p.dummy:
            chunks.append(DataSet(b"", p.lrecl))
        elif p.inline is not None:
            chunks.append(DataSet.of([l.encode("latin-1") for l in p.inline], p.lrecl or None))
        elif p.dsn and p.dsn in datasets:
            chunks.append(datasets[p.dsn])
        elif p.dsn and p.disp[0] in ("OLD", "SHR", "MOD"):
            continue
    if not chunks:
        return None
    lrecl = chunks[0].lrecl
    return DataSet(b"".join(c.data for c in chunks), lrecl)


def run_job(job: Job, initial: dict[str, DataSet], run_program) -> JobResult:
    """run_program(step, files: {ddname: bytes}, stdin: [lines]) -> (outputs {ddname: bytes}, stdout, rc, error, sizes).

    sizes: {ddname: record length or None for text lines}, describing the data sets the program wrote.
    """
    datasets: dict[str, DataSet] = dict(initial)
    result = JobResult()
    rcs: dict[str, int] = {}
    for step in job.steps:
        if not should_run(step, rcs):
            result.rcs[step.name] = None
            continue
        inputs = {}
        for name, dd in step.dds.items():
            if name == "SYSIN" and step.pgm not in UTILITIES:
                continue
            ds = _input_for(dd, datasets)
            if ds is not None:
                inputs[name] = ds
        sysin = step.dds.get("SYSIN")
        stdin = list(sysin.inline) if sysin is not None and sysin.inline is not None and step.pgm not in UTILITIES else []
        if sysin is not None and sysin.inline is None and sysin.dsn in datasets and step.pgm not in UTILITIES:
            stdin = [r.decode("latin-1").rstrip() for r in datasets[sysin.dsn].records()]
        if step.pgm in UTILITIES:
            outs, text, rc = run_utility(step, inputs)
            error = None
        else:
            raw, text, rc, error, sizes = run_program(step, {k: v.data for k, v in inputs.items()}, stdin)
            outs = {k: DataSet(v, sizes.get(k)) for k, v in raw.items()}
        result.sysout[step.name] = text
        rcs[step.name] = result.rcs[step.name] = rc
        if error:
            result.error = f"{step.name}: {error}"
        for name, ds in outs.items():
            dd = step.dds.get(name)
            if dd is not None and dd.sysout:  # a file written to SYSOUT=* is printed output: it joins the step's SYSOUT
                result.sysout[step.name] += ds.data.decode("latin-1").replace("\r\n", "\n")
                continue
            if dd is None or dd.dummy:
                continue
            if dd.dsn is None:
                continue
            if dd.disp[0] == "MOD" and dd.dsn in datasets and not ds.data.startswith(datasets[dd.dsn].data):
                ds = DataSet(datasets[dd.dsn].data + ds.data, ds.lrecl)
            datasets[dd.dsn] = ds
        for name, dd in step.dds.items():  # DISP=(...,DELETE)
            if dd.dsn and dd.disp[1] == "DELETE" and dd.dsn in datasets:
                del datasets[dd.dsn]
        if error:
            break
    result.datasets = {k: v.data for k, v in datasets.items() if not k.startswith("&&")}
    result.lrecl = {k: v.lrecl for k, v in datasets.items() if not k.startswith("&&")}
    return result


# ---------------------------------------------------------------- what a job needs as input

def initial_datasets(job: Job) -> list[tuple[str, Step, DD]]:
    """Data sets a step reads before any step creates them: these are the job's inputs."""
    made: set[str] = set()
    needed: list[tuple[str, Step, DD]] = []
    for step in job.steps:
        for name, dd in step.dds.items():
            for part in [dd] + dd.concat:
                if part.dsn and part.disp[0] in ("OLD", "SHR", "MOD") and part.dsn not in made and part.dsn not in [n for n, _, _ in needed]:
                    needed.append((part.dsn, step, part))
        for dd in step.dds.values():
            if dd.dsn:
                made.add(dd.dsn)
    return needed
