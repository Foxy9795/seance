# Séance design

Séance migrates a COBOL program to Python and proves the result matches the original by running both. This
document covers how the requirements in `requirements.md` are met. The numbers refer to those requirements.

## Pipeline

Each stage is a pure function over files, with one CLI entry point (`python -m seance <stage> <program>`).
The web app, the MCP server and the exported package call the same functions.

```
legacy/<p>/*.cbl *.cpy ──analyze──▶ ProgramModel          R1   seance/model.py, layout.py, cobol_src.py
        │                              │
        │                         record (GnuCOBOL)        R2   seance/recorder.py, cases.py → fixtures/<p>/<set>/
        │                              │
        │                         spec                     R3   seance/spec.py, analyze.py
        │                              │
        └────────translate─────────────▶ migrated/<p>.py   R4   seance/translate.py + rt.py, cobol_num.py, codec.py
                                       │
                               verify (saved sets + Hypothesis)   R5   seance/verify.py
                                       │
                          report (Markdown, HTML, JSON, JUnit)    R6   seance/report.py, export.py
```

`seance/rt.py` is the runtime the translated Python stands on. It keeps COBOL data as bytes in the layout the
copybook gives, so `PIC S9(7)V99 COMP-3` is packed decimal in memory, not a Python number that happens to print the
same. Every store goes through `cobol_num.store`, which truncates or rounds the way COBOL does (ROUNDED is half
away from zero, a COMPUTE without ROUNDED truncates, a missing ON SIZE ERROR drops high-order digits).

## Ground truth

Behavior is what the compiled original does, not what the source seems to say (steering `product.md`).
`recorder.compile_legacy` builds the COBOL with GnuCOBOL; `cases.run_cobol` runs it in a temporary folder with a
fixed clock (`COB_CURRENT_DATE`) so runs repeat. A saved set is the input files, the console input and every output
byte the COBOL produced. Sets are plain files under `fixtures/<program>/<set>/`, so they can be reviewed in git.

Set kinds: `edges`, `random` and `missing` (generated from the copybook layout), `yours-*` (uploaded data),
`golden-*` (output from a real mainframe run, which GnuCOBOL is also run on, so the report says whether GnuCOBOL
agrees), and `gap-*` (found by gap filling, below).

## Verification (R5, R6)

1. Replay every saved set through the Python and compare byte for byte (`verify.replay_sets`).
2. Generate fresh inputs with Hypothesis from the layout, run both programs, and shrink the first difference with a
   bounded number of COBOL runs (`verify.random_check`, `verify.shrink`). Hypothesis only generates; its own shrinker
   would rerun the COBOL thousands of times.
3. Report statement coverage of the saved runs, so lines no run reaches are called out.
4. Anything unmatched is listed as "needs human review". A verdict is `Spirit matched` or `Spirit restless`.
   The report carries a receipt: SHA-256 of the COBOL, the Python and the test data.

## Test strength and gap filling

Passing saved sets prove little if they never reach the code that matters. `mutate.py` plants one small bug at a
time (a comparison flipped, a constant bumped, ROUNDED toggled, `+` and `-` swapped) and replays the saved sets.
A survivor is a spot the tests cannot see.

`gapfill.py` then searches for an input that tells each survivor apart from the original:

- It watches the changed comparison while the original runs and measures how far the input is from the point where
  the change would matter (equal operands for `<=`/`<`, the window between 1500 and 1501 for a changed constant).
- It starts from the saved records, trims them, and walks one numeric field at a time toward that point. When no
  saved record reaches the code, it starts from the same Hypothesis generators the random check uses.
- An input that separates the two is shrunk, run through the real COBOL, and saved as a `gap-*` set if the COBOL
  agrees with the original Python. If the COBOL disagrees, the Python has a bug the saved sets missed; that is
  reported as a mismatch for human review and is never saved as a passing test.
- A comparison reached exactly at its edge on several different inputs without the output ever changing is
  reported as equivalent, with the evidence. Anything else unresolved is reported as needing human review.
- Each survivor is searched in its own process with a time limit, because a changed copy can loop forever.
- "Equivalent" needs the changed comparison reached at its edge on several different inputs, and the search varies text fields
  (record types, codes) as well as numbers, because a branch gated by a code can hide a difference from numbers alone.
  Mutations that are not comparisons (a constant in arithmetic, ROUNDED, + and -) are never called equivalent: reaching the code
  without a changed output says too little, so they stay "needs human review" until an input separates them.

## Embedded SQL, CICS and JCL

`sqlpre.py` and `cicspre.py` precompile `EXEC SQL` and `EXEC CICS` into plain COBOL `CALL`s to a bridge. The same
bridge exists in C (linked into the GnuCOBOL run) and in Python (`sqlbridge.py`, `cicsbridge.py`), both over SQLite,
so the original and the migration run against identical data. `jcl.py` runs batch jobs step by step, with SORT and
IEBGENER as shared Python on both sides.

## Surfaces

- **FastAPI** (`seance/api.py`): JSON routes, a per-session token, loopback only.
- **One static page** (`web/index.html`): vanilla JS, no build step, no network requests to other hosts. Dark,
  candlelit theme; colors keep WCAG AA contrast (`tests/test_ui_contrast.py`). Motion respects
  `prefers-reduced-motion` and the Animation setting.
- **MCP server** (`seance/mcp_server.py`): `describe_program`, `run_legacy_program`, `verify_migration` and the rest.
  Read-only tools are auto-approved; tools that write files are not.
- **CLI** (`seance/cli.py`): the stages, plus `serve`, `samples`, `check-all` (JUnit for CI) and `fill-gaps`.

## Correctness properties

These are the properties the tests and the check assert.

- P1. For every sample, the Python output equals the COBOL output for every saved set and every random run.
- P2. A change to a record layout is made in the COBOL and recorded again; the Python never carries its own layout.
- P3. No money value passes through `float` or `round()` (`scripts/check_rules.py`).
- P4. A mutation that survives is either closed by a new saved set, shown to be a real mismatch, judged equivalent
  with evidence, or listed for human review. It is never silently dropped.
- P5. Exported packages run without Séance installed and produce the recorded output.
- P6. Two programs that both stop with an error are the same only if the Python stopped with the runtime's own `CobolError`; any
  other Python exception is a difference (`cases.compare`).

## Decisions and rejected alternatives

- Analysis (business rules, Gherkin, lineage) is rule-based. Rejected: an LLM explanation step, because the product's
  claim is proof, and generated prose is not proof.
- The workspace starts empty; examples live in `samples/` and load through the guide. Rejected: shipping read-only
  examples inside the workspace, which could not be deleted or edited like a user's own programs.
- One static HTML file. Rejected: a bundler, to keep the project installable with nothing but Python.
- Gap filling steers with the program's own comparison operands. Rejected: relying on Hypothesis's targeted search
  alone, which cannot hit an exact-equality edge.
