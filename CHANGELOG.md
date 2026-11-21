# Changelog

All notable changes to Séance. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
version numbers follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-21
### Added
- Home page: what Séance does, how to add a program, every feature with a one-click way to open it on a sample, the
  sample library, MCP settings for nine clients, and what runs today.
- MCP server for any client: a launcher with no machine paths (`python scripts/seance_mcp.py`), HTTP at `/mcp` in the
  app and standalone (`seance mcp --http`), and `seance mcp-config --client NAME|all --mode local|portable|http [--write]`.
- COPY and REPLACE done in one pass the way cobc does them, checked word for word against `cobc -E` on 470 programs.
- 65 intrinsic functions ported from libcob, with `scripts/fuzz_functions.py` comparing them with GnuCOBOL.
- ALPHABET, PROGRAM COLLATING SEQUENCE and SORT/MERGE COLLATING SEQUENCE; SAME RECORD AREA; DECLARATIVES; numeric
  paragraph names; ALTER; CORRESPONDING; RENAMES; SPECIAL-NAMES; edited pictures rebuilt and measured.
- The NIST COBOL-85 test suite as a harness (`scripts/stress_nist.py`): 294 of 366 programs match GnuCOBOL byte for
  byte (`docs/STRESS_NIST.md`).
### Changed
- Menus, header, toasts and dialogs are opaque.
- COBOL sources are read one character per byte, so literals with accented letters keep the bytes cobc compiled.
- IDENTIFICATION DIVISION comment entries are left out as cobc leaves them out.

## [1.1.0] - 2026-11-20

### Added
- The command bar searches the code as well as programs and actions. Choosing a name opens **Where Used**: every line in
  the workspace that defines, changes or reads it, grouped by program, each one a link into the code (`/api/xref`, and the
  `where_used` MCP tool, which only reads and is auto-approved in a newly written MCP config).
- **View Records** on the Test Data tab: any saved input or output file split into the fields of its record layout, with
  CSV export (`/api/records`).
- Translator: compiler directives (`>>IF`, `>>ELIF`, `>>ELSE`, `>>DEFINE`, `>>SOURCE FORMAT`, `$SET`), `REPLACE` (with `ALSO`,
  `LEADING`, `TRAILING` and `OFF`), level-78 and `CONSTANT` items, debugging lines under `WITH DEBUGGING MODE`,
  `DECIMAL-POINT IS COMMA`, several programs in one source file, `DELETE FILE`, and `LENGTH OF`. GnuCOBOL's own test programs
  now match 165 of 464 (36%), up from 141 (`docs/STRESS.md`).

### Changed
- The search button and the command bar are the same box: it opens in place, at the same size, font and position, and only
  the results slide in beneath it. Dropdowns open at the size of their field. Motion is shorter and calmer everywhere.
- A new look: layered surfaces, tinted stat tiles with a verification bar, a stronger verdict, larger titles.
- The plain-English description follows `EVALUATE` of a field ("When IN-CLASS is "F": copies .050 into WS-RATE"), reads
  cases written on one line, and covers GO TO, CALL, STRING, UNSTRING, INSPECT, SEARCH, SORT, SET and the GIVING forms.

### Fixed
- Deleting a program now also deletes its check history, so a new program of the same name starts clean.
- A level-88 with one value was described as "'Y' to None".
- The Overview cut long record layouts off after a few fields.

## [1.0.0] - 2026-11-20

First release.

### Proof
- Every check replays each saved run of the real COBOL (compiled with GnuCOBOL 3.1.2) through the Python and compares
  every output file, everything displayed and the return code, byte for byte. Then Hypothesis generates fresh input
  from the record layouts, runs both programs, and shrinks the first difference to the smallest input that shows it.
- Statement coverage of the saved runs, with the COBOL lines no run reaches listed as needing review.
- A receipt with each verdict: SHA-256 of the COBOL (including copybooks and called programs), the Python and the test data.
- Test strength by planted bugs, and gap filling: for each planted bug the saved runs miss, a search for an input that
  tells it apart from the original. Inputs the real COBOL agrees with are saved as test sets; an input where the COBOL
  and the original Python disagree is reported as a real mismatch and never saved. A change that never alters the
  output at its edge is reported as likely equivalent, with the evidence.
- Parallel runs against output from your own mainframe, with GnuCOBOL run on the same data so the two can be compared.
- Check history, and reports as Markdown, HTML, JSON and JUnit (`seance check-all --junit` for a build pipeline).

### Translation
- A rule-based COBOL-to-Python translator over a byte-accurate runtime: DISPLAY, COMP-3, COMP, COMP-5, COMP-1/2,
  BINARY-CHAR to BINARY-DOUBLE, tables and REDEFINES, sign positions, P scaling, edited pictures, ROUNDED and the
  ROUNDED MODE phrases, ON SIZE ERROR, STRING, UNSTRING, INSPECT, SORT and MERGE, CALL with LINKAGE, indexed,
  relative, sequential and line-sequential files, PERFORM in all its forms including FOREVER.
- Embedded SQL and CICS through precompilers and shared bridges in C and Python, both on SQLite; JCL batch jobs with
  SORT and IEBGENER steps.
- Every Python line names the COBOL line it came from. A statement the translator cannot handle raises an error naming
  that line, so a check fails there instead of passing quietly. Known gaps are stated when a program is added.
- A stress test over GnuCOBOL's own test programs (`scripts/stress_translate.py`, results in `docs/STRESS.md`).

### Understanding
- Paragraph flow graph, dead code, complexity, business rules in plain English with Gherkin, data dictionary, field
  lineage and dependencies, all from the source with no model involved.
- An assessment of the whole workspace with migration waves, as a table, a graph and CSV.

### The app
- A local web app: program list, command palette (Ctrl K) that opens at the search button, keyboard shortcuts,
  settings, a guided tour with a sample library, and an empty workspace to start from. Each action is offered in
  one place. Animation follows the reduced-motion setting; colors keep WCAG AA contrast.
- Standalone export: the Python with its runtime, a `run.py` for whole files, and a pytest suite of every saved run.
- A setup check in the About dialog, and a notice when the open page is older than the server.

### Setup and tooling
- `pip install -e .` gives a `seance` command. `scripts\setup.ps1` does everything on Windows: the virtual
  environment, GnuCOBOL 3.1.2 (downloaded and checked against a fixed SHA-256), and a setup check.
- `seance setup`, `seance doctor`, `seance --version`, and an overview of the commands when `seance` runs with no arguments.
- Tested from a fresh clone with no GnuCOBOL on the machine: `scripts\setup.ps1` downloads, checks and unpacks it, then the
  whole test suite passes.
- An MCP server with 13 tools, so Kiro can describe programs, run the real COBOL, draft, check and strengthen tests.
  `seance setup --mcp-config` points Kiro's settings at the folder it runs in.
- `scripts/check_rules.py` checks the repository against the Kiroween rules and the project's steering rules.

### Fixed before release
An independent review (`docs/review/2026-11-20/`) found these; each has a test in `tests/test_review_fixes.py`:
- Two programs that both stopped with an error compared as equal, so a Python crash could pass. Now only the
  runtime's own `CobolError` counts as the same stop.
- Binary and packed record files were split at bytes 0x0A and 0x0C as if they were print files.
- UNSTRING with a pointer outside the sending field, MOVE of text with a sign or a decimal point to a number, and
  INSPECT on signed numbers did not match GnuCOBOL.
- The exported test suite accepted any exception where the COBOL had stopped.
- The receipt hashed only the main source file.
- Requests to `http://[::1]` were refused; dialogs did not return focus to the control that opened them.

### Known limits
See "Limits" in the README: Windows first, `DECIMAL-POINT IS COMMA`, compiler directives, REPLACE and nested programs
are not translated yet, gap filling does not cover SQL and CICS programs, and IMS, REPORT and SCREEN sections are not
supported.
