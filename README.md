# Séance

**Rewrite COBOL in Python, and prove it gives the same answers.**

Kiroween 2026, category: Resurrection.

Migrating COBOL rarely fails because the new code is hard to write. It fails because nobody can
show the new code behaves exactly like the old: the same rounding, the same truncation, the same
signs, on every record. Séance runs the original COBOL and the Python side by side and compares
every output, character by character.

1. **Add your COBOL.** Drop the program and its copybooks. Séance compiles it with GnuCOBOL and
   records what it really does on edge cases, random records, and values it finds in the code.
2. **Get a Python draft.** A rule-based translator writes the Python statement by statement. Every
   line is tagged with the COBOL line it came from. Anything it cannot translate raises an error
   naming that line, so a check fails loudly instead of passing quietly.
3. **Check and measure.** Run the check against the real COBOL. Then measure test strength: Séance
   plants small bugs in the Python one at a time and shows which ones the saved records miss.
4. **Download it.** A standalone Python program, with a `run.py` that processes a whole file the way
   the batch job did. It needs only Python 3.10 or newer.

## Quick Start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Put GnuCOBOL 3.1.2 (MinGW x64) in tools\gnucobol\ :
#   https://github.com/mridoni/gnucobol-binaries/releases  (gnucobol-3.1.2-windows-mingw-x64.7z)
.\scripts\run.ps1        # starts the app and opens http://127.0.0.1:8000
```

Any `cobc` already on PATH also works. Start with **Watch a Wrong Rewrite Get Caught**, then
**Add My COBOL** and **Use the Example**.

## The App

| Tab | What it does |
| --- | --- |
| **Check** | Runs the COBOL and the Python on every saved test set and on new random records. Shows "Spirit Matched" or "Spirit Restless" and the smallest failing input, split by field with the wrong characters lit up. |
| **Test Strength** | Plants one bug at a time (`>` to `>=`, ROUNDED dropped, a constant changed, `+` to `-`) and replays the saved records. Shows how many were caught and the COBOL line of every survivor. |
| **Try a Record** | Type records and see the COBOL and Python answers side by side. Every failing case has a "Try This Record" button. |
| **Code** | COBOL on the left, Python on the right. Save, Save and Check, Redraft From COBOL (the old file is kept as `.bak`), Download. |
| **COBOL Explained** | A plain-English, line-numbered reading of the program, including every place a number is rounded or cut off. |
| **Test Data** | The saved record sets. Drop a real input file, in text lines or fixed-length records, and every check replays it with the COBOL's answers. |
| **Export** | The standalone program (.zip), the Python file, and the check report. |

The progress strip above the tabs shows where each program stands: Python, Check, Test Strength, Export.

## What COBOL It Reads

The same lists are served by `/api/about` and shown in the app, from one place in `seance/config.py`.

**Works today:**

- Fixed-format (columns 8-72, sequence numbers, `-` continuation) and free-format source, detected automatically
- One input file and one output file with any names, including DD names such as `ACCTREC`
- Fixed-length records (no line breaks) and `LINE SEQUENTIAL` text files
- Records in the FD or in copybooks via `COPY`
- Groups, `FILLER`, `VALUE`, and level-88 condition names
- Text, numbers, decimals, and every sign style: trailing or leading overpunch, trailing or leading separate. Checked against GnuCOBOL, including negative zero.
- Edited pictures such as `$$,$$9.99-`, `ZZ9.99CR`, `-(5)9.99`, `***,**9.99`. Checked against GnuCOBOL for values that fit.
- `COMP` and `COMP-3` in WORKING-STORAGE
- Translated statements: `MOVE`, `COMPUTE`, `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`, `IF`, `EVALUATE` (`TRUE` or a subject, `THRU`, `OTHER`), `PERFORM` (paragraphs, `THRU`, `UNTIL`, `VARYING`, `TIMES`, `WITH TEST AFTER`), `INITIALIZE`, `SET ... TO TRUE`, `ON SIZE ERROR`, and priming-read or read-inside-the-loop structures

**Not yet.** The app says so clearly, naming the field or line:

- `COMP` or `COMP-3` fields inside the record files
- `OCCURS` tables and `REDEFINES`
- Indexed or relative files, or more than one input or output file
- Programs that skip records or add header and total lines (one output record per input record is required)
- `GO TO`, `STRING`, `UNSTRING`, `INSPECT`, `CALL`, intrinsic `FUNCTION`s: the draft marks them for a person
- Edited-picture display when a value is too big for the picture (GnuCOBOL is inconsistent there, so Séance reports a difference instead of guessing)

## How the Checking Works

- **Saved test sets:** Edge cases come from the record layout: zero, the smallest and largest values, and negative zero. They also come from the code: level-88 values on input fields, and every literal an input field (or a field it is moved into) is compared against, plus the values just either side of it. Random records come next, then any files you upload.
- **New random records each check:** Hypothesis generates them from the layout using the same code-derived values, and they run against the live COBOL binary. The first failure is made as simple as possible with a fixed budget of COBOL runs.
- **Test strength:** Bugs that provably cannot change anything are skipped, such as adding ROUNDED to whole-number arithmetic. Each planted bug runs in its own process with a time limit, so a bug that makes a loop endless is caught, not hung on.
- **Fresh code every time:** checks run in a separate process with a timeout (`SEANCE_VERIFY_TIMEOUT`), so edits are always picked up.

## Settings

All in `seance/config.py`, read from the environment:

`SEANCE_ROUNDS`, `SEANCE_MAX_ROUNDS`, `SEANCE_VERIFY_TIMEOUT`, `SEANCE_COMPARE_TIMEOUT`, `SEANCE_MUTANTS`,
`SEANCE_MAX_DATA_RECORDS`, `SEANCE_RANDOM_RECORDS`.

## Security Model

Séance compiles and runs code you give it, so treat it like a local dev server.

- It binds to 127.0.0.1 and rejects requests addressed to any other host name, which blocks DNS rebinding.
- Every request that changes anything must be JSON and carry a random per-launch token that only the page it serves contains.
- The shipped examples are read-only. Only programs you add can be edited, redrafted or deleted.
- It does not sandbox your code beyond timeouts. Do not run COBOL or Python you do not trust, and do not expose the port.

## Kiro Integration

- **MCP server** (`seance/mcp_server.py`, registered in `.kiro/settings/mcp.json`) with these tools: `list_programs`, `describe_program`, `describe_layout`, `run_legacy_program`, `generate_records`, `record_legacy_fixtures`, `draft_python`, `verify_migration`, `measure_test_strength`.
- **Steering** (`.kiro/steering/`): product rules and COBOL-to-Python rules.
- **Hook** (`.kiro/hooks/`): re-verifies when a file in `migrated/` is saved.
- **Spec** (`.kiro/specs/seance/`): requirements.

The venv Python path in `.kiro/settings/mcp.json` is absolute. Edit it if you clone the repo elsewhere.

## Command Line

```powershell
. .\scripts\env.ps1                       # GnuCOBOL on PATH for this shell
python -m seance analyze accounts         # what Séance understood about the program
python -m seance translate accounts       # write the Python draft
python -m seance verify accounts          # check it against the real COBOL
python -m seance mutate accounts          # measure test strength
python -m seance export accounts          # build\accounts_python.zip
python -m pytest                          # 76 tests, including differential tests against GnuCOBOL
python scripts\ui_check.py                # 24 checks that drive the real UI in Edge (app must be running)
```

## Example Programs

| Program | What it exercises |
| --- | --- |
| accounts | Mainframe style: fixed format, DD names, a copybook, a priming read, level-88 account types, compound interest in `PERFORM VARYING`, a tiered fee in `EVALUATE`, `ON SIZE ERROR`, a `COMP-3` work field and an edited output field. |
| payroll | Per-step ROUNDED (half away from zero) against float `round()`. Ships with a naive float draft that fails. |
| loan | `ON SIZE ERROR` on a payment that does not fit or a zero term, and exponentiation. Ships with a naive draft. |
| interest | Overdraft fee overflow flips -999,999,999.99 to -24.99. |
| inventory | Stock above 99,999 wraps, and shortfall backorders truncate to 5 digits. |

## Limits

- Windows-first. The COBOL runtime is the MinGW build of GnuCOBOL 3.1.2.
- A pass is strong evidence, not a proof for every possible input. Test Strength shows where the evidence is thin.
- The translator and the description are rule-based, not an LLM. They never guess: what they cannot read is marked.
- Packed-decimal record files (`COMP-3` inside the record) are the main thing to add next.

License: MIT.
