# Séance: product steering

Séance migrates legacy COBOL programs to Python and proves the migration is correct.
The proof is the product. Code generation alone is not.

## Principles
- Behavior is defined by what the original program does when run, not by what we think the source says.
- Every migrated program ships with a verification report: recorded legacy outputs, generated tests, property-based tests, and a list of anything not matched.
- Never hide a mismatch. Unmatched behavior is reported as "needs human review".
- Money uses `decimal.Decimal` with explicit rounding that mirrors COBOL `COMP-3` / `PIC 9(n)V99` semantics. Never use `float`.
- Fixed-width records are parsed from the copybook layout, not guessed.

## Stack
- Python 3.12, `hypothesis` for property-based tests, `pytest`.
- Backend: FastAPI. Frontend: one static HTML file with vanilla JS (no build step).
- Legacy runtime: GnuCOBOL (`cobc`), invoked through a small MCP server so Kiro can run the original program.

## Style
- Small modules, type hints, no global state.
- Every pipeline stage (analyze, record, generate, verify) is a pure function over files plus one CLI entry point.

## Theme
- Dark, candlelit UI. Test result labels: "Spirit matched" / "Spirit restless".
- Theme must never hide information. Colors must keep WCAG AA contrast.

