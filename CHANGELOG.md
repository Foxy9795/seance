# Changelog

All notable changes to Séance. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
version numbers follow [Semantic Versioning](https://semver.org/).

## [1.2.6] - 2026-11-22
### Fixed
- **What it does** is never blank in the workspace list: with no header comment, it is worked out from the program (files read and written, paragraphs, decisions, calculations, loops).
- Dropping a data file where COBOL is expected (the page, or the Add dialog) says so and where it goes, instead of adding it as a copybook; a binary file, a file over 8 MB and a text file with no COBOL in it are refused, and an empty dialog is not left open.
- Test Data: a file over 64 MB gets a message, not an out-of-memory page; the file is read with `FileReader` (no second copy as text); the record limit for uploaded files is 100,000 (`SEANCE_MAX_DATA_RECORDS`).
### Added
- `seance bigcheck PROGRAM FILE`: runs the real COBOL and the Python on one input file of any size, compares every output byte and says where the first difference is (`--input`, `--code-page`, `--keep`).

## [1.2.5] - 2026-11-22
### Fixed
- A program that calls a FUNCTION (`FUNCTION CURRENT-DATE` and the like) failed on its second run in the same process with `KeyError: '_FN1'`: the temporary item for a function result stayed in the program's item table. Each run now starts clean.
- The loop guard stopped a correct program at 2,000,000 steps, so a file of more than 2 million records could not be run. The limit grows with the size of the input files (8 steps per input byte); a program with no input keeps 2,000,000.

## [1.2.4] - 2026-11-22
Everything still open from the 2026-11-21 review (`docs/review/2026-11-21/findings.md`), each measured against GnuCOBOL 3.1.2.
### Fixed
- Source: a UTF-8 byte order mark no longer stops a program loading; a tab in the first seven columns of fixed format moves the
  text to column 8, as cobc reads it; an empty `PROCEDURE DIVISION.` is a program that ends at once.
- `COPY x OF lib.name` accepts a library name with periods; a constant defined as another constant keeps its text value.
- Arithmetic: `0 ** -1` and `0 ** 0` follow libcob (0 and 1, no size error); COMP-1 and COMP-2 never raise ON SIZE ERROR.
  An expression inside a function argument is a temporary field laid out as `cob_alloc_field` does (zero padded binary, 38 extra
  places on a division), so `FUNCTION MAX(A + 1, 2)` prints as the COBOL does.
- DISPLAY: a negative zero (a small negative moved into a field with fewer decimals) prints as `+0`; a COMP-5 item with `V`
  prints the stored integer with no point.
- SPECIAL-NAMES: `SYMBOLIC CHARACTERS ... IN alphabet` counts the ordinal in that alphabet; an ordinal outside 1 to 256 is a
  clear error, not a crash.
- Declaratives: an error in file B inside file A's declarative runs B's declarative (only the same file is blocked from nesting).
- Workers: `--rounds 0` checks the saved runs only; the export package finds its runtime files when run from another folder;
  a Python run that never ends stops after 120 seconds and says so; `mutate` and `fill-gaps` say when a program has no saved runs.
- MCP: a loopback `Host` header without a port is accepted.
- Page: the home cards for Business rules, Data lineage and Record viewer open that view; the "smallest failing input" demo opens
  the buggy port; focus goes to the nearest thing left after a delete; field and button borders pass WCAG 1.4.11 (3:1).
- Reports say "Notes" where they said "Needs human review"; duplicated imports and templates in the export removed.
### Checked, not changed
- `CLOSE REEL` on an indexed or relative file, and `SAME RECORD AREA` for three files, already match GnuCOBOL 3.1.2 (measured with probes).
- The NIST COBOL-85 suite: 322 of 366 programs match.
### Not done
- IEBGENER pads or cuts records to the output `LRECL` only; it does not read a later program's `RECORD CONTAINS`.
- The 96th significant digit of the transcendental functions is rounded half up; no failing example has been found for GMP's own rounding.
## [1.2.3] - 2026-11-22
### Fixed (page)
- One progress bar for Check All, drawn smoothly; re-drawing the workspace no longer replays the fade-in (the blink) or throws
  the page to the top (select-all, row checkboxes); keyboard focus stays on the box that was clicked.
- Scrolling inside Settings or any dialog or menu no longer scrolls the page behind; the page no longer shifts a few pixels when a
  scrollbar appears; leaving a page closes a Where Used or Records dialog left open.
- Skip Tour works while a check is running; a check started from a tour step cannot run twice or move the tour twice.
- Clicking a Python line finds its COBOL line from continuation lines and `def` lines too, and scrolls the COBOL pane to it;
  lines of generated record layouts say they have no COBOL line.
- A server failure answers with what went wrong instead of "Internal Server Error".
- "Needs human review" is gone: a difference the gap search finds is "Bug found", an unreached line is "Not reached".
### Changed
- The product starts with an empty workspace and no sample library (set SEANCE_SAMPLES=1 to bring it back); the hard-coded
  example on the home page, the sample tour and the sample buttons are hidden without it. The feature cards open on your own program.
### Fixed (proof and runtime, from the Antigravity review of 1.2)
- A check no longer passes when the two sides stop with different file statuses, when a last line was left open (WITH NO
  ADVANCING) on one side only, or when a form feed stands where a line end should be.
- Saved runs record the hash of the COBOL they came from; a run recorded from other COBOL is reported as stale, not replayed as proof.
- A program's own notes (SQL, CICS, unseeded RANDOM ...) appear in its report.
- DIVIDE ... REMAINDER works from the quotient cut to the receiver's scale (never rounded), and ON SIZE ERROR guards the remainder.
- A COMP-5 item overflows at the end of its bytes, so ON SIZE ERROR sees it.
- HIGH-VALUE and LOW-VALUE follow the program collating sequence (measured); a table SORT keeps its COLLATING SEQUENCE phrase.
- Paragraphs after END DECLARATIVES are not part of the last declarative; a COPY on a line whose identifiers contain EXEC is expanded;
  HIGHEST/LOWEST-ALGEBRAIC counts PIC P positions; an exported package carries editing.py and intrinsics.py.

## [1.2.2] - 2026-11-22
### Added
- LINAGE, LINAGE-COUNTER (qualified by file) and `WRITE ... AT END-OF-PAGE / NOT AT END-OF-PAGE`, following libcob's
  page logic: top lines before the first record, a plain WRITE is AFTER ADVANCING 1, overflow pads the page, writes the
  bottom lines and opens the next with the top lines.
- READ PREVIOUS and START LAST (indexed and relative files), `WRITE record IN file`, RECORD VARYING ... DEPENDING ON.
### Fixed
- Sequential files: OPEN EXTEND of a file that does not exist gives 35; WRITE after OPEN I-O gives 48; REWRITE needs a
  successful READ just before (43) and a record of the size read (44); WRITE AFTER ADVANCING leaves the last line open
  and CLOSE ends it; ADVANCING 0 writes a carriage return.

## [1.2.1] - 2026-11-21
### Fixed
- Relative files: `RELATIVE key-name` without the word KEY, REWRITE of the record last read in sequential access (status 43 when no READ came first, as GnuCOBOL gives), status 46 on a second READ after the end, and `START ... KEY GREATER OR EQUAL TO`. NIST relative-file programs matching: 12 of 24 to 21.

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
- The NIST COBOL-85 test suite as a harness (`scripts/stress_nist.py`): 319 of 366 programs match GnuCOBOL byte for
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
