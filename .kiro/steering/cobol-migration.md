# COBOL to Python migration rules

Apply when editing files under `migrated/`.

- Mirror every COBOL PIC store with `seance.cobol_num.store(value, digits, scale, signed, rounded)`.
  `digits` is the total digit count (integer + decimals). Use `rounded=True` only where the COBOL has ROUNDED.
- A COBOL COMPUTE without ROUNDED truncates. Without ON SIZE ERROR it also drops high-order digits.
- Never use `float`, `round()`, or banker's rounding. COBOL ROUNDED is half away from zero.
- Record classes come from `generated/<program>_records.py`. Do not edit them. Change the copybook and run `python -m seance generate <program>`.
- After a change, run `python -m seance verify <program>`. A mismatch means the Python is wrong, not the fixture.

## Use the MCP tools instead of guessing
- Before writing a migration, call `describe_program` and read the spec. Pay attention to the section on values that silently change.
- When unsure what the COBOL does for an input, call `run_legacy_program` with that input. Its output is the ground truth.
- Finish with `verify_migration`. Do not report a migration as done until the verdict is 'Spirit matched'.

