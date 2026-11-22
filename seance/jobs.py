"""Check a whole batch job: the COBOL steps against the Python steps, with the job's data sets flowing between them."""

from __future__ import annotations

import json
import random
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .cases import (ENC, Case, Diff, Result, _units, apply_links, edge_rows, key_links, file_records, pack_file, random_rows, run_cobol, run_python, show)
from .jcl import UTILITIES, DataSet, Job, JobResult, initial_datasets, load_job, run_job
from .model import ROOT, FileDef

SET_LABELS = {"edges": "Edge Cases (zero, smallest and largest values, plus values the code tests for)", "random": "Random Records"}


def job_names(root: Path = ROOT) -> list[str]:
    base = root / "legacy"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / f"{p.name}.jcl").exists() and not (p / f"{p.name}.cbl").exists())


def resolve(pgm: str, root: Path = ROOT) -> str | None:
    """The workspace program an EXEC PGM= names: by PROGRAM-ID, else by folder name."""
    from .programs import program_names
    from .recorder import get_model

    names = program_names(root)
    for n in names:
        try:
            if get_model(n, root).program_id == pgm:
                return n
        except Exception:
            continue
    low = pgm.lower()
    return low if low in names else None


def check_job(job: Job, root: Path = ROOT) -> list[str]:
    problems = []
    for step in job.steps:
        if step.pgm not in UTILITIES and resolve(step.pgm, root) is None:
            problems.append(f"step {step.name} runs {step.pgm}, which is not in the workspace. Add that program first.")
    return problems


def _file_for(step, dd_name: str, root: Path) -> FileDef | None:
    from .recorder import get_model

    if step.pgm in UTILITIES:
        return None
    prog = resolve(step.pgm, root)
    if prog is None:
        return None
    return next((f for f in get_model(prog, root).all_files if f.assign == dd_name), None)


def _lrecl(f: FileDef | None, dd) -> int | None:
    if dd is not None and dd.lrecl:
        return dd.lrecl
    if f is None:
        return 80
    return None if f.organization == "line" else f.size + (9 if f.organization == "relative" else 0)


# ---------------------------------------------------------------- step runners

class Runner:
    """Runs one program step. kind 'cobol' uses the compiled programs; 'python' imports the translations fresh."""

    def __init__(self, kind: str, root: Path = ROOT, impls: dict[str, str] | None = None):
        self.kind, self.root, self.impls = kind, root, impls or {}
        self.modules: dict[str, object] = {}

    def __call__(self, step, files: dict[str, bytes], stdin: list[str]):
        from .recorder import compile_legacy, get_model

        prog = resolve(step.pgm, self.root)
        model = get_model(prog, self.root)
        case = Case({a: d for a, d in files.items() if any(f.assign == a for f in model.all_files)}, stdin)
        if self.kind == "cobol":
            res = run_cobol(compile_legacy(prog, self.root), model, case, 60)
        else:
            if prog not in self.modules:
                from .verify import load_implementation

                self.modules[prog] = load_implementation(self.impls.get(prog, f"migrated.{prog}"))
            res = run_python(self.modules[prog], case)
        sizes = {f.assign: _lrecl(f, step.dds.get(f.assign)) for f in model.all_files}
        return res.outputs, res.stdout, res.return_code, res.error, sizes


# ---------------------------------------------------------------- cases

@dataclass
class JobCase:
    datasets: dict[str, bytes] = field(default_factory=dict)
    lrecl: dict[str, int | None] = field(default_factory=dict)
    records: dict[str, list[bytes]] = field(default_factory=dict)


def generated(job: Job, root: Path = ROOT, count: int = 200, seed: int = 1031) -> dict[str, JobCase]:
    from .hints import value_hints
    from .recorder import get_model

    rng = random.Random(seed)
    sets = {"edges": JobCase(), "random": JobCase()}
    plan = []
    for dsn, step, dd in initial_datasets(job):
        f = _file_for(step, dd.name, root)
        reader = step
        if f is None and step.pgm in UTILITIES:  # read by SORT or IEBGENER: use the layout of the program it feeds
            out_dd = step.dds.get("SORTOUT") or step.dds.get("SYSUT2")
            for later in job.steps[job.steps.index(step) + 1:]:
                hit = next((d for d in later.dds.values() if out_dd is not None and d.dsn and d.dsn == out_dd.dsn), None)
                if hit is not None:
                    f, reader = _file_for(later, hit.name, root), later
                    break
        lrecl = _lrecl(f, dd)
        if f is not None and f.record is not None:
            prog = resolve(reader.pgm, root)
            hints = value_hints(get_model(prog, root))
            rows = {"edges": edge_rows(f.record, hints), "random": random_rows(f.record, count, rng, hints)}
            plan.append((dsn, f, lrecl, prog, rows))
        else:  # read only by a utility: text records of the DD's length
            size = lrecl or 80
            for name, n in (("edges", 6), ("random", count)):
                recs = [(rng.choice("ABCDEFGH") + f"{rng.randrange(10**6):06d}" + " ITEM").encode().ljust(size)[:size] for _ in range(n)]
                sets[name].records[dsn] = recs
                sets[name].datasets[dsn] = b"".join(recs)
                sets[name].lrecl[dsn] = size
    # transactions name keys the generated master really has, when one program reads both (see cases.key_links)
    for prog in {pr for _, _, _, pr, _ in plan}:
        links = key_links(get_model(prog, root))
        for name in ("edges", "random"):
            by_file = {f.name: rows[name] for _, f, _, pr, rows in plan if pr == prog}
            apply_links(links, by_file, random.Random(seed + len(name)))
    for dsn, f, lrecl, _, rows in plan:
        for name, rs in rows.items():
            recs = file_records(f, rs)
            sets[name].records[dsn] = recs
            sets[name].datasets[dsn] = pack_file(f, recs)
            sets[name].lrecl[dsn] = lrecl
    return sets


def execute(job: Job, case: JobCase, runner) -> JobResult:
    initial = {k: DataSet(v, case.lrecl.get(k)) for k, v in case.datasets.items()}
    try:
        return run_job(job, initial, runner)
    except Exception as exc:  # a crash in the harness is a result, not a lost check
        return JobResult(error=f"{type(exc).__name__}: {exc}")


def compare_jobs(job: Job, case: JobCase, expected: JobResult, actual: JobResult, root: Path = ROOT) -> tuple[list[Diff], int]:
    diffs: list[Diff] = []
    units = 0
    if (expected.error is None) != (actual.error is None):
        diffs.append(Diff("run", -1, expected.error or "finished normally", actual.error or "finished normally"))
    for step in job.steps:
        e, a = expected.rcs.get(step.name, "not run"), actual.rcs.get(step.name, "not run")
        units += 1
        if e != a:
            diffs.append(Diff(f"{step.name} return code", -1, "bypassed" if e is None else str(e), "bypassed" if a is None else str(a)))
        el, al = (expected.sysout.get(step.name) or "").splitlines(), (actual.sysout.get(step.name) or "").splitlines()
        units += max(len(el), len(al))
        for i in range(max(len(el), len(al))):
            x = el[i] if i < len(el) else None
            y = al[i] if i < len(al) else None
            if x != y:
                diffs.append(Diff(f"{step.name} SYSOUT", i, x if x is not None else "(no line)", y if y is not None else "(no line)"))
    for dsn in sorted(set(expected.datasets) | set(actual.datasets)):
        if dsn not in expected.datasets or dsn not in actual.datasets:
            diffs.append(Diff(dsn, -1, "exists" if dsn in expected.datasets else "does not exist", "exists" if dsn in actual.datasets else "does not exist"))
            continue
        size = expected.lrecl.get(dsn) or actual.lrecl.get(dsn)

        def split(data: bytes) -> list[bytes]:
            if b"\n" in data or not size:
                return _units(None, data)
            return [data[i:i + size] for i in range(0, len(data), size)]
        e_units, a_units = split(expected.datasets[dsn]), split(actual.datasets[dsn])
        units += max(len(e_units), len(a_units))
        for i in range(max(len(e_units), len(a_units))):
            x = e_units[i] if i < len(e_units) else None
            y = a_units[i] if i < len(a_units) else None
            if x != y:
                diffs.append(Diff(dsn, i, show(x) if x is not None else "(no line)", show(y) if y is not None else "(no line)"))
    return diffs, units


# ---------------------------------------------------------------- saved sets


def save(job: str, name: str, case: JobCase, result: JobResult, label: str, root: Path = ROOT) -> None:
    d = root / "fixtures" / job / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    meta = {"label": label, "inputs": {}, "lrecl": case.lrecl, "outputs": {}, "sysout": result.sysout, "rcs": result.rcs,
            "out_lrecl": result.lrecl,
            "error": result.error, "records": sum(len(v) for v in case.records.values())}
    for i, (dsn, data) in enumerate(sorted(case.datasets.items())):
        (d / f"in{i}.dat").write_bytes(data)
        meta["inputs"][dsn] = f"in{i}.dat"
    for i, (dsn, data) in enumerate(sorted(result.datasets.items())):
        (d / f"out{i}.dat").write_bytes(data)
        meta["outputs"][dsn] = f"out{i}.dat"
    (d / "set.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load(job: str, name: str, root: Path = ROOT) -> tuple[JobCase, JobResult, dict]:
    d = root / "fixtures" / job / name
    meta = json.loads((d / "set.json").read_text(encoding="utf-8"))
    case = JobCase({k: (d / v).read_bytes() for k, v in meta["inputs"].items()}, meta.get("lrecl", {}))
    result = JobResult({k: (d / v).read_bytes() for k, v in meta["outputs"].items()}, meta["sysout"], meta["rcs"], meta.get("error"),
                       meta.get("out_lrecl", {}))
    return case, result, meta


def set_names(job: str, root: Path = ROOT) -> list[str]:
    base = root / "fixtures" / job
    if not base.exists():
        return []
    order = {"edges": 0, "random": 1}
    return sorted((p.name for p in base.iterdir() if (p / "set.json").exists()), key=lambda n: (order.get(n, 2), n))


def record(job_name: str, root: Path = ROOT) -> dict[str, int]:
    job = load_job(job_name, root)
    problems = check_job(job, root)
    if problems:
        raise ValueError(" ".join(problems))
    base = root / "fixtures" / job_name
    if base.exists():
        for p in base.iterdir():
            if p.is_dir() and not p.name.startswith(("yours-", "gap-")):
                shutil.rmtree(p)
    counts = {}
    for name, case in generated(job, root).items():
        res = execute(job, case, Runner("cobol", root))
        save(job_name, name, case, res, SET_LABELS[name], root)
        counts[name] = sum(len(v) for v in case.records.values())
    return counts


def describe(job_name: str, root: Path = ROOT) -> dict:
    job = load_job(job_name, root)
    steps = []
    for s in job.steps:
        dds = []
        for name, dd in s.dds.items():
            what = "SYSOUT" if dd.sysout else "DUMMY" if dd.dummy else "in-stream data" if dd.inline is not None else (dd.dsn or "")
            dds.append({"dd": name, "what": what, "disp": ",".join(x for x in dd.disp if x) if dd.dsn else "", "lines": len(dd.inline or [])})
        steps.append({"step": s.name, "pgm": s.pgm, "program": resolve(s.pgm, root) if s.pgm not in UTILITIES else None,
                      "utility": s.pgm in UTILITIES, "cond": [list(c) for c in s.cond], "when": [list(w) for w in s.when], "dds": dds, "line": s.line})
    return {"name": job_name, "job": job.name, "steps": steps, "notes": job.notes, "inputs": [d for d, _, _ in initial_datasets(job)],
            "problems": check_job(job, root)}


# ---------------------------------------------------------------- the check

def _shrink(job: Job, case: JobCase, root: Path, impls: dict, budget: int = 24) -> tuple[JobCase, list[Diff]]:
    """Halve each input data set while the job still differs."""
    def fails(c: JobCase):
        e = execute(job, c, Runner("cobol", root))
        a = execute(job, c, Runner("python", root, impls))
        return compare_jobs(job, c, e, a, root)[0]

    best = fails(case)
    runs = 1
    for dsn in list(case.records):
        while runs < budget and len(case.records[dsn]) > 1:
            half = case.records[dsn][: len(case.records[dsn]) // 2]
            trial = JobCase(dict(case.datasets), dict(case.lrecl), dict(case.records))
            trial.records[dsn] = half
            size = case.lrecl.get(dsn)
            trial.datasets[dsn] = DataSet.of(half, size).data if size else b"".join(r.rstrip(b" ") + b"\n" for r in half)
            found = fails(trial)
            runs += 1
            if not found:
                break
            case, best = trial, found
    return case, best


def verify_job(job_name: str, rounds: int = 10, root: Path = ROOT, impls: dict | None = None):
    from .verify import Report

    impls = impls or {}
    job = load_job(job_name, root)
    report = Report(job_name, f"jobs.{job_name}")
    for name in set_names(job_name, root):
        case, expected, meta = load(job_name, name, root)
        actual = execute(job, case, Runner("python", root, impls))
        found, units = compare_jobs(job, case, expected, actual, root)
        report.sets.append({"name": name, "label": meta["label"], "records": meta.get("records", 0), "console_lines": 0,
                            "compared": units, "differing": len(found), "python_error": actual.error, "cobol_error": expected.error})
        for d in found[: max(0, 20 - len(report.diffs))]:
            report.diffs.append({"set": name, **d.to_dict()})
    if not report.sets:
        raise ValueError(f"No saved test sets for job {job_name!r}. Run: python -m seance record {job_name}")
    for k in range(rounds):
        case = generated(job, root, count=random.Random(k).randint(1, 25), seed=7000 + k)["random"]
        e = execute(job, case, Runner("cobol", root))
        a = execute(job, case, Runner("python", root, impls))
        report.random_runs += 1
        found, _ = compare_jobs(job, case, e, a, root)
        if found:
            small, diffs = _shrink(job, case, root, impls)
            report.random_failure = {"inputs": {d: [show(r) for r in rs] for d, rs in small.records.items()}, "stdin": [],
                                     "diffs": [x.to_dict() for x in diffs[:20]]}
            break
    for s in report.sets:
        if s["differing"]:
            report.review.append(f"{s['label']}: {s['differing']} of {s['compared']} compared items differ")
    for note in job.notes:
        report.review.append(note)
    return report


def job_programs(job_name: str, root: Path = ROOT) -> list[str]:
    job = load_job(job_name, root)
    return sorted({resolve(s.pgm, root) for s in job.steps if s.pgm not in UTILITIES} - {None})


def python_sha(job_name: str, root: Path = ROOT) -> str | None:
    """One hash over the Python of every program the job runs."""
    import hashlib

    h = hashlib.sha256()
    try:
        names = job_programs(job_name, root)
    except Exception:
        return None
    for name in names:
        p = root / "migrated" / f"{name}.py"
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def job_info(name: str, root: Path = ROOT) -> dict:
    from .programs import last_check

    from .programs import is_sample

    info = {"name": name, "kind": "job", "sample": is_sample(name, root), "kinds": ["jcl"], "title": name.replace("_", " ").title(),
            "implementations": [{"module": f"jobs.{name}", "label": "Job", "role": "job", "editable": False, "last_check": last_check(f"jobs.{name}", root)}],
            "files": [], "console_input": [], "calls": [], "unsupported": [], "notes": [], "format": "jcl", "error": None}
    try:
        d = describe(name, root)
        text = (root / "legacy" / name / f"{name}.jcl").read_text(encoding="utf-8", errors="replace")
        purpose = " ".join(l[3:].strip() for l in text.splitlines() if l.startswith("//*") and l[3:].strip())
        info.update({"program_id": d["job"].upper(), "purpose": purpose[:240], "steps": d["steps"], "inputs": d["inputs"],
                     "notes": d["notes"] + d["problems"], "io": f"{len(d['steps'])} steps, runs " + ", ".join(job_programs(name, root))})
        if d["problems"]:
            info["error"] = " ".join(d["problems"])
    except Exception as exc:
        info["error"] = str(exc)
    try:
        info["sets"] = [{"set": n, "label": load(name, n, root)[2]["label"], "records": load(name, n, root)[2].get("records", 0)} for n in set_names(name, root)]
    except Exception:
        info["sets"] = []
    return info


def create_job(name: str, jcl: str, root: Path = ROOT) -> dict:
    """Add a JCL job to the workspace and record what the real COBOL does for it. The programs it runs must already be
    in the workspace (they are found by PROGRAM-ID). Cleans up on failure."""
    from .jcl import JclError
    from .programs import MAX_SOURCE_BYTES, ProgramError, _rm, program_names, validate_name

    name = (name or "").strip() or _job_name(jcl)
    validate_name(name)
    if not jcl.strip():
        raise ProgramError("The JCL is empty.")
    if len(jcl.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ProgramError(f"The JCL is larger than {MAX_SOURCE_BYTES // 1000} KB.")
    if name in program_names(root) or (root / "legacy" / name).exists():
        raise ProgramError(f"A program or job named '{name}' already exists. Pick another name or delete it first.")
    folder = root / "legacy" / name
    try:
        folder.mkdir(parents=True)
        (folder / f"{name}.jcl").write_text(jcl.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
        try:
            job = load_job(name, root)
        except JclError as exc:
            raise ProgramError(f"Séance cannot read this JCL: {exc}") from exc
        problems = check_job(job, root)
        if problems:
            raise ProgramError("\n".join(problems))
        try:
            counts = record(name, root)
        except Exception as exc:
            raise ProgramError(f"The job could not be run on generated data:\n{exc}") from exc
    except Exception:
        _rm(folder)
        _rm(root / "fixtures" / name)
        raise
    return {"name": name, "sets": counts, "job": describe(name, root)}


def _job_name(jcl: str) -> str:
    import re

    m = re.match(r"//([A-Z0-9#@$]{1,8})\s+JOB\b", jcl.lstrip(), re.I)
    return (m.group(1).lower() if m else "job")
