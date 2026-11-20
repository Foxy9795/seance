# Contributing

## Set up

```powershell
.\scripts\setup.ps1                                   # .venv, the seance command, GnuCOBOL 3.1.2, a setup check
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"  # Playwright, for the UI checks
.\.venv\Scripts\python.exe -m playwright install msedge   # only if Microsoft Edge is not installed
. .\scripts\env.ps1                                   # GnuCOBOL on PATH for this shell
```

## Before you send a change

```powershell
python -m pytest -q                 # 189 tests, many of them against the real GnuCOBOL
python scripts\check_rules.py       # the Kiroween rules and the steering rules
python -m seance serve --no-browser # then, in a second shell:
python scripts\ui_check.py          # drives the real UI in Edge (start from an empty workspace)
python scripts\audit_ui.py          # contrast, names, tap targets, dropdowns, script errors
```

A change to the translator or the runtime should also keep `scripts\stress_translate.py` at or above the numbers in
`docs\STRESS.md` (fetch the suites first with `--fetch run_fundamental run_misc ...`).

## How the code is organised

- Each pipeline stage (analyze, record, translate, verify) is a function over files with one CLI entry point in
  `seance/cli.py`. The web app (`seance/api.py`), the MCP server and the exported package call the same functions.
- `seance/rt.py` is the runtime translated programs stand on: COBOL data stays bytes in the copybook's layout.
- `web/index.html` is the whole front end: one file, vanilla JavaScript, no build step.

## Rules the code follows

These come from `.kiro/steering/` and are checked where they can be:

- Behavior is what the compiled COBOL does when it runs. A mismatch means the Python is wrong, never the saved data.
- Money is `decimal.Decimal`. No `float`, no `round()`, no banker's rounding (`scripts/check_rules.py` fails on them).
- Record layouts come from the COBOL. To change one, change the COBOL and record again.
- Anything not matched is reported as needing human review. Nothing is hidden to make a check pass.
- A test for every fix: it fails before the change and passes after.
- Colors keep WCAG AA contrast (`tests/test_ui_contrast.py`), and animation follows the reduced-motion setting.
