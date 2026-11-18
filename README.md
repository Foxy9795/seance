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

Any `cobc` already on PATH also works. Start with **See A Bug Being Caught** on the home page, then
**Add Your COBOL** and **Load An Example Program**.

## The App

Pick a program on the left. Each one has four tabs:

| Tab | What it does |
| --- | --- |
| **Overview** | What the program does, every file it reads and writes with its record layout, and a plain-English, line-numbered description. |
| **Code Side By Side** | COBOL on the left, Python on the right. Click a Python line to see its COBOL line. Your own programs can be edited, saved and translated again. |
| **Prove It** | Runs the check: "Spirit Matched" or "Spirit Restless", a receipt with hashes of both files, the smallest failing input, and field-by-field differences. Also Test Strength (planted bugs) and Test Data (upload real files). |
| **Try Your Input** | Type records or console input, or replay a saved set, and see both programs' output side by side. |

**Download** gives the Python file, a standalone package that runs without Séance or COBOL, and the check report.

## What COBOL It Reads

The same lists are served by `/api/about` and shown in the app, from one place in `seance/config.py`.

**Works today:**

- Fixed-format and free-format source, including IBM-style programs (a missing period after PROGRAM-ID is fixed and reported)
- Any number of sequential input and output files, with DD names such as `ACCTREC`
- Console programs: `DISPLAY`, and `ACCEPT` for typed input
- Fixed-length records, `LINE SEQUENTIAL` text files, and printed reports written with `ADVANCING`
- Records in the FD, WORKING-STORAGE or copybooks (`COPY`, `COPY REPLACING`)
- Packed decimal (`COMP-3`), binary (`COMP`, `COMP-5`) and display numbers anywhere, every sign style
- `OCCURS` tables (`DEPENDING ON`, `INDEXED BY`), `REDEFINES`, groups, `FILLER`, `VALUE`, level-88 conditions
- Edited pictures such as `$$,$$9.99-`, `ZZ9.99CR`, `***,**9.99`
- `MOVE`, `COMPUTE`, `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`, `IF`, `EVALUATE`, `PERFORM` in every form, `GO TO`,
  `ON SIZE ERROR`, `STRING`, `UNSTRING`, `INSPECT`, `SEARCH`, `SEARCH ALL`, `SET`, `INITIALIZE`, reference modification,
  and intrinsic `FUNCTION`s such as `CURRENT-DATE`, `UPPER-CASE`, `TRIM`, `NUMVAL`

**Not yet:** indexed or relative files, `SORT`/`MERGE`, `EXEC SQL` and CICS, `CALL`, REPORT and SCREEN sections,
`COMP-1`/`COMP-2` and `P` scaling. A program that uses them is still accepted if it compiles; the statements the
translator cannot handle raise an error naming the COBOL line, so the check fails there instead of passing quietly.

**Real-world test:** the 30 programs of the Open Mainframe Project COBOL course
(github.com/openmainframeproject/cobol-programming-course). 20 of the 21 that GnuCOBOL can run translate with
no gaps and match the COBOL byte for byte; the other one calls a second program (`CALL`). The other 9 are lab
exercises with deliberate compile errors or an endless loop, or need DB2. Three of them ship as examples.

## How the Checking Works

- **Byte-accurate runtime:** the Python keeps every 01 record as bytes laid out the way GnuCOBOL lays them out, so
  packed decimal, binary, REDEFINES, tables and group moves behave the same. The encodings are differential-tested
  against GnuCOBOL.
- **A test case is a whole run:** the bytes of every input file plus the console input. Both programs run on it with
  the same fixed clock, and every output file, everything displayed, and the return code are compared.
- **Saved test sets:** edge cases from the layout (zero, smallest and largest values) and from the code (level-88
  values and every literal a field is compared against), random records, and any files you upload.
- **Random runs each check:** Hypothesis generates fresh input files and console input; the first failure is shrunk
  (fewer records, plainer values) within a fixed budget of COBOL runs.
- **Test strength:** planted bugs run in their own process with a time limit, so a bug that loops forever is caught.
- **Receipt:** each report records SHA-256 hashes of the COBOL and the Python, and the app says when either changed
  after the check.

## Settings

All in `seance/config.py`, read from the environment:

`SEANCE_ROUNDS`, `SEANCE_MAX_ROUNDS`, `SEANCE_VERIFY_TIMEOUT`, `SEANCE_COMPARE_TIMEOUT`, `SEANCE_MUTANTS`,
`SEANCE_MAX_DATA_RECORDS`, `SEANCE_RANDOM_RECORDS`, `SEANCE_RUN_TIMEOUT`.

## Security Model

Séance compiles and runs code you give it, so treat it like a local dev server.

- It binds to 127.0.0.1 and rejects requests addressed to any other host name, which blocks DNS rebinding.
- Every request that changes anything must be JSON and carry a random per-launch token that only the page it serves contains.
- The shipped examples are read-only. Only programs you add can be edited, redrafted or deleted.
- It does not sandbox your code beyond timeouts. Do not run COBOL or Python you do not trust, and do not expose the port.

## Kiro Integration

- **MCP server** (`seance/mcp_server.py`, registered in `.kiro/settings/mcp.json`) with these tools: `list_programs`, `describe_program`, `describe_layout`, `run_legacy_program` (input files and console input), `record_legacy_fixtures`, `draft_python`, `verify_migration`, `measure_test_strength`.
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
python -m pytest                          # 53 tests, including differential tests against GnuCOBOL
python scripts\ui_check.py                # 16 checks that drive the real UI in Edge (app must be running)
```

## Example Programs

| Program | What it exercises |
| --- | --- |
| accounts | Fixed format, DD names, a copybook, level-88 account types, `PERFORM VARYING`, `EVALUATE`, `ON SIZE ERROR`, an edited output field. |
| payroll | Per-step ROUNDED (half away from zero). Ships with a buggy hand-written float port that the check catches. |
| loan | `ON SIZE ERROR` on a payment that does not fit or a zero term, and exponentiation. Ships with a buggy port. |
| interest | Overdraft fee overflow flips -999,999,999.99 to -24.99. |
| inventory | Stock above 99,999 wraps, and shortfall backorders truncate to 5 digits. |
| account_report | Real course program CBL0011: a report with headers and totals over packed-decimal (`COMP-3`) records. |
| add_amounts | Real course program ADDAMT: an interactive console loop that runs until you answer NO. |
| table_search | Real course program SRCHBIN: an `OCCURS` table loaded from a file and searched with `SEARCH ALL`. |

The three course programs are CC-BY-4.0, unchanged; see `SOURCE.md` next to each.

## Limits

- Windows-first. The COBOL runtime is the MinGW build of GnuCOBOL 3.1.2.
- A pass is strong evidence, not a proof for every possible input. Test Strength shows where the evidence is thin.
- The translator and the description are rule-based, not an LLM. They never guess: what they cannot read is marked.
- `CALL` between programs and indexed files are the main things to add next.

License: MIT.
