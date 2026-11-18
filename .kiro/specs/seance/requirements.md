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

## R6. Report
- The report SHALL show: matched fixtures, property-test runs, mismatches, and items needing human review.
- The report SHALL be viewable in the web UI and exportable as Markdown.

## R7. Demo programs
- The repo SHALL include three COBOL programs: payroll, inventory batch, and bank interest.
- At least one program SHALL contain a deliberate edge case (rounding or sign handling) that a naive migration gets wrong.
