# Séance

**Rewrite COBOL in Python, and prove it gives the same answers.**

Migrating COBOL rarely fails because the new code is hard to write. It fails because nobody can show the new code
behaves exactly like the old: the same rounding, the same truncation, the same signs, on every record. Séance runs the
original COBOL and the Python side by side and compares every output, byte for byte.

1. **Add your COBOL.** Drop the program, the programs it CALLs and its copybooks (or a JCL job). Séance compiles it with
   GnuCOBOL and records what it really does on edge cases, random records and the values it finds in the code.
2. **Get a Python draft.** A rule-based translator writes the Python statement by statement. Every line is tagged with
   the COBOL line it came from. Anything it cannot translate raises an error naming that line, so a check fails loudly
   instead of passing quietly.
3. **Check and measure.** Run the check against the real COBOL. Then measure test strength: Séance plants small bugs in
   the Python one at a time and shows which ones the saved records miss.
4. **Take it with you.** A standalone Python program with a `run.py` that processes a whole file the way the batch job
   did. It needs only Python 3.10 or newer.

## Quick Start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Put GnuCOBOL 3.1.2 (MinGW x64) in tools\gnucobol\ :
#   https://github.com/mridoni/gnucobol-binaries/releases  (gnucobol-3.1.2-windows-mingw-x64.7z)
.\scripts\run.ps1        # or: python -m seance serve   (opens http://127.0.0.1:8000)
```

Any `cobc` already on PATH also works. The workspace starts empty. The first time you open the app, the **guide** offers a
two-minute tour with a sample program, or you can add your own COBOL straight away.

## The App

**Finding your way**

| | |
| --- | --- |
| **Program list** (left) | Every program with its status dot and the status in words. Filter it, or hide it with `Ctrl B`. On a phone it is a drawer. |
| **Search** (`Ctrl K`, or `/`) | Jump to any program or run an action: add, check all, go to a tab, export, settings. |
| **Tabs** (`1` to `5`) | Overview, Code, Check, Try Input, Test Data. The address always shows where you are, so Back, Forward and reload work. |
| **Status line** | The last verdict, lines compared, coverage and age, visible on every tab. A check keeps running while you look at another program. |
| **Shortcuts** (`?`) | `A` add, `R` run the check, `[` and `]` previous and next program, `G` then `W` workspace. |

**Workspace.** Totals, filters by result (matched, restless, needs attention, not checked) and by kind (indexed, SQL, CICS,
JCL, CALL ...), sorting, list or cards, and **Check All** with progress.

**A program**

| Tab | What it does |
| --- | --- |
| **Overview** | Every file it reads, writes or updates with its record layout, and a line-numbered description generated from the COBOL. For a job: its steps, programs and data sets. |
| **Code** | COBOL beside Python, including the programs it CALLs. Click a Python line to find its COBOL line. Lines no saved run reaches are marked. Edit the Python in place (unsaved edits are kept when you change tab). |
| **Check** | "Spirit matched" or "Spirit restless", lines compared, random runs, coverage, a receipt (hashes of the COBOL, the Python and the test data), the smallest failing input and field-by-field differences. Also a mutation test. |
| **Try Input** | Type input or replay a saved set; both programs' output side by side. Databases and CICS screens are shown as tables and terminal screens. |
| **Test Data** | The saved sets, **Record Again**, and upload of your own files, ASCII or EBCDIC. |

**Export** gives the Python file, a standalone package, and the check report (Markdown or JSON). **Settings** covers density,
text size, animation, code display, random runs per check and the workspace defaults.

**The guide.** On first launch, and under Help at any time: a two-minute tour that loads a sample, runs a real check, then
runs a hand-written port that has a bug so you can watch it being caught. The sample library is part of the guide. Samples
become ordinary programs, and one click removes them all.

## Adding Your Work

- **A COBOL program:** drop it, the programs it CALLs and its copybooks anywhere on the page, or paste it. Fixed and free
  format both work. The name is filled in from PROGRAM-ID.
- **A JCL job:** drop the `.jcl` file. The programs it runs must already be in the workspace (found by PROGRAM-ID); SORT,
  IEBGENER and IEFBR14 are built in.
- **From the command line or Kiro:** put the files in `legacy/<name>/<name>.cbl` and run `python -m seance record <name>`
  and `python -m seance translate <name>`.

## Sample Library

Fifteen small programs ship in `samples/`, not in your workspace. The guide loads them on request.

| Group | Samples |
| --- | --- |
| Start here | payroll (with a buggy float port), accounts, loan (with a port that crashes), interest, inventory |
| Real programs | account_report (CBL0011), add_amounts (ADDAMT), table_search (SRCHBIN): unchanged Open Mainframe Project course programs, CC-BY-4.0, see `SOURCE.md` beside each |
| Files, CALL and SORT | customer_master (indexed), order_pricing (CALL), transaction_sort (SORT), seat_bookings (relative) |
| SQL, CICS and JCL | payment_posting (EXEC SQL), customer_inquiry (EXEC CICS), nightly_batch (a four-step job) |

```powershell
python -m seance samples list        # what is available, and what is loaded
python -m seance samples load payroll
python -m seance samples remove      # removes every loaded sample, nothing else
```

## What COBOL It Runs

The lists are served by `/api/about` and shown in the app, from `seance/config.py`.

**Works today:**

- Fixed and free format, including IBM-style source (a missing period after PROGRAM-ID is fixed and reported)
- Sequential, line sequential, **indexed** (VSAM KSDS style, with alternate keys) and **relative** files: READ by key,
  READ NEXT, START, WRITE, REWRITE, DELETE, INVALID KEY, FILE STATUS, OPTIONAL files
- **CALL** between programs in the same folder: LINKAGE SECTION, BY REFERENCE / BY CONTENT, GOBACK, EXIT PROGRAM,
  CANCEL, IS INITIAL, ON EXCEPTION, RETURN-CODE
- **SORT and MERGE** (USING/GIVING, INPUT/OUTPUT PROCEDURE with RELEASE and RETURN), and SORT of a table, which
  reproduces the C runtime's unstable order exactly
- Console programs (DISPLAY, ACCEPT)
- Packed (COMP-3), binary (COMP, COMP-5) and display numbers anywhere; OCCURS, REDEFINES, level-88s, COPY REPLACING
- MOVE, COMPUTE, arithmetic verbs, IF, EVALUATE, every PERFORM, GO TO, NEXT SENTENCE, STRING, UNSTRING, INSPECT,
  SEARCH, SEARCH ALL, SET, INITIALIZE, reference modification, intrinsic FUNCTIONs, edited pictures
- Mainframe data in **EBCDIC** (code pages 037, 1140, 500, 273, 1047), converted field by field: text and zoned
  numbers change code, packed and binary fields keep their bytes
- Floating point (COMP-1, COMP-2), P scaling (`999PP`, `VPP99`), CALL ... RETURNING, variable-length records
- **Embedded SQL** (EXEC SQL): SELECT INTO, cursors (DECLARE, OPEN, FETCH, CLOSE), INSERT, UPDATE, DELETE including
  WHERE CURRENT OF, SQLCA, WHENEVER, indicator variables, DSNTIAR
- **CICS** (EXEC CICS): READ (EQUAL, GTEQ, GENERIC, UPDATE), WRITE, REWRITE, DELETE, browsing (STARTBR, READNEXT,
  READPREV, ENDBR), SEND TEXT/MAP, RECEIVE/RECEIVE MAP, temporary storage and transient data queues, RETURN TRANSID with a
  COMMAREA, LINK, XCTL, ABEND, HANDLE CONDITION, HANDLE AID, RESP/RESP2, DFHRESP, DFHAID, the EIB
- **JCL jobs**: steps that run programs, SORT/DFSORT, IEBGENER and IEFBR14, COND and IF/THEN/ELSE, temporary data sets
  (`&&TEMP`) passed between steps, in-stream data

**How SQL and CICS run without a mainframe.** Like the IBM precompilers, Séance rewrites each EXEC SQL or EXEC CICS
into ordinary COBOL that CALLs a bridge, on the same source lines. The COBOL side links a small C bridge; the Python
side has a Python bridge with the same rules. Both work on one SQLite database, seeded the same way, so both
programs start from the same tables, VSAM files, queues and screens, and are compared on the state they leave. A
CICS transaction is replayed pseudo-conversationally: each RETURN TRANSID starts the next turn with the COMMAREA it
returned and the next screen the user typed (ENTER, PF keys, CLEAR, PA keys, with MAPFAIL where CICS gives it).
This proves the Python does what the COBOL does against the same data. It does not prove DB2-specific SQL
behaviour that SQLite does not share; SQL the bridge cannot run is reported, not guessed.

**Not yet:** IMS (EXEC DLI), REPORT and SCREEN sections, BMS map source (the symbolic map copybook is used), dynamic
CALL of programs that are not in the folder. A program that uses them is still accepted when it compiles;
untranslatable statements raise an error naming the COBOL line, so the check fails there instead of passing quietly.

**Real-world test:** the 30 programs of the Open Mainframe Project COBOL course. 24 translate with no gaps and match
byte for byte, including CBL0033, which CALLs another program, and the three DB2 programs CBLDB21, CBLDB22 and
CBLDB23. The other 6 cannot be checked: five are lab exercises with deliberate compile errors and one loops forever.

## How the Checking Works

- **Byte-accurate runtime:** every 01 record is a byte buffer laid out the way GnuCOBOL lays it out. Behaviour was
  measured with probe programs (file status codes, RETURN-CODE across CALL, sort stability, record initial values,
  edited-picture overflow).
- **A test case is a whole run:** every input file plus console input. Both programs run on it with the same fixed
  clock; every output file, everything displayed and the return code are compared. Indexed and relative files go
  in and out of the real COBOL through generated loader and unloader programs.
- **Saved sets:** edge values from the layout and from the code (level-88s, literals the program compares against and
  every WHEN of an EVALUATE), random records whose transaction keys are drawn from the generated master, a run with
  input files missing (when the program checks FILE STATUS), and any files you upload.
- **Random runs each check:** Hypothesis generates fresh input; the first failure is shrunk to the smallest input.
- **Coverage:** the saved runs are replayed under a line tracer; COBOL statements no run reaches are listed as
  needing review, because a difference there would go unseen.
- **Mutation test:** small bugs planted in the Python one at a time must each be caught by the saved runs.
- **Receipt:** SHA-256 of the COBOL source, the Python and the test data, so a verdict cannot be reused for other code.

## How It Compares

From public documentation (November 2026). Séance is a local, single-developer tool; the others are enterprise
platforms. Where they need a mainframe, a cloud account or a services contract, Séance runs on a laptop in seconds.

| | Séance | COBOL Phoenix | AWS Transform | IBM watsonx Code Assistant for Z | Google Dual Run |
| --- | --- | --- | --- | --- | --- |
| Translation | Rules, to Python | Rules, to Python | AI + rules, to Java | AI, to Java | AI, to Java/C# |
| Runs the original COBOL to get expected answers | Yes, locally (GnuCOBOL) | Yes, locally | No (uses mainframe data) | Records on z/OS | Yes, on the mainframe |
| Minimal failing input (shrinking) | Yes | Not documented | Not documented | Not documented | Not documented |
| Mutation testing | Yes | Yes | No | No | No |
| Statement coverage of the evidence | Yes | Yes | No | No | No |
| Hash receipt over code and test data | Yes | Partial | No | No | No |
| Indexed (VSAM-style) files | Yes | No | Yes | Yes | Yes |
| CALL, SORT | Yes | CALL only | Yes | Yes | Yes |
| EXEC SQL, CICS, JCL | Yes, on SQLite, both sides | No | Yes | Yes | Yes |
| Runs offline, free | Yes | Yes | No | No | No |

Sources: github.com/thosuperman/cobol-phoenix; docs.aws.amazon.com/transform; ibm.com/products/watsonx-code-assistant-z;
docs.cloud.google.com/mainframe-dual-run. Passing differential tests is strong evidence, not a proof for every input.

## Settings

In the app: **Settings** (gear icon), saved in the browser. For checks, in `seance/config.py`, read from the environment (`python -m seance serve --port N` changes the port):

`SEANCE_ROUNDS`, `SEANCE_MAX_ROUNDS`, `SEANCE_VERIFY_TIMEOUT`, `SEANCE_COMPARE_TIMEOUT`,
`SEANCE_MUTANTS`, `SEANCE_MAX_DATA_RECORDS`, `SEANCE_RANDOM_RECORDS`, `SEANCE_RUN_TIMEOUT`.

## Your Workspace

| Folder | What is in it |
| --- | --- |
| `legacy/<name>/` | The COBOL (or JCL), its copybooks and called programs |
| `fixtures/<name>/` | The saved runs of the real COBOL |
| `migrated/<name>.py` | The Python for it |
| `docs/specs/<name>.md` | The generated description |
| `build/` | Compiled programs and check reports (safe to delete) |

These are git-ignored here, so the product repository stays clean. Remove those lines from `.gitignore` if you want to
version your own migration work in this repository.

## Security Model

Séance compiles and runs code you give it, so treat it like a local dev server.

- It binds to 127.0.0.1 and rejects requests addressed to any other host name, which blocks DNS rebinding.
- Every request that changes anything must be JSON and carry a random per-launch token that only the page it serves contains.
- It does not sandbox your code beyond timeouts. Do not run COBOL or Python you do not trust, and do not expose the port.

## Kiro Integration

- **MCP server** (`seance/mcp_server.py`, registered in `.kiro/settings/mcp.json`) with these tools: `list_programs`,
  `describe_program`, `describe_layout`, `run_legacy_program` (input files and console input), `record_legacy_fixtures`,
  `draft_python`, `verify_migration`, `measure_test_strength`, `list_samples`, `load_sample`.
- **Steering** (`.kiro/steering/`): product rules and COBOL-to-Python rules.
- **Hook** (`.kiro/hooks/`): re-verifies when a file in `migrated/` is saved.
- **Spec** (`.kiro/specs/seance/`): requirements.

The venv Python path in `.kiro/settings/mcp.json` is absolute. Edit it if you clone the repo elsewhere.

## Command Line

```powershell
. .\scripts\env.ps1                       # GnuCOBOL on PATH for this shell
python -m seance serve                    # the app, on 127.0.0.1 only
python -m seance samples list             # the sample library
python -m seance analyze accounts         # what Séance understood about the program
python -m seance translate accounts       # write the Python draft
python -m seance verify accounts          # check it against the real COBOL
python -m seance mutate accounts          # measure test strength
python -m seance export accounts          # build\accounts_python.zip
python -m pytest                          # 124 tests, including differential tests against GnuCOBOL
python scripts\ui_check.py                # 59 checks that drive the real UI in Edge (app must be running, workspace empty)
python scripts\shots.py                   # screenshots of every main screen into build\shots
```

The tests load the sample library into the workspace for the run and remove it afterwards.

## Limits

- Windows-first. The COBOL runtime is the MinGW build of GnuCOBOL 3.1.2.
- A pass is strong evidence, not a proof for every possible input. Test Strength shows where the evidence is thin.
- The translator and the description are rule-based, not an LLM. They never guess: what they cannot read is marked.
- SQL and CICS run on SQLite through bridges, not on DB2 or a CICS region. Both programs see the same data, so a
  match proves the translation; it says nothing about DB2 behaviour SQLite does not share.
- HANDLE CONDITION and HANDLE AID take effect in source order, not in the order they run. That is the same for
  programs that set handlers before using them, which is the usual style; a program that sets them on different
  paths would need RESP instead.
- IMS and the REPORT and SCREEN sections are the main things to add next.

License: MIT.

Séance began as an entry to Kiroween 2026 (Resurrection). The earlier submission notes are in `docs/hackathon/`.
