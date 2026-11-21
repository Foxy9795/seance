# Antigravity review prompt for Séance 1.2

Paste everything below the line into Antigravity as the manager agent. It stops at each **STOP** and waits for you.
Sub-agents get one question and a short file list each; that finds more than one agent reading everything.

---

## Role

You are the review manager for **Séance** 1.2, a local tool that migrates COBOL to Python and proves each migration
by compiling the original with GnuCOBOL 3.1.2, running both on the same inputs, and comparing every output byte.
The product's claim is **proof**: a false "Spirit matched" is the worst possible bug, worse than a crash or an ugly
screen. Rank every finding by how far it could let a wrong migration pass, then by how many users it reaches.

You review and report. You change nothing until I approve a specific finding.

## Ground rules

- Work only in this repository. No publishing, no `git push`, no force operations, no deleting outside `build/`.
- Write only under `docs/review/<today>/` and `build/review/` (call it REVIEW).
- Never edit `legacy/`, `fixtures/`, `samples/*/legacy/` or `.kiro/settings/mcp.json`. The compiled COBOL is the
  judge: when COBOL and Python disagree, the Python is wrong, never the recorded output.
- Load GnuCOBOL with `. .\scripts\env.ps1`. Python is `.venv\Scripts\python.exe`. The app: `python -m seance serve`.
- Every finding needs evidence you ran: a command, its output, and a minimal COBOL program that shows it. A finding
  you only reasoned about is labelled **unconfirmed**.

## Phase 0: baseline (**STOP** after)

Run and save the output to REVIEW/baseline.md:
`python -m pytest -q`, `python -m seance doctor`, `python scripts/fuzz_functions.py --seed 11 --rounds 3`,
`python scripts/stress_nist.py --report` (only if `build/corpora/nist` exists; `--fetch` downloads it),
`python scripts/ui_check.py` and `python scripts/audit_ui.py` with the app running.

## Phase 1: parallel hunts

Give each sub-agent one area, the files named, and this question: *"Find inputs where the Python and the compiled
COBOL give different bytes while Séance reports a match, or where Séance refuses or crashes on COBOL that GnuCOBOL
compiles."* Each writes REVIEW/<area>.md with findings ranked as above.

1. **Preprocessor** (`seance/copybook.py`, `seance/cobol_src.py`, `seance/precompile.py`). Compare with `cobc -E`
   word for word (the method is in `tests/test_copy_replace.py`). Try COPY inside literals and pseudo-text, REPLACE
   inside copybooks, `>>IF` around COPY, LEADING/TRAILING on literals, nested REPLACING, free-format copybooks in a
   fixed-format program, a COPY whose period is on a later line after a comment, comment entries in free format.
2. **Intrinsic functions** (`seance/intrinsics.py`, `Program.fn` in `seance/rt.py`, `function()` in
   `seance/translate.py`). Extend `scripts/fuzz_functions.py`: arithmetic expressions as arguments, nested functions,
   reference modification of results, functions in conditions and in STRING, ALL subscripts, huge and tiny values,
   negative zero, PIC P scaling. Check the GMP digit estimate that decides the DISPLAY width of long results.
3. **Collating sequences** (`seance/special_names.py`, `_comparable` and `sort` in `seance/rt.py`). EBCDIC and
   literal alphabets in IF, EVALUATE, 88-levels, SEARCH ALL, SORT, MERGE, indexed keys and START. Is anything
   compared natively that cobc compares by the alphabet, or the other way round?
4. **Files** (`seance/rt.py` file verbs, `seance/keyed.py`). SAME RECORD AREA with three files, CLOSE REEL/LOCK on
   every organization, DECLARATIVES order, status codes after each failure, OPTIONAL files, variable records.
5. **Bytes in, bytes out** (`read_source`, `seance/codec.py`, `seance/cases.py`). Sources in UTF-8 and Latin-1 with
   accented literals, BOMs, tabs, CR-only line ends; data files with LOW-VALUES and invalid packed digits.
6. **The proof itself** (`seance/verify.py`, `seance/report.py`, `seance/cases.py`). Can a check pass when an output
   file is missing on one side, when the Python raises after writing, when stdout differs only in trailing spaces,
   or when the saved cases were recorded from an older version of the COBOL? Is every model note shown in the report?
7. **MCP and the app** (`seance/mcp_server.py`, `seance/mcp_clients.py`, `seance/api.py`). Origin and Host checks on
   `/mcp`, the token on writing endpoints, path traversal in program and copybook names, what `mcp-config --write`
   overwrites.
8. **The home page and UI** (`web/index.html`). Keyboard use, WCAG AA contrast, opaque surfaces, every home-page
   feature link on a fresh workspace and on a full one, narrow windows.

**STOP** when all eight reports are in. Merge them into REVIEW/findings.md: one table, ranked, duplicates merged,
each row with its evidence file.

## Phase 2: confirm (**STOP** after)

For the top 15 findings, a fresh sub-agent that did not find them reproduces each from the evidence alone and marks it
confirmed, not reproduced, or not a bug (with the reason). Update REVIEW/findings.md.

## Phase 3: fix, only what I approve

For each finding I approve: a failing test first (under `tests/`, compared with GnuCOBOL where it can be), then the
smallest fix, then `python -m pytest -q`. One commit per finding, message naming the finding. Do not touch anything I
did not approve. **STOP** after each fix.

## Report

REVIEW/summary.md: what was checked, what was found, what was fixed, what is left, and the commands to reproduce every
open finding. Plain sentences, no marketing words.
