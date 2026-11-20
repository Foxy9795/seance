# Scope 2 Findings: Proof Integrity

Can the checker say "Spirit matched" when the programs differ?

---

### F2.1 Differing errors between COBOL and Python are ignored, declaring "Spirit matched"
Severity: Critical
Confidence: verified
Where: seance/cases.py:250
What happens: `compare()` checks `if (expected.error is None) != (actual.error is None):`. When both COBOL and Python raise errors, this condition evaluates to `False`. Because the `elif` branch requires `and expected.error is None`, differing error strings and return codes are skipped entirely. `compare()` returns zero diffs, leading `Report.matched` to return `True` ("Spirit matched").
Evidence: Ran `build/review/probe_verify_errors.py` where COBOL ended with `error="CobolError: file not found"` and Python crashed with `error="ZeroDivisionError: division by zero"`.
Output:
```
diffs: []
units: 0
rep.matched: True
```
Why it matters: This directly violates the product's core promise of mathematical proof. A crashing or misbehaving Python program is certified as "Spirit matched" as long as the COBOL run also encountered an error.
Suggested fix: In `seance/cases.py` lines 250-254, check `if expected.error != actual.error:` and append a `Diff("run", -1, expected.error or "finished normally", actual.error or "finished normally")`. Also compare return codes whenever errors differ.

---

### F2.2 Sequential binary/packed records containing 0x0A or 0x0C are split into arbitrary chunks
Severity: High
Confidence: verified
Where: seance/cases.py:196
What happens: In `_units`, any file with `f.organization != "line"` containing byte `0x0A` (`\n`) or `0x0C` (`\f`) is routed to `_record_units`, which splits the byte stream on `[\n\f]` assuming it is a print file with `WRITE ADVANCING`. In binary (`COMP`) or packed (`COMP-3`) sequential files, `0x0A` and `0x0C` are valid payload bytes; splitting on them misaligns record boundaries across arbitrary slices.
Evidence: Ran `build/review/probe_binary_record_split.py` on a 20-byte file with two 10-byte sequential records where record 1 contains `\n` at byte 4.
Output:
```
len data: 20
units count: 3
unit 0: len=4 b'1234'
unit 1: len=10 b'67890ABCDE'
unit 2: len=5 b'FGHIJ'
```
Why it matters: Record framing is corrupted, leading to false mismatches or mismatched comparisons when inspecting binary output data.
Suggested fix: In `_units`, check whether the file records contain non-display usage (or check if `WRITE ADVANCING` was actually used in the file definition) before treating newline characters as record delimiters in non-line files.

---

### F2.3 Receipt cobol_sha256 only hashes main program, ignoring copybooks and called subprograms
Severity: Medium
Confidence: verified
Where: seance/report.py:22
What happens: `receipt()` computes `"cobol_sha256"` by hashing only `root / "legacy" / r.program / f"{r.program}.cbl"`. Any changes to copybooks (`*.cpy`) or called subprograms in `legacy/<program>/` leave the receipt hash unchanged.
Evidence: Read `seance/report.py` lines 21-23:
```python
"cobol_sha256": _sha(root / "legacy" / r.program / f"{r.program}.cbl") or _sha(root / "legacy" / r.program / f"{r.program}.jcl"),
```
Why it matters: The receipt hash is intended to prove that the verified verdict corresponds uniquely to the code that produced it. Changing copybook layouts or subprogram business logic does not invalidate the receipt.
Suggested fix: Hash all source files (`*.cbl`, `*.cpy`, `*.jcl`) in `root / "legacy" / r.program /` sorted by path, or hash the entire legacy directory tree for that program.

---

### F2.4 Standalone exported test suite catches any exception when COBOL had an error
Severity: High
Confidence: verified
Where: seance/export.py:94
What happens: In `TEST_SUITE`, when a fixture has `meta.get("error")`, the generated test executes:
```python
if meta.get("error"):
    with pytest.raises(Exception):
        program.main(IO(files, meta["stdin"]))
    return
```
Any Python exception, including `SyntaxError`, `NameError`, `AttributeError`, or `TypeError`, satisfies `pytest.raises(Exception)` and marks the test as passing.
Evidence: Read `seance/export.py` lines 93-96.
Why it matters: The exported package promises a standalone pytest suite proving equivalence. A broken Python migration that crashes on import or initialization passes all error fixtures.
Suggested fix: Store the specific error class or error code in `meta["error"]` and assert that the Python exception matches or is a designated `CobolError`.
