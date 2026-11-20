"""Package a migration as a standalone Python program that runs without Séance or COBOL."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

from .cases import text_only
from .cases import text_only
from .cases import text_only
from .recorder import ROOT, get_model

RUNTIME_FILES = ("rt.py", "codec.py", "cobol_num.py")

RUNNER = '''"""Run the migrated {pid} program the way the COBOL batch job ran.

Input files are read from this folder under the names the COBOL used ({inputs}), and output files are
written here too ({outputs}). Set DD_<NAME>=path to use another file, as with a JCL DD statement.
Console input comes from stdin; DISPLAY output goes to stdout.

    python run.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import {module} as program  # noqa: E402
from seance.rt import run_cli  # noqa: E402

FILES = {files!r}

if __name__ == "__main__":
    sys.exit(run_cli(program.main, FILES))
'''


TEST_SUITE = '''"""Golden tests for {pid}: every saved run of the real COBOL ({count} sets), replayed through the Python.

Each folder under data/ holds the input files the COBOL read and the output it wrote. The test feeds the same input to the
Python and compares every output file, the console output and the return code, byte for byte.

    python -m pip install pytest
    python -m pytest tests
"""
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import {module} as program  # noqa: E402
from seance.rt import IO, CobolError  # noqa: E402

SETS = sorted(p for p in (HERE / "data").iterdir() if (p / "set.json").exists())
TEXT_FILES = {text_files!r}  # line sequential files: a line ending is not part of the data
RECORD_SIZE = {record_size!r}  # fixed-length record files
PRINT_FILES = {print_files!r}  # record files made only of text: a print file carries line and page breaks between records
PRINT_FILES = {print_files!r}  # record files made only of text: a print file carries line and page breaks between records
PRINT_FILES = {print_files!r}  # record files made only of text: a print file carries line and page breaks between records


def units(assign, data):
    """Lines of a text file, or records of a record file (print files carry line and page breaks between records)."""
    if assign in TEXT_FILES:
        rows = data.replace(b"\\r\\n", b"\\n").split(b"\\n")
        if rows and rows[-1] == b"":
            rows.pop()
        return rows
    size = RECORD_SIZE.get(assign) or len(data) or 1
    if assign in PRINT_FILES and (b"\\n" in data or b"\\f" in data):
        out = []
        for piece in re.split(rb"[\\n\\f]", data):
            out += [piece[i:i + size] for i in range(0, len(piece), size)] or [b""]
        while out and out[-1] == b"":
            out.pop()
        return out
    return [data[i:i + size] for i in range(0, len(data), size)]


def same(assign, got, want):
    return got is not None and (got == want or units(assign, got) == units(assign, want))


@pytest.mark.parametrize("folder", SETS, ids=lambda p: p.name)
def test_matches_the_cobol(folder):
    meta = json.loads((folder / "set.json").read_text(encoding="utf-8"))
    files = {{assign: (folder / name).read_bytes() for assign, name in meta["inputs"].items()}}
    expected = {{assign: (folder / name).read_bytes() for assign, name in meta["outputs"].items()}}
    console = (folder / "console.txt").read_text(encoding="utf-8")
    if meta.get("error"):  # the COBOL itself stopped here (for example a missing file): so must the Python
        with pytest.raises(CobolError):  # the runtime's own error; any other exception is a crash, not a match
            program.main(IO(files, meta["stdin"]))
        return
    io = IO(files, meta["stdin"])
    io = program.main(io) or io
    for assign, data in expected.items():
        assert same(assign, io.outputs.get(assign), data), f"output file {{assign}} differs from the COBOL's"
    assert io.stdout.replace("\\r\\n", "\\n") == console.replace("\\r\\n", "\\n"), "console output differs from the COBOL's"
    assert int(io.return_code or 0) == int(meta["return_code"]), "return code differs from the COBOL's"
'''


def _test_suite(program: str, model, root: Path) -> dict[str, bytes | str]:
    """The saved runs as a pytest suite that needs nothing but the packaged runtime. Programs that talk to a database or a
    CICS region are left out: their bridges are not part of the package."""
    if any(f.organization in ("sqldb", "cicsdb") for f in model.all_files):
        return {}
    base = root / "fixtures" / program
    sets = sorted(p for p in base.iterdir() if (p / "set.json").exists()) if base.exists() else []
    if not sets:
        return {}
    files: dict[str, bytes | str] = {"tests/__init__.py": ""}
    for d in sets:
        for f in d.iterdir():
            if f.is_file():
                files[f"tests/data/{d.name}/{f.name}"] = f.read_bytes()
    text_files = sorted(f.assign for f in model.all_files if f.organization == "line")
    files[f"tests/test_{program}.py"] = TEST_SUITE.format(pid=model.program_id, count=len(sets), module=program, text_files=text_files,
                                                                record_size={f.assign: f.size for f in model.all_files if f.organization != "line"},
                                                                print_files=sorted(f.assign for f in model.all_files if f.organization != "line" and text_only(f)))
    return files


def bundle(program: str, implementation: str | None = None, root: Path = ROOT) -> tuple[str, bytes]:
    implementation = implementation or f"migrated.{program}"
    model = get_model(program, root)
    module = program
    impl_src = (root / (implementation.replace(".", "/") + ".py")).read_text(encoding="utf-8-sig")
    report_md = root / "build" / "reports" / f"{implementation.replace('.', '_')}.md"
    report_json = root / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
    verdict = ""
    if report_json.exists():
        r = json.loads(report_json.read_text(encoding="utf-8"))
        rc = r.get("receipt", {})
        verdict = (f"Last Séance check: **{r.get('verdict')}** ({rc.get('saved_records', 0)} saved records, "
                   f"{rc.get('random_runs', r.get('random_runs', 0))} random runs).")
    folder = f"{program}_python"
    inputs = ", ".join(f.assign for f in model.inputs) or "none"
    outputs = ", ".join(f.assign for f in model.outputs) or "none"
    files = [[f.name, f.assign] for f in model.all_files]
    readme = f"""# {model.program_id.title()} in Python

Migrated from `{model.path.name}` with Séance on {date.today().isoformat()}.
{verdict}

## Run it

```
python run.py
```

It reads {inputs} and writes {outputs} in the current folder, byte for byte the way the COBOL did.
{"It also reads console input (ACCEPT), one value per line on stdin." if model.all_accepts else ""}
Set `DD_<NAME>` to point a file elsewhere, for example `DD_{(model.all_files[0].assign if model.all_files else 'INPUT')}=data/today.dat`.
Python 3.10 or newer, no other packages.

## Files

| File | What it is |
| --- | --- |
| `{module}.py` | The program |
| `seance/` | COBOL data and number rules (records, packed decimal, rounding, truncation, edited pictures) |
| `run.py` | Runs the program on the files in this folder |
| `REPORT.md` | The last Séance check, if one was run |
"""
    suite = _test_suite(program, model, root)
    if suite:
        readme += "\n## Tests\n\n`tests/` replays every saved run of the original COBOL through this Python and compares the output:\n\n```\npython -m pip install pytest\npython -m pytest tests\n```\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/{module}.py", impl_src)
        z.writestr(f"{folder}/run.py", RUNNER.format(pid=model.program_id, module=module, files=files, inputs=inputs, outputs=outputs))
        z.writestr(f"{folder}/README.md", readme)
        z.writestr(f"{folder}/seance/__init__.py", '"""COBOL runtime rules used by the migrated program."""\n')
        for name in RUNTIME_FILES:
            z.writestr(f"{folder}/seance/{name}", (root / "seance" / name).read_text(encoding="utf-8-sig"))
        if report_md.exists():
            z.writestr(f"{folder}/REPORT.md", report_md.read_text(encoding="utf-8"))
        for name, data in suite.items():
            z.writestr(f"{folder}/{name}", data)
    return f"{folder}.zip", buf.getvalue()


def report_html(program: str, implementation: str | None = None, root: Path = ROOT) -> str | None:
    """The last check as one self-contained page, for people who will not open the app (printable, nothing to install)."""
    from html import escape as e

    implementation = implementation or f"migrated.{program}"
    p = root / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text(encoding="utf-8"))
    rc = r.get("receipt") or {}
    cov = r.get("coverage") or {}
    sets = r.get("sets", [])
    compared = sum(s.get("compared", 0) for s in sets)
    differing = sum(s.get("differing", 0) for s in sets)
    good = bool(r.get("matched"))
    rows = "".join(f"<tr><td>{e(s['label'].split(' (')[0])}</td><td class=n>{s.get('records', 0)}</td><td class=n>{s.get('compared', 0)}</td><td class='n {'bad' if s.get('differing') else ''}'>{s.get('differing', 0)}</td></tr>" for s in sets)
    def diff(d):
        fields = "".join(f"<tr><td>{e(str(x['name']))}</td><td>{e(str(x['expected']))}</td><td class=bad>{e(str(x['actual']))}</td></tr>" for x in d.get("fields", []) if not x.get("same"))
        return (f"<div class=diff><b>{e(str(d['stream']))}{'' if d['index'] < 0 else ' line ' + str(d['index'] + 1)}</b><pre>COBOL   {e(str(d['expected']))}\nPython  {e(str(d['actual']))}</pre>"
                f"{'<table class=f><tr><th>Field<th>COBOL<th>Python</tr>' + fields + '</table>' if fields else ''}</div>")
    shown = "".join(diff(d) for d in r.get("diffs", [])[:10])
    fail = r.get("random_failure")
    shrunk = ""
    if fail:
        inputs = "".join(f"<p><code>{e(k)}</code></p><pre>" + e("\n".join(v)) + "</pre>" for k, v in (fail.get("inputs") or {}).items())
        shrunk = f"<h2>Smallest failing input</h2><p>A random run failed. Séance shrank its input to this.</p>{inputs}" + "".join(diff(d) for d in fail.get("diffs", [])[:3])
    missed = ", ".join(f"line {m['line']}" for m in (cov.get("missed") or [])[:30])
    review = "".join(f"<li>{e(x)}</li>" for x in r.get("review", [])) or "<li>Nothing flagged</li>"
    from . import __version__
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Séance check report: {e(program)}</title>
<style>body{{font:15px/1.55 system-ui,Segoe UI,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#1d1a21}}h1{{font:600 26px Georgia,serif;margin:0 0 4px}}h2{{font-size:17px;margin:28px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.v{{display:inline-block;padding:4px 12px;border-radius:6px;font-weight:600;color:#fff;background:{'#1c7a55' if good else '#b3402e'}}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #e4e0e8}}td.n,th.n{{text-align:right}}
.bad{{color:#b3402e;font-weight:600}}pre{{background:#f4f2f6;padding:10px;border-radius:6px;overflow:auto;font:13px Consolas,monospace}}code{{font:13px Consolas,monospace}}.meta{{color:#665f70;font-size:13px}}.f{{width:auto;margin:6px 0}}
.metrics{{display:flex;gap:28px;margin:14px 0}}.metrics b{{font-size:22px;display:block}}.metrics span{{color:#665f70;font-size:12px}}.diff{{margin:10px 0}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>{e(program)}</h1><p class=meta>{e(r.get('implementation', implementation))} · checked {e(str(rc.get('checked_at', '')))} · Séance {e(__version__)}</p>
<p><span class=v>{e(str(r.get('verdict')))}</span></p>
<div class=metrics><div><b>{compared:,}</b><span>Lines compared</span></div><div><b class="{'bad' if differing else ''}">{differing}</b><span>Lines differ</span></div><div><b>{r.get('random_runs', 0)}</b><span>Random runs</span></div>{'<div><b>' + str(cov.get('percent')) + '%</b><span>COBOL statements reached</span></div>' if cov else ''}</div>
<h2>Receipt</h2><p class=meta>A verdict belongs to exactly this code and this data.</p><table><tr><td>COBOL source SHA-256</td><td><code>{e(str(rc.get('cobol_sha256', '')))}</code></td></tr><tr><td>Python SHA-256</td><td><code>{e(str(rc.get('python_sha256', '')))}</code></td></tr><tr><td>Test data SHA-256</td><td><code>{e(str(rc.get('evidence_sha256', '')))}</code></td></tr></table>
<h2>Saved test sets</h2><table><tr><th>Set<th class=n>Input records<th class=n>Compared<th class=n>Differ</tr>{rows}</table>
{('<h2>Coverage</h2><p>' + str(cov.get('reached')) + ' of ' + str(cov.get('statements')) + ' COBOL statements are reached by the saved runs.' + (' Not reached: ' + e(missed) + '.' if missed else ' Every statement is reached.') + '</p>') if cov else ''}
{shrunk}{'<h2>Differences in the saved runs</h2>' + shown if shown else ''}
<h2>Needs human review</h2><ul>{review}</ul>
<p class=meta>Passing differential tests is strong evidence, not a proof for every input.</p></body></html>"""


def report_markdown(program: str, implementation: str | None = None, root: Path = ROOT) -> str | None:
    implementation = implementation or f"migrated.{program}"
    p = root / "build" / "reports" / f"{implementation.replace('.', '_')}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:80]
