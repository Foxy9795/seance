"""Package a migration as a standalone Python program that runs without Séance or COBOL."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

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
    return f"{folder}.zip", buf.getvalue()


def report_markdown(program: str, implementation: str | None = None, root: Path = ROOT) -> str | None:
    implementation = implementation or f"migrated.{program}"
    p = root / "build" / "reports" / f"{implementation.replace('.', '_')}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:80]
