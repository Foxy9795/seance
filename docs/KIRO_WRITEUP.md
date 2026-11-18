# Kiro write-up (draft for the Devpost form)

Fill in the bracketed parts from your real experience before submitting. Judges read for specifics.

**IDE, CLI, Web, Crew**: [Which did you use? What differed?]

**Spec-driven development**: `.kiro/specs/seance/requirements.md` holds seven requirements in WHEN/THEN form (ingest, record ground truth, spec, generate, verify, report, demo programs). [Describe how the spec shaped the build compared to vibe coding.]

**Steering**: `product.md` fixes the product principle (the proof is the product), the numeric rules (Decimal only, never float) and the theme. `cobol-migration.md` tells Kiro how to mirror COBOL storage with `store()` and `size_error()` and to verify before declaring done. [Which rule changed Kiro's output the most?]

**Hooks**: `verify-migration-on-save` re-runs the verifier whenever a file in `migrated/` is saved, so a wrong migration is flagged immediately. [Confirm it fired in your session.]

**MCP**: `seance/mcp_server.py` exposes seven tools. The key one is `run_legacy_program`: Kiro can ask the real COBOL program what it does for any input instead of guessing from source. Without MCP, Kiro would infer rounding and truncation rules from reading code, which is where migrations go wrong.

**Property-based testing**: Hypothesis generates valid records from the copybook layout, runs both the compiled COBOL and the Python migration, and shrinks any difference to the smallest input. It shrank the payroll float-rounding bug to one input (7.5 hours at 0.01 per hour). The recorded edge cases caught the loan draft crashing on a zero term, and the property test found the rounding differences the edge cases missed.

**Custom agents / Powers**: [None used so far. Add if you use any.]

