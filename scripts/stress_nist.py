"""Translator stress test over the NIST COBOL-85 test suite (CCVS85): standard COBOL, module by module.

    python scripts/stress_nist.py --fetch          download newcob.val (3.4 MB) and build the module folders
    python scripts/stress_nist.py NC SM IF         translate and check the programs of those modules
    python scripts/stress_nist.py --report         write docs/STRESS_NIST.md from the saved results

The suite comes from GnuCOBOL's mirror on SourceForge and goes to build/corpora/nist (git-ignored); it is not part of
this repository. It is split the way GnuCOBOL's own test run splits it: EXEC85, the suite's own COBOL program, is
compiled with GnuCOBOL and fills in the implementor names (GnuCOBOL's tests/cobol85/EXEC85.conf.in), then each member
becomes a file. Each program is then put through Séance: the compiled COBOL is the judge, the Python must write the
same bytes. The suite's expected results are not used.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HOME = ROOT / "build" / "corpora" / "nist"
NEWCOB = HOME / "newcob.val"
RESULTS = ROOT / "build" / "stress" / "nist"
URL = "https://sourceforge.net/projects/gnucobol/files/nist/newcob.val.tar.gz/download"
CONF_URL = "https://raw.githubusercontent.com/OCamlPro/gnucobol/gnucobol-3.1.2/tests/cobol85/EXEC85.conf.in"
MODULES = ["NC", "SM", "IC", "SQ", "RL", "IX", "ST", "SG", "OB", "IF", "RW", "DB"]
RUN_SECONDS = 60
# GnuCOBOL's own run treats these as compile-only (they test that the compiler flags errors) or as needing a person
SKIP = {"NC401M", "RL301M", "RL401M", "IC401M", "IX301M", "IX401M", "SQ303M", "SQ401M", "ST301M", "RW301M", "RW302M", "DB205A",
        "OBNC1M", "NC302M", "NC114M"}
EXEC85_SUBS = {
    "002500": "           SELECT           POPULATION-FILE",
    "002700": '           "NEWCOB_VAL" ORGANIZATION LINE SEQUENTIAL.',
    "003000": '           "newcob.tmp" ORGANIZATION LINE SEQUENTIAL.',
    "003100": "",
    "003400": '           "unused".',
    "003700": '           "newcob.log".',
    "004000": '           "EXEC85.conf" ORGANIZATION LINE SEQUENTIAL.',
}


# ---------------------------------------------------------------- building the suite

def fetch() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    pack = HOME / "newcob.val.tar.gz"
    if not NEWCOB.exists():
        if not pack.exists():
            req = urllib.request.Request(URL, headers={"User-Agent": "Wget/1.21"})
            with urllib.request.urlopen(req, timeout=120) as r:
                pack.write_bytes(r.read())
        with tarfile.open(pack) as t:
            t.extract("newcob.val", HOME, filter="data")
    conf = HOME / "EXEC85.conf.in"
    if not conf.exists():
        with urllib.request.urlopen(CONF_URL, timeout=60) as r:
            conf.write_bytes(r.read())
    build_exec85()
    for m in MODULES:
        build_module(m)


def build_exec85() -> Path:
    from seance.recorder import cobc_path, cobol_env

    exe = HOME / ("EXEC85.exe" if os.name == "nt" else "EXEC85")
    if exe.exists():
        return exe
    lines = NEWCOB.read_text(encoding="latin-1").splitlines()
    head = next(i for i, x in enumerate(lines) if x.startswith("*HEADER"))
    end = next(i for i, x in enumerate(lines) if x.startswith("*END"))
    body = [EXEC85_SUBS.get(x[:6], x) for x in lines[head + 1:end]]
    src = HOME / "EXEC85.cob"
    src.write_text("\n".join(body) + "\n", encoding="latin-1")
    subprocess.run([cobc_path(), "-std=cobol85", "-debug", "-x", "-o", str(exe), str(src)], check=True, env=cobol_env(), cwd=HOME)
    return exe


def build_module(module: str) -> None:
    from seance.recorder import cobol_env

    out = HOME / module
    if (out / ".done").exists():
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / "EXEC85.conf").write_text(f"*SELECT-MODULE {module}\n" + (HOME / "EXEC85.conf.in").read_text(encoding="latin-1"), encoding="latin-1")
    env = {**cobol_env(), "NEWCOB_VAL": str(NEWCOB)}
    subprocess.run([str(build_exec85())], check=True, env=env, cwd=out, capture_output=True)
    expand(out / "newcob.tmp", out)
    (out / ".done").write_text("ok", encoding="utf-8")


def expand(tmp: Path, moddir: Path) -> None:
    """A port of GnuCOBOL's tests/cobol85/expand.pl: one file per member."""
    import re

    header = re.compile(r"^      \*HEADER,([^,]*),([^, ]*)(,([^,]*),([^, ]*))?")
    lines = tmp.read_text(encoding="latin-1").splitlines()
    i = 0
    module = moddir.name
    while i < len(lines):
        m = header.match(lines[i])
        i += 1
        if not m:
            continue
        kind, prog, subt, subr = m.group(1), m.group(2), m.group(4), m.group(5)
        target = None
        if subt == "SUBPRG":
            target = moddir / f"{subr}.SUB"
        elif subt == "SUBRTN":
            target = moddir / "lib" / f"{subr}.CBL"
        elif kind == "COBOL":
            target = moddir / f"{prog}.CBL"
        elif kind == "DATA*" and prog[:2] == module:
            target = moddir / f"{prog}.DAT"
        elif kind == "CLBRY":
            target = (HOME / "copyalt" / "ALTLB") if prog == "ALTL1" else (HOME / "copy" / prog)
            if target.exists():
                target = None
        body = []
        while i < len(lines) and not lines[i].startswith("      *END"):
            body.append(lines[i])
            i += 1
        i += 1
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(body) + "\n", encoding="latin-1")


# ---------------------------------------------------------------- running one program through Séance

def run_one(cob: Path, name: str, root: Path) -> dict:
    """Compile, translate, run both on the program's own input and compare. Never raises: every outcome is a result."""
    from seance.cases import Case, compare, run_cobol, run_python
    from seance.model import ModelError, load_model
    from seance.recorder import LegacyRuntimeError, compile_legacy
    from seance.translate import Unsupported, translate

    src = root / "legacy" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{name}.cbl").write_text(cob.read_text(encoding="latin-1"), encoding="latin-1")
    if name[:2].upper() == "SM":
        for c in (HOME / "copy").glob("*"):
            (src / c.name).write_text(c.read_text(encoding="latin-1"), encoding="latin-1")
        # COPY ALTLB IN "../copyalt" (SM207A): the second library sits beside the program's folder, as in the suite
        alt = root / "legacy" / "copyalt"
        alt.mkdir(parents=True, exist_ok=True)
        for c in (HOME / "copyalt").glob("*"):
            (alt / c.name).write_text(c.read_text(encoding="latin-1"), encoding="latin-1")
    for sub in (cob.parent / "lib").glob("*.CBL") if name[:2].upper() == "IC" else []:
        (src / sub.name.lower()).write_text(sub.read_text(encoding="latin-1"), encoding="latin-1")
    stdin = []
    dat = cob.with_suffix(".DAT")
    if dat.exists():
        stdin = dat.read_text(encoding="latin-1").splitlines()
    try:
        model = load_model(name, root)
    except ModelError as exc:
        return {"stage": "model", "why": str(exc).splitlines()[0][:200]}
    except Exception as exc:
        return {"stage": "model", "why": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        exe = compile_legacy(name, root)
    except LegacyRuntimeError as exc:
        return {"stage": "cobc", "why": (str(exc).strip().splitlines() or ["?"])[-1][:200]}
    except Exception as exc:
        return {"stage": "cobc", "why": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        tr = translate(name, root)
    except Unsupported as exc:
        return {"stage": "unsupported", "why": str(exc)[:240]}
    except Exception as exc:
        import traceback

        tb = traceback.extract_tb(exc.__traceback__)[-1]
        return {"stage": "crash", "why": f"{type(exc).__name__}: {exc} ({Path(tb.filename).name}:{tb.lineno})"[:240]}
    gaps = [{"line": g["line"], "text": g["text"][:80], "why": g["why"]} for g in tr.unsupported]
    ns: dict = {"__name__": f"nist_{name}", "__file__": str(root / "migrated" / f"{name}.py")}
    try:
        exec(compile(tr.code, ns["__file__"], "exec"), ns)
    except Exception as exc:
        return {"stage": "crash", "why": f"the translated module does not load: {type(exc).__name__}: {exc}"[:240], "gaps": gaps}
    from types import SimpleNamespace

    mod = SimpleNamespace(main=ns["main"], __file__=ns["__file__"])
    case = Case(stdin=stdin)
    try:
        want = run_cobol(exe, model, case, RUN_SECONDS)
    except Exception as exc:
        return {"stage": "cobc", "why": f"the COBOL could not be run: {exc}"[:200]}
    box: list = []
    t = threading.Thread(target=lambda: box.append(run_python(mod, case)), daemon=True)
    t.start()
    t.join(RUN_SECONDS)
    if not box:
        return {"stage": "mismatch", "why": "the Python did not finish", "gaps": gaps}
    got = box[0]
    diffs, _ = compare(model, want, got)
    if not diffs:
        return {"stage": "match", "gaps": gaps, "statements": tr.statements}
    d = diffs[0]
    err = got.error or ""
    stage = "gap-hit" if err.startswith("NotImplementedError") else "mismatch"
    return {"stage": stage, "why": err[:200] or f"{d.stream} line {d.index + 1}", "expected": d.expected[:200], "actual": d.actual[:200],
            "gaps": gaps, "cobol_error": want.error, "differing": len(diffs)}


def _one_cli(argv: list[str]) -> int:
    cob, name, root = Path(argv[0]), argv[1], Path(argv[2])
    result = run_one(cob, name, root)
    print("\n@@" + json.dumps(result), flush=True)
    os._exit(0)  # a run that hung leaves a spinning thread behind


def _spawn(cob: Path, name: str, root: Path, env: dict) -> dict:
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__)), "--one", str(cob), name, str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=240, env=env, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"stage": "crash", "why": "timed out after 240 seconds (translator or compiler hung)"}
    lines = [x for x in proc.stdout.splitlines() if x.startswith("@@")]
    if lines:
        return json.loads(lines[-1][2:])
    return {"stage": "crash", "why": ((proc.stderr.strip().splitlines() or ["no output"])[-1])[:240]}


def run_module(module: str, workers: int, only: str | None = None) -> list[dict]:
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    from seance.recorder import cobol_env

    folder = HOME / module
    if not folder.exists():
        raise SystemExit(f"{folder} is missing. Run: python scripts/stress_nist.py --fetch")
    progs = sorted(p for p in folder.glob("*.CBL") if p.stem not in SKIP and (not only or only in p.stem))
    env = {**cobol_env(), "PYTHONIOENCODING": "utf-8"}
    results: list[dict] = []
    lock = threading.Lock()

    def go(cob: Path) -> None:
        name = cob.stem.lower()
        with tempfile.TemporaryDirectory(prefix="nist_") as tmp:
            r = _spawn(cob, name, Path(tmp), env)
        r["name"] = cob.stem
        with lock:
            results.append(r)
            print(f"{cob.stem:<8} {r['stage']:<12} {r.get('why', '')[:110]}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(go, progs))
    results.sort(key=lambda r: r["name"])
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not only:
        (RESULTS / f"{module}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- the report

def report() -> str:
    import re
    from collections import Counter

    rows, details = [], []
    tot = Counter()
    for m in MODULES:
        p = RESULTS / f"{m}.json"
        if not p.exists():
            continue
        rs = json.loads(p.read_text(encoding="utf-8"))
        c = Counter(r["stage"] for r in rs)
        usable = len(rs) - c["cobc"]
        tot.update(c)
        tot["usable"] += usable
        rows.append(f"| {m} | {len(rs)} | {c['cobc']} | {usable} | **{c['match']}** | {round(100 * c['match'] / usable) if usable else 0}% | "
                    f"{c['mismatch']} | {c['gap-hit'] + c['unsupported']} | {c['model'] + c['crash']} |")
        reasons = Counter(re.sub(r"\d+", "N", (r.get("why") or "")[:90]) for r in rs if r["stage"] not in ("match", "cobc"))
        if reasons:
            details.append(f"### {m}\n\n| Count | Reason |\n| ---: | --- |\n" + "\n".join(f"| {n} | {w.replace('|', '/')} |" for w, n in reasons.most_common(12)))
    head = ["# NIST COBOL-85 stress test", "",
            "Generated by `python scripts/stress_nist.py --report`. The programs are the NIST CCVS85 suite, split by its own EXEC85 "
            "program the way GnuCOBOL's test run splits it (`build/corpora/nist`, not part of this repository). Each program is compiled "
            "with GnuCOBOL 3.1.2 and translated by Séance; it counts as matched only when the Python writes every byte the COBOL wrote: the "
            "report file, every other file and the console. The suite's own expected results are not used.", "",
            "| Module | Programs | Not compilable by default | Usable | Matched | Share | Output differs | Statement not supported | Not modelled |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    usable = tot["usable"]
    total_row = f"| **All** | {sum(tot[k] for k in ('match', 'mismatch', 'gap-hit', 'unsupported', 'model', 'crash', 'cobc'))} | {tot['cobc']} | {usable} | **{tot['match']}** | {round(100 * tot['match'] / usable) if usable else 0}% | {tot['mismatch']} | {tot['gap-hit'] + tot['unsupported']} | {tot['model'] + tot['crash']} |"
    return "\n".join(head + rows + [total_row, "", "## What stopped the rest", ""] + details) + "\n"


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--one":
        return _one_cli(argv[1:])
    if argv and argv[0] == "--fetch":
        fetch()
        print("built:", ", ".join(f"{m} ({len(list((HOME / m).glob('*.CBL')))})" for m in MODULES))
        return 0
    if argv and argv[0] == "--report":
        (ROOT / "docs" / "STRESS_NIST.md").write_text(report(), encoding="utf-8")
        print("wrote docs/STRESS_NIST.md")
        return 0
    workers = int(os.environ.get("STRESS_WORKERS", "6"))
    only = None
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    for m in argv or MODULES:
        rs = run_module(m, workers, only)
        n = sum(r["stage"] == "match" for r in rs)
        print(f"== {m}: {n} of {len(rs)} matched")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
