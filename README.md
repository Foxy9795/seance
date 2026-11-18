# Séance

Raise legacy COBOL from the dead, and check against the real program that the new code behaves the same.

Kiroween 2026, category: Resurrection.

Migrating COBOL fails when nobody can prove the new code matches the old. Séance
compiles and runs the original program, records what it actually does, and checks
a Python migration against those recordings (a few hundred records per program) and
against freshly generated random records. Mismatches shrink to a minimal failing input.
A pass is strong evidence, not a proof for every possible input.

## Quick start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Put GnuCOBOL 3.1.2 (MinGW x64) in tools\gnucobol\ :
#   https://github.com/mridoni/gnucobol-binaries/releases  (gnucobol-3.1.2-windows-mingw-x64.7z)
.\scripts\run.ps1        # starts the app and opens http://127.0.0.1:8000
```

Any `cobc` already on PATH also works.

### Security model

Séance compiles and runs code you give it (COBOL and Python), so treat it like a local dev server:

- It binds to 127.0.0.1 only and rejects requests addressed to any other host name, which blocks DNS rebinding.
- Every request that changes anything needs a random per-launch token that only the page it serves contains, and must be JSON. A web page on another site cannot drive it.
- The shipped examples are read-only. Only programs you add can be edited or deleted.
- It does not sandbox your code. Do not paste COBOL or Python you do not trust, and do not expose the port.

## Using the app

| Tab | What it does |
| --- | --- |
| **Check** | Runs the real COBOL and your Python on saved edge cases, saved random records, and fresh Hypothesis-generated records. Shows "Spirit matched" or "Spirit restless" and the smallest failing input, split by field with the wrong characters highlighted. |
| **Try one record** | Type records, see COBOL and Python side by side. A failing case has a "Try this record" button that sends it here. |
| **Code** | COBOL on the left, your Python on the right. Save, or save and check. |
| **What the COBOL does** | A plain-English, line-numbered reading of the COBOL, including where values silently round or truncate. |
| **Add your COBOL** | Paste a program (and any copybooks). Séance compiles it, records fixtures, writes the description and creates a Python stub. "Load a working example" fills in a fixed-format program with DD file names, FILLER, a level-88 flag, a default signed field and an edited output field. |

"Copy an AI prompt to write the Python" puts an instruction on your clipboard so Kiro can write the migration with the MCP tools. Wisp, the ghost, is the guide.

## What COBOL it understands

Séance reads the program itself, so you do not rename anything to fit it.

| Supported | Notes |
| --- | --- |
| Fixed-format source (columns 8-72, sequence numbers, `-` continuation) and free format | Detected automatically |
| One input file and one output file, any names | DD-style names such as `ACCTREC` and literal names such as `"INPUT.DAT"` |
| Fixed-length records (no line breaks) and `LINE SEQUENTIAL` text files | Chosen from the `SELECT` clause |
| Records defined in the FD, or in copybooks you add | `COPY` members are inlined |
| Groups, `FILLER`, `VALUE`, level-88 names | Groups are flattened into fields |
| `X`, `9`, `V`, signed `S9` in all four sign styles (trailing/leading overpunch, trailing/leading separate) | Checked against GnuCOBOL, including negative zero |
| Edited pictures such as `$$,$$9.99-`, `ZZ9.99CR`, `-(5)9.99`, `***,**9.99` | Checked against GnuCOBOL for values that fit |
| `COMP`, `COMP-3` in WORKING-STORAGE | Only the record files must be display data |

| Not supported yet | What you see |
| --- | --- |
| `COMP` / `COMP-3` fields inside a record file | An error naming the field, with a workaround |
| `OCCURS`, `REDEFINES`, `BLANK WHEN ZERO`, `JUSTIFIED`, `SYNCHRONIZED` | An error naming the field |
| Indexed or relative files; more than one input or output file | An error naming the files |
| Programs that skip records or write headers and totals | An error: Séance needs one output record per input record |
| Edited-picture display when a value is too big for the picture | GnuCOBOL's output is inconsistent here, so Séance reports a difference instead of guessing |
| `COPY ... REPLACING` | An error |

The IBM-style course program `CBL0001` (openmainframeproject/cobol-programming-course) is the shape this was built against: fixed format, DD names, records in the FD, edited print fields. It has `COMP-3` account fields in its record, so Séance explains that limit instead of failing mysteriously.

## How it works

1. **Analyze**: parse the copybooks into a record layout and write a spec (`seance/copybook.py`, `seance/spec.py`).
2. **Generate**: emit a Python record layer with exact PIC semantics (`generated/`).
3. **Record**: compile and run the original with GnuCOBOL on edge and random inputs; store fixtures (`fixtures/`).
4. **Migrate**: you or Kiro write the business logic in `migrated/`, using `seance.cobol_num.store()` and `size_error()` to mirror COBOL storage.
5. **Verify**: replay fixtures, then run a Hypothesis differential test against the live COBOL binary.

Verification runs in a separate process with a timeout (`SEANCE_VERIFY_TIMEOUT`, default 600 seconds), so edits are always picked up and a migration that loops forever cannot hang the app.

## Kiro integration

- **MCP server** (`seance/mcp_server.py`, registered in `.kiro/settings/mcp.json`): `list_programs`, `describe_program`, `describe_layout`, `run_legacy_program`, `generate_records`, `record_legacy_fixtures`, `verify_migration`.
- **Steering** (`.kiro/steering/`): product rules and COBOL-to-Python rules.
- **Hook** (`.kiro/hooks/`): re-verify when a file in `migrated/` is saved.
- **Spec** (`.kiro/specs/seance/`): requirements.

The venv Python path in `.kiro/settings/mcp.json` is absolute. Edit it if you clone the repo elsewhere.

## Command line

```powershell
. .\scripts\env.ps1                                   # GnuCOBOL on PATH for this shell
python -m seance all payroll                          # spec, generate, record, verify
python -m seance verify payroll --impl examples.naive.payroll_naive   # watch it fail
python -m seance analyze payroll                        # what Séance understood about the program
python -m seance compare payroll --line "A1    075000001"
python -m pytest
```

## Demo programs

| Program | Edge case the verifier catches |
| --- | --- |
| payroll | Per-step ROUNDED (half away from zero) vs float `round()`. Gross pay wraps past 999,999.99. |
| interest | Overdraft fee overflow flips -999,999,999.99 to -24.99. |
| inventory | Stock above 99,999 wraps; shortfall backorders truncate to 5 digits. |
| loan | `ON SIZE ERROR` on a payment that does not fit or a zero term; exponentiation. Float drafts divide by zero where COBOL returns status E. |

## Limits

- Windows-first. The COBOL runtime is the bundled MinGW build of GnuCOBOL 3.1.2.
- Séance verifies a migration. It does not write the business logic itself; you or Kiro do.
- Verification is evidence, not proof. It covers recorded and generated inputs, not every possible input.
- The spec generator is rule-based, not an LLM. It narrates statements it is sure about and lists the rest under "Needs human review".
- Your COBOL and Python run as you, with no sandbox beyond a timeout.
- Packed-decimal record files (`COMP-3` in the record) are the main thing to add next.

License: MIT.

