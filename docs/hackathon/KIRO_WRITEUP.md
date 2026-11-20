# Kiro write-up (for the Devpost form)

Sentences in square brackets are questions only you can answer. Replace them with what happened in your sessions.
Judges read for specifics.

## What Séance is

Séance migrates COBOL to Python and proves each migration by running the original COBOL (GnuCOBOL) and the Python on
the same inputs and comparing every output byte. Category: Resurrection.

## What is new since the first version

- An empty workspace with a sample library behind a guided tour; every program, sample or yours, can be deleted.
- A rewritten app shell: command palette (Ctrl K), shortcuts, settings, assessment page, animation that honours reduced motion.
- Analysis from the COBOL alone: flow graph, business rules with Gherkin, data dictionary, lineage, migration waves.
- Parallel runs: mainframe output is the expected answer; GnuCOBOL is run too and the report says whether it agrees.
- Test strength by planted bugs, then **gap filling**: a search for inputs that catch the bugs the saved tests missed,
  with the real COBOL as judge. It found a real gap in payroll and correctly refused to call another one a gap.
- Embedded SQL, CICS and JCL; `check-all` with JUnit output; exported packages that carry their own pytest suite.
- `scripts/check_rules.py` checks the submission rules and the steering rules, and runs in the test suite.

## How Kiro was used

**IDE, CLI, Web, Crew**: Built in Kiro IDE.

**Spec-driven development**: `.kiro/specs/seance/` holds `requirements.md` (WHEN/THEN, R1 to R9), `design.md` (pipeline,
verification, gap filling, correctness properties, rejected alternatives) and `tasks.md` (status checked against the
repository). [How did the spec shape the build compared with vibe coding?]

**Steering**: `product.md` fixes the product principle (the proof is the product), the numeric rules (Decimal only,
never float), the stack and the theme. `cobol-migration.md` tells Kiro how to mirror COBOL storage with `store()`,
that a mismatch means the Python is wrong, and to finish with `verify_migration`. `scripts/check_rules.py` turns the
numeric and theme rules into a check that fails the build. [Which rule changed Kiro's output the most?]

**Hooks**: `verify-migration-on-save` re-runs the verifier whenever a file in `migrated/` is saved, so a wrong
migration is flagged at once. [Confirm it fired in your session, and what it caught.]

**MCP**: `seance/mcp_server.py` exposes 13 tools. `run_legacy_program` is the key one: Kiro asks the real COBOL what
it does for any input instead of guessing from the source. `fill_test_gaps` lets Kiro close test gaps itself.
Read-only tools are auto-approved; tools that write files are not.

**Property-based testing**: Hypothesis generates valid records from the copybook layout, runs the compiled COBOL and
the Python, and the first difference is shrunk to a small input. On the sample library:

- The naive `loan` port shrinks to one record of zeros: the COBOL finishes normally, the Python raises
  `ZeroDivisionError` (float division).
- The naive `payroll` port shrinks to hours 40.1 at 999.98: gross pay is 40149.20 in COBOL and 40149.19 with floats.

**Beyond the saved tests**: mutation testing plants bugs in the Python. On `payroll`, two of twelve survived. Gap
filling closed one (a bracket edge between 1500 and 1501, caught by a new saved set the COBOL confirms) and showed the
other (`<=` changed to `<` at 500) never changes the output, because the tax is continuous there. It reports that as
"likely equivalent", with the number of edge hits behind the claim, not as a pass.

**Custom agents / Powers**: None. The project defines no custom agents (`.kiro/` has steering, a hook, a spec and an MCP server).
