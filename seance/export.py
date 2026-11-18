"""Package a migration as a standalone Python program that runs without Séance or COBOL."""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

from .recorder import ROOT, get_model

RUNNER = '''"""Run the migrated {pid} program on a data file, the way the COBOL batch job did.

    python run.py INPUT-FILE OUTPUT-FILE
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import {module} as program  # noqa: E402
from {module}_records import IN_WIDTH, OUT_WIDTH, InRecord  # noqa: E402

INPUT_IS_LINES = {in_lines}
OUTPUT_IS_LINES = {out_lines}


def read_records(path):
    data = open(path, "rb").read().decode("latin-1")
    if INPUT_IS_LINES:
        rows = data.replace("\\r\\n", "\\n").split("\\n")
        return rows[:-1] if rows and rows[-1] == "" else rows
    return [data[i : i + IN_WIDTH] for i in range(0, len(data), IN_WIDTH)]


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    reset = getattr(program, "reset", None)
    if callable(reset):
        reset()
    out = [program.transform(InRecord.parse(r)).format() for r in read_records(argv[1])]
    with open(argv[2], "wb") as f:
        if OUTPUT_IS_LINES:
            f.write("".join(o + "\\n" for o in out).encode("latin-1"))
        else:
            f.write("".join(o.ljust(OUT_WIDTH)[:OUT_WIDTH] for o in out).encode("latin-1"))
    print(f"{{len(out)}} records written to {{argv[2]}}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''


def bundle(program: str, implementation: str | None = None, root: Path = ROOT) -> tuple[str, bytes]:
    implementation = implementation or f"migrated.{program}"
    model = get_model(program, root)
    module = program
    impl_src = (root / (implementation.replace(".", "/") + ".py")).read_text(encoding="utf-8-sig")
    impl_src = impl_src.replace(f"from generated.{program}_records import", f"from {module}_records import")
    records_src = (root / "generated" / f"{program}_records.py").read_text(encoding="utf-8-sig")
    report_md = root / "build" / "reports" / f"{implementation.replace('.', '_')}.md"
    report_json = root / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
    verdict = ""
    if report_json.exists():
        r = json.loads(report_json.read_text(encoding="utf-8"))
        verdict = f"Last Séance check: **{r.get('verdict')}** ({sum(v['records'] for v in r.get('fixtures', {}).values())} saved records, {r.get('property_runs')} random rounds)."
    folder = f"{program}_python"
    readme = f"""# {model.program_id.title()} in Python

Migrated from `{model.path.name}` with Séance on {date.today().isoformat()}.
{verdict}

## Run it

```
python run.py INPUT-FILE OUTPUT-FILE
```

It reads the same file the COBOL read ({'text lines' if model.input.organization == 'line' else f'fixed-length records of {model.in_layout.width} characters'}) and writes the
same file it wrote ({'text lines' if model.output.organization == 'line' else f'fixed-length records of {model.out_layout.width} characters'}). Python 3.10 or newer, no other packages.

## Files

| File | What it is |
| --- | --- |
| `{module}.py` | The business logic |
| `{module}_records.py` | Reading and writing the record layout, generated from the COBOL |
| `seance/` | COBOL number rules (rounding, truncation, signs, edited pictures) used by the code |
| `run.py` | Runs the program on a file |
| `REPORT.md` | The last Séance check, if one was run |
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/{module}.py", impl_src)
        z.writestr(f"{folder}/{module}_records.py", records_src)
        z.writestr(f"{folder}/run.py", RUNNER.format(pid=model.program_id, module=module, in_lines=model.input.organization == "line", out_lines=model.output.organization == "line"))
        z.writestr(f"{folder}/README.md", readme)
        z.writestr(f"{folder}/seance/__init__.py", '"""COBOL number rules used by the migrated program."""\n')
        for name in ("cobol_num.py", "runtime.py"):
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
