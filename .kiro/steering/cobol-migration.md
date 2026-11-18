# COBOL to Python migration rules

Apply when editing files under `migrated/`.

- A migration is a module with `main(io)`. `io` holds the input files (`io.inputs`, `io.lines(name)`, `io.records(name, size)`)
  and console input; the program writes `io.outputs`, `io.stdout` and `io.return_code`. Translated programs keep
  COBOL data byte for byte through `seance.rt.Program`; prefer editing those over rewriting by hand.
- In hand-written code, mirror every COBOL PIC store with `seance.cobol_num.store(value, digits, scale, signed, rounded)`.
  `digits` is the total digit count (integer + decimals). Use `rounded=True` only where the COBOL has ROUNDED.
- A COBOL COMPUTE without ROUNDED truncates. Without ON SIZE ERROR it also drops high-order digits.
- Never use `float`, `round()`, or banker's rounding. COBOL ROUNDED is half away from zero.
- Record layouts come from the COBOL (FD, WORKING-STORAGE and copybooks). To change one, change the COBOL and run
  `python -m seance record <program>` and `python -m seance translate <program>`.
- After a change, run `python -m seance verify <program>`. A mismatch means the Python is wrong, not the saved test data.

## Use the MCP tools instead of guessing
- Before writing a migration, call `describe_program` and read the spec. Pay attention to the section on values that silently change.
- When unsure what the COBOL does for an input, call `run_legacy_program` with that input. Its output is the ground truth.
- Finish with `verify_migration`. Do not report a migration as done until the verdict is 'Spirit matched'.
