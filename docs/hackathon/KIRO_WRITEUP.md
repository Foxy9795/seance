# Kiro write-up (for the Devpost form)
Sentences in square brackets are questions only you can answer. Replace them with what happened in your sessions.
Judges read for specifics.

## What Séance is
Séance migrates COBOL to Python and proves each migration by running the original COBOL (GnuCOBOL) and the Python on
the same inputs and comparing every output byte. Category: Resurrection.

## What it does today (version 1.2.11)
- **A dashboard, not a manual.** Drop programs, copybooks and JCL anywhere on the page (several at once); each program takes
  the copybooks and CALLed programs from the same drop. A missing copybook is reported with a Locate button. After an import
  the page shows programs, copybooks, JCL jobs, SQL blocks and CALL relationships, a five-step wizard (import, analyze,
  translate, verify, export) that names the next action, and a health score.
- **Proof.** Both programs run on edge values, random records and your own data (any size; `seance bigcheck` for a whole file);
  a difference shrinks to the smallest input. A false "Spirit matched" is treated as the worst bug.
- **Evidence beyond the saved tests.** Mutation testing plants bugs in the Python; *Generate missing tests* searches for inputs
  that catch the ones the tests missed, with the real COBOL as judge.
- **Analysis** from the COBOL alone (flow, business rules as Gherkin, data dictionary, lineage, migration waves); embedded SQL,
  CICS and JCL; exported packages that carry their own pytest suite; JUnit output for CI.
- **Measured against GnuCOBOL**, not against opinion: 325 of the 366 NIST COBOL-85 programs match byte for byte
  (`docs/STRESS_NIST.md`), 275 tests pass, and fourteen small programs in `tests/probes/` run on both sides.

## How Kiro was used
**IDE, CLI, Web, Crew**: Built in Kiro IDE. The whole project was built in the IDE. The CLI, Web and Crew clients were not used.
**Spec-driven development**: `.kiro/specs/seance/` holds `requirements.md` (WHEN/THEN, R1 to R9), `design.md` (pipeline,
verification, gap filling, correctness properties, rejected alternatives) and `tasks.md` (status checked against the
repository). The spec fixed the order of work (analyze, record, generate, verify) and the definition of done before any code was written, so each later change could be checked against a requirement and a task instead of a feeling. Each requirement names its test, which is why the test suite grew with the features.
**Steering**: `product.md` fixes the product principle (the proof is the product), the numeric rules (Decimal only,
never float), the stack and the theme. `cobol-migration.md` tells Kiro how to mirror COBOL storage with `store()`,
that a mismatch means the Python is wrong, and to finish with `verify_migration`. `scripts/check_rules.py` turns the
numeric and theme rules into a check that fails the build (a `float()` in the runtime failed it once, and was fixed).
The rule that a mismatch means the Python is wrong, never the saved test data, changed the most: fixes went into the Python or the translator every time, and fixtures were never edited to make a result pass.
**Hooks**: `verify-migration-on-save` re-runs the verifier whenever a file in `migrated/` is saved, so a wrong
migration is flagged at once. The hook is configured and enabled in `.kiro/hooks/`. It tells Kiro to fix the Python and never to edit fixtures or the COBOL.
**MCP**: `seance/mcp_server.py` exposes 14 tools (stdio, HTTP, and inside the app). `run_legacy_program` is the key one: Kiro
asks the real COBOL what it does for any input instead of guessing from the source. `fill_test_gaps` lets Kiro close test
gaps itself. Read-only tools are auto-approved; tools that write files are not. The settings are written for nine agents,
with a portable form that names no folder of the machine.
**Property-based testing**: Hypothesis generates valid records from the copybook layout, runs the compiled COBOL and
the Python, and the first difference is shrunk to a small input. On the `loan` and `payroll` sample programs:
- The naive `loan` port shrinks to one record of zeros: the COBOL finishes normally, the Python raises
  `ZeroDivisionError` (float division).
- The naive `payroll` port shrinks to hours 40.1 at 999.98: gross pay is 40149.20 in COBOL and 40149.19 with floats.
**Beyond the saved tests**: mutation testing plants bugs in the Python. On `payroll`, two of twelve survived. Gap
filling closed one (a bracket edge between 1500 and 1501, caught by a new saved set the COBOL confirms) and showed the
other (`<=` changed to `<` at 500) never changes the output, because the tax is continuous there. It reports that as
"likely equivalent", with the number of edge hits behind the claim, not as a pass.
**Review loop**: a second AI agent (Antigravity) reviewed each release independently and produced written findings
(`docs/review/`). Each finding was reproduced on GnuCOBOL before it was fixed in Kiro, and each fix became a test or a probe
program, so the same bug cannot come back. It made the written finding plus a reproducing probe the unit of work: Kiro is asked to fix one reproduced finding at a time, and it is done only when the probe passes on both sides.
**Custom agents / Powers**: None. The project defines no custom agents (`.kiro/` has steering, a hook, a spec and an MCP server).

## What was not written here
The three course programs in `samples/` are CC-BY-4.0 and unchanged (see `THIRD_PARTY.md`). GnuCOBOL and the NIST suite are
downloaded when used, not stored in the repository.
