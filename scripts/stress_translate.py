"""Stress the translator with the programs from GnuCOBOL's own test suite.

For every program in the suite, Séance compiles it with GnuCOBOL, translates it to Python, runs both, and compares
what they write. The expected output in the suite is not used: the compiled COBOL is the judge, as everywhere else.

    python scripts/stress_translate.py --fetch run_fundamental run_misc     download suites (not redistributed)
    python scripts/stress_translate.py run_fundamental --workers 4          run one or more suites
    python scripts/stress_translate.py run_fundamental --only "DISPLAY"     programs whose test name contains this
    python scripts/stress_translate.py run_fundamental --report docs/STRESS.md

The suite files go to build/gnucobol_tests (git-ignored). They are GPL-licensed and are not part of this repository.
Results go to build/stress/<suite>.json. Programs that need extra files, that the suite expects to fail compiling,
or that GnuCOBOL cannot compile with default options are counted separately: they say nothing about the translator.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SUITES = ROOT / "build" / "gnucobol_tests"
OUT = ROOT / "build" / "stress"
TAG = "gnucobol-3.1.2"  # the GnuCOBOL release bundled in tools/
URL = "https://raw.githubusercontent.com/OCamlPro/gnucobol/" + TAG + "/tests/testsuite.src/{}.at"
QUADRIGRAPHS = {"@<:@": "[", "@:>@": "]", "@S|@": "$", "@%:@": "#", "@&t@": ""}
RUN_SECONDS = 10


# ---------------------------------------------------------------- the suite files

def fetch(names: list[str]) -> None:
    SUITES.mkdir(parents=True, exist_ok=True)
    for n in names:
        target = SUITES / f"{n}.at"
        if target.exists():
            continue
        try:
            with urllib.request.urlopen(URL.format(n), timeout=60) as r:
                target.write_bytes(r.read())
            print(f"fetched {n} ({target.stat().st_size // 1024} KB)")
        except Exception as exc:
            print(f"could not fetch {n}: {exc}")


def _balanced(text: str, start: int) -> tuple[str, int]:
    """The m4-quoted text that begins just after an opening [ at `start - 1`, and the index after its closing ]."""
    depth, i = 1, start
    while i < len(text) and depth:
        c = text[i]
        depth += (c == "[") - (c == "]")
        i += 1
    return text[start:i - 1], i


def extract(at_text: str) -> list[dict]:
    """One entry per AT_SETUP: name, the main program (prog.cob), and why it may not be usable."""
    out = []
    for block in re.split(r"(?m)^AT_SETUP\(\[", at_text)[1:]:
        name = block.split("])", 1)[0].strip().replace("\n", " ")
        block = block.split("AT_CLEANUP", 1)[0]
        files: dict[str, str] = {}
        for m in re.finditer(r"AT_DATA\(\[([^\]]+)\],\s*\[", block):
            body, _ = _balanced(block, m.end())
            for k, v in QUADRIGRAPHS.items():
                body = body.replace(k, v)
            files[m.group(1).strip()] = body.lstrip("\n")
        prog = files.get("prog.cob") or files.get("prog.cbl")
        compiles = re.findall(r"AT_CHECK\(\[\$COMPILE([^\]]*)\],\s*\[(\d+)\]", block)
        flags = " ".join(f.strip() for f, _ in compiles[:1])
        skip = None
        if prog is None:
            skip = "no prog.cob in the test"
        elif set(files) - {"prog.cob", "prog.cbl"}:
            skip = "needs extra files: " + ", ".join(sorted(set(files) - {"prog.cob", "prog.cbl"}))[:60]
        elif compiles and compiles[0][1] != "0":
            skip = "the suite expects this not to compile"
        out.append({"name": name, "source": prog, "flags": flags, "skip": skip})
    return out


# ---------------------------------------------------------------- one program, in its own process

def run_one(cob: Path, name: str, root: Path) -> dict:
    """Compile, translate, run both and compare. Never raises: every outcome is a result."""
    from seance.cases import Case, compare, run_cobol, run_python
    from seance.model import ModelError, load_model
    from seance.recorder import LegacyRuntimeError, compile_legacy
    from seance.translate import Unsupported, translate

    src = root / "legacy" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{name}.cbl").write_text(cob.read_text(encoding="utf-8"), encoding="utf-8")
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
    ns: dict = {"__name__": f"stress_{name}", "__file__": str(root / "migrated" / f"{name}.py")}
    try:
        exec(compile(tr.code, ns["__file__"], "exec"), ns)
    except Exception as exc:
        return {"stage": "crash", "why": f"the translated module does not load: {type(exc).__name__}: {exc}"[:240], "gaps": gaps}
    from types import SimpleNamespace

    mod = SimpleNamespace(main=ns["main"], __file__=ns["__file__"])
    try:
        want = run_cobol(exe, model, Case(), RUN_SECONDS)
    except Exception as exc:
        return {"stage": "cobc", "why": f"the COBOL could not be run: {exc}"[:200]}
    box: list = []
    t = threading.Thread(target=lambda: box.append(run_python(mod, Case())), daemon=True)
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
    return {"stage": stage, "why": err[:200] or f"{d.stream} line {d.index + 1}", "expected": d.expected[:200], "actual": d.actual[:200], "gaps": gaps,
            "cobol_error": want.error, "differing": len(diffs)}


def _one_cli(argv: list[str]) -> int:
    import os

    cob, name, root = Path(argv[0]), argv[1], Path(argv[2])
    result = run_one(cob, name, root)
    print("\n@@" + json.dumps(result), flush=True)
    os._exit(0)  # a run that hung leaves a spinning thread behind


# ---------------------------------------------------------------- the whole suite

def _spawn(cob: Path, name: str, root: Path, env: dict) -> dict:
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__)), "--one", str(cob), name, str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=90, env=env, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"stage": "crash", "why": "timed out after 90 seconds (translator or compiler hung)"}
    lines = [x for x in proc.stdout.splitlines() if x.startswith("@@")]
    if lines:
        return json.loads(lines[-1][2:])
    return {"stage": "crash", "why": ((proc.stderr.strip().splitlines() or ["no output"])[-1])[:240]}


def run_suite(suite: str, workers: int, only: str | None, limit: int | None) -> list[dict]:
    from seance.recorder import cobol_env

    path = SUITES / f"{suite}.at"
    if not path.exists():
        raise SystemExit(f"{path} is missing. Run: python scripts/stress_translate.py --fetch {suite}")
    cases = extract(path.read_text(encoding="utf-8", errors="replace"))
    if only:
        cases = [c for c in cases if only.lower() in c["name"].lower()]
    if limit:
        cases = cases[:limit]
    env = cobol_env()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    root = Path(tempfile.mkdtemp(prefix="seance_stress_"))
    work = root / "src"
    work.mkdir()
    jobs = []
    for i, c in enumerate(cases):
        c["id"] = f"{suite}-{i:03d}"
        c["pname"] = f"st{i:03d}"
        if c["skip"]:
            c["result"] = {"stage": "skipped", "why": c["skip"]}
        else:
            f = work / f"{c['pname']}.cob"
            f.write_text(c["source"], encoding="utf-8")
            jobs.append(c)
    t0 = time.time()
    done = 0

    def go(c: dict) -> None:
        nonlocal done
        c["result"] = _spawn(work / f"{c['pname']}.cob", c["pname"], root, env)
        done += 1
        if done % 10 == 0:
            print(f"  {done}/{len(jobs)} ({time.time() - t0:.0f}s)", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(go, jobs))
    for c in cases:
        c.pop("source", None)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{suite}.json").write_text(json.dumps(cases, indent=1), encoding="utf-8")
    return cases


def _key(r: dict) -> str:
    """Group failures by reason: numbers, quoted names and line numbers are blanked."""
    why = r.get("why") or r.get("stage", "")
    why = re.sub(r"'[^']*'|\"[^\"]*\"", "'_'", why)
    why = re.sub(r"\b\d+\b", "N", why)
    return why[:110]


def summarize(cases: list[dict], title: str) -> str:
    stages = Counter(c["result"]["stage"] for c in cases)
    usable = len(cases) - stages["skipped"] - stages["cobc"]
    ok = stages["match"]
    lines = [f"## {title}", "",
             f"{len(cases)} programs. {stages['skipped']} skipped (extra files, or the suite expects a compile error), "
             f"{stages['cobc']} not compilable by GnuCOBOL with default options. Of the remaining {usable}:", "",
             f"- **{ok} matched** the COBOL output ({100 * ok // max(usable, 1)}%)"]
    for st, label in (("mismatch", "ran but the output differs"), ("gap-hit", "reached a statement the translator does not support"),
                      ("unsupported", "the translator refused the program"), ("model", "Séance could not model the program"),
                      ("crash", "the translator or the translated module crashed")):
        if stages[st]:
            lines.append(f"- {stages[st]} {label}")
    groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in cases:
        st = c["result"]["stage"]
        if st in ("mismatch", "gap-hit", "unsupported", "model", "crash"):
            groups[st][_key(c["result"])].append(c)
    for st in ("mismatch", "gap-hit", "unsupported", "model", "crash"):
        if not groups[st]:
            continue
        lines += ["", f"### {st}", "", "| Count | Reason | Example |", "| ---: | --- | --- |"]
        for key, items in sorted(groups[st].items(), key=lambda kv: -len(kv[1]))[:25]:
            ex = items[0]
            lines.append(f"| {len(items)} | {key.replace('|', '/')} | {ex['id']} {ex['name'][:48].replace('|', '/')} |")
    # statements the translator left as gaps in programs that nevertheless matched
    gap_texts = Counter(g["why"][:70] for c in cases for g in c["result"].get("gaps", []))
    if gap_texts:
        lines += ["", "### Statements the translator reports as unsupported (in any program)", "", "| Count | Reason |", "| ---: | --- |"]
        lines += [f"| {n} | {w.replace('|', '/')} |" for w, n in gap_texts.most_common(20)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--one":
        return _one_cli(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("suites", nargs="*", help="suite names, such as run_fundamental")
    ap.add_argument("--fetch", nargs="+", metavar="SUITE", help="download these suites first")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", help="only programs whose test name contains this text")
    ap.add_argument("--limit", type=int, help="only the first N programs of each suite")
    ap.add_argument("--report", metavar="FILE", help="write a Markdown summary")
    ap.add_argument("--report-only", action="store_true", help="do not run anything; summarize the saved results in build/stress")
    ap.add_argument("--baseline", metavar="TEXT", help="a line for the report saying what the first run found, for comparison")
    a = ap.parse_args(argv)
    if a.fetch:
        fetch(a.fetch)
    sections = []
    for s in a.suites:
        print(f"{s}:")
        if a.report_only:
            cases = json.loads((OUT / f"{s}.json").read_text(encoding="utf-8"))
        else:
            cases = run_suite(s, a.workers, a.only, a.limit)
        text = summarize(cases, s)
        print(text)
        sections.append(text)
    if a.report and sections:
        head = ("# Translator stress test\n\nGenerated by `python scripts/stress_translate.py`. The programs come from GnuCOBOL's own test suite "
                f"({TAG}), fetched at run time and not stored in this repository. The compiled COBOL is the judge; the suite's expected output is not used.\n\n"
                + (f"{a.baseline}\n\n" if a.baseline else "")
                + "How to read this. The suite exists to test GnuCOBOL itself, so it is full of extensions, compiler options and corner cases that ordinary "
                "business programs never use. A program counts as matched only when every byte the COBOL wrote is reproduced by the Python. "
                "A program that does not match is not silently accepted: the check reports it, and statements the translator cannot "
                "translate raise an error that names the COBOL line. The tables below are where to look next.\n\n")
        Path(a.report).write_text(head + "\n".join(sections), encoding="utf-8")
        print(f"wrote {a.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
