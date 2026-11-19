# Séance requirements

## R1. Ingest
As a developer, I give Séance a COBOL program and its copybooks, so it can analyze them.
- WHEN a `.cbl` file and optional `.cpy` files are provided THEN the system SHALL list data items, paragraphs, and file I/O.
- IF the source cannot be parsed THEN the system SHALL report the line and reason and stop.

## R2. Record ground truth
- WHEN sample input files are provided THEN the system SHALL compile and run the original program with GnuCOBOL and store inputs and outputs as fixtures.
- The system SHALL generate additional inputs from the copybook layout (boundaries, zeros, max values, negative signs).

## R3. Spec
- The system SHALL produce a plain-English spec of each paragraph, linked to source line numbers.

## R4. Generate
- The system SHALL generate a Python module that reads and writes the same record layouts.
- Numeric fields SHALL use `Decimal` with the rounding mode observed in recorded outputs.

## R5. Verify
- The system SHALL replay every fixture against the Python module and compare byte for byte.
- The system SHALL run property-based tests that feed random valid records to both programs and compare outputs.
- IF outputs differ THEN the report SHALL show the input, both outputs, and the first differing field.
- The system SHALL measure how strong the saved test sets are by planting small bugs in the Python and replaying the sets.
- WHEN a planted bug survives THEN the system SHALL search for an input that tells it apart from the original, check that input against the real COBOL, and save it as a test set only if the COBOL agrees with the original Python.
- IF the COBOL disagrees with the original Python on that input THEN the system SHALL report a mismatch needing human review and SHALL NOT save it as a passing test.
- IF no input can be found THEN the system SHALL say so, label the change equivalent only when its edge was reached on several inputs without the output changing, and otherwise mark it as needing human review.

## R6. Report
- The report SHALL show: matched fixtures, property-test runs, mismatches, and items needing human review.
- The report SHALL be viewable in the web UI and exportable as Markdown.

## R7. Demo programs
- The repo SHALL include three COBOL programs: payroll, inventory batch, and bank interest.
- At least one program SHALL contain a deliberate edge case (rounding or sign handling) that a naive migration gets wrong.
## R8. Product
- The workspace SHALL start empty. Sample programs SHALL load only through the guide or the `samples` command, and SHALL be deletable like any other program.
- WHEN the user prefers reduced motion THEN the UI SHALL stop animating and keep every piece of information visible.
- The UI SHALL keep WCAG AA contrast and label results `Spirit matched` and `Spirit restless`.
## R9. Submission
- The repository SHALL contain `.kiro/` (steering, hooks, specs, MCP settings), an OSI-approved license, install instructions, and a demo script under three minutes.
- Third-party programs SHALL be unchanged and attributed with their license.
- `scripts/check_rules.py` SHALL fail when a rule above is broken.
