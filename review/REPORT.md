# Séance Review Report

**Verdict: ship after fixes**

Séance is an extraordinarily well-crafted, rigorous migration and verification workbench with 161 passing tests, deep differential testing against live GnuCOBOL, strict bounded sandboxing, and faithful decimal arithmetic. However, it cannot be shipped in its current state because of one Critical proof integrity defect that permits false "Spirit matched" certifications and saves broken tests into fixtures, three High severity translator semantic bugs, an exported test suite flaw, and unfilled submission write-up brackets. Once these specific findings are resolved, the repository is ready to ship.

---

## 1. Findings by Severity

### Critical
- **F2.1 / F3.1 Differing runtime errors between COBOL and Python are ignored, declaring "Spirit matched" and saving broken gap fixtures**
  - *Where*: `seance/cases.py:250`, `seance/gapfill.py:703`
  - *What happens*: In `compare()`, `if (expected.error is None) != (actual.error is None):` evaluates to `False` when both COBOL and Python stop with errors. Because the subsequent comparison block requires `and expected.error is None`, differing error strings and return codes are skipped entirely. `compare()` returns zero diffs, causing `Report.matched` to return `True` ("Spirit matched"). In `seance/gapfill.py`, this zero-diff result tricks the gap filler into certifying that original Python matched COBOL, permanently saving the broken run as a passing `gap-*` test fixture in `fixtures/<program>/`.

### High
- **F1.1 UNSTRING with pointer <= 0 slices from string end, mutates target with trailing char, and misses OVERFLOW**
  - *Where*: `seance/rt.py:1168`
  - *What happens*: When `pointer` is 0 or negative, `pos = int(self.n(pointer)) - 1` becomes negative (e.g. -1). Python slices `text[pos:]` from the string end, corrupts receiving targets with trailing characters, increments pointer to a positive value, and fails to signal `ON OVERFLOW`.
- **F1.2 Moving alphanumeric text with leading sign to numeric field stores zero**
  - *Where*: `seance/rt.py:1441`
  - *What happens*: In `_alpha_to_number`, when `lenient_sign=False` (used for `MOVE`), the loop immediately breaks upon encountering a leading `+` or `-` because `ch.isdigit()` is false, returning `Decimal(0)`.
- **F1.3 INSPECT REPLACING on signed numeric field strips negative sign**
  - *Where*: `seance/rt.py:1244`
  - *What happens*: `inspect_replace` uses `_text(ref)`, which calls `_digits_text` (omitting sign). Writing back via `self.move` treats the value as unsigned, flipping negative values to positive.
- **F2.2 Sequential binary/packed records containing 0x0A or 0x0C are split into arbitrary chunks**
  - *Where*: `seance/cases.py:196`
  - *What happens*: In `_units`, any non-line file containing byte `0x0A` (`\n`) or `0x0C` (`\f`) is routed to `_record_units`, which splits the byte stream assuming it is a print file with `WRITE ADVANCING`. In binary (`COMP`) or packed (`COMP-3`) sequential files, `0x0A` and `0x0C` are valid data bytes; splitting on them misaligns record framing.
- **F2.4 / F8.3 Standalone exported test suite catches any exception when COBOL had an error**
  - *Where*: `seance/export.py:94`
  - *What happens*: The exported test template executes `with pytest.raises(Exception):` for error fixtures. Any Python exception—including `ImportError`, `AttributeError`, or syntax crashes—satisfies the assertion and passes the test.
- **F6.1 Devpost write-up contains four unfilled bracketed placeholder questions**
  - *Where*: `docs/hackathon/KIRO_WRITEUP.md:24-36`
  - *What happens*: `scripts/check_rules.py` flags 4 bracketed author prompts in the submission write-up.
- **F8.1 Missing test coverage for differing runtime errors between COBOL and Python**
  - *Where*: `tests/test_pipeline.py:51`
  - *What happens*: No test in the test suite checks `compare()` when both COBOL and Python have non-None `error` attributes, allowing F2.1 to go undetected despite 161 passing tests.

### Medium
- **F2.3 Receipt cobol_sha256 only hashes main source file, ignoring copybooks and subprograms**
  - *Where*: `seance/report.py:22`
  - *What happens*: Hashing only the root `.cbl`/`.jcl` file means modifications to copybooks (`.cpy`) or called subprograms do not change the receipt hash.
- **F3.2 Equivalence threshold of four inputs does not detect downstream-gated branches**
  - *Where*: `seance/gapfill.py:49`
  - *What happens*: If a mutated comparison sets a flag whose output effect is gated by an untriggered categorical condition (e.g. record type), 4 inputs without that record type declare the mutant equivalent.
- **F5.1 Modal dialogs do not restore focus to triggering element on close**
  - *Where*: `web/index.html:1120`
  - *What happens*: Closing modal dialogs drops keyboard focus to `document.body` instead of returning to the button that opened the dialog, violating WCAG 2.1 SC 2.4.3.
- **F8.2 Unchecked corner cases in UNSTRING pointer boundaries and INSPECT sign handling**
  - *Where*: `tests/test_codec_vs_cobol.py:1`
  - *What happens*: Test suite lacks differential tests for `UNSTRING` with invalid pointer values and `INSPECT` on signed display fields.

### Low
- **F1.4 DIVIDE REMAINDER without GIVING produces invalid Python expression**
  - *Where*: `seance/translate.py:823`
  - *What happens*: Non-standard construct emits `None - S.n(...) * None`.
- **F3.3 Non-comparison mutations cannot record edge flips and remain perpetually "open"**
  - *Where*: `seance/gapfill.py:372`
  - *What happens*: Arithmetic mutations set `ev.flipped` but not `ev.edge`, preventing equivalence detection.
- **F4.1 TrustedHostMiddleware omits IPv6 loopback [::1]**
  - *Where*: `seance/api.py:44`
  - *What happens*: Requests to `http://[::1]:8000` return HTTP 400 Invalid Host.
- **F5.2 Several modal dialogs lack explicit initial focus assignment**
  - *Where*: `web/index.html:1130`
  - *What happens*: `setDlg`, `keysDlg`, `aboutDlg` open without focusing their primary control.
- **F7.1 Settings documentation omits SEANCE_HOST and SEANCE_PORT**
  - *Where*: `README.md:200`
  - *What happens*: `README.md` documents runtime check flags but omits server host and port environment variables.

### Note
- **F6.2 MCP server configuration holds absolute machine path**
  - *Where*: `.kiro/settings/mcp.json:4`
  - *What happens*: Holds hardcoded author path `C:\Users\siddh\...`; known author decision.

---

## 2. Reproductions of Critical and High Findings

### Reproduction: F2.1 / F3.1 (Proof Integrity / Gap Filling)
**Script**: `build/review/probe_verify_errors.py`
```python
from pathlib import Path
from seance.cases import Result, compare
from seance.model import ProgramModel
from seance.verify import Report

model = ProgramModel(name="TEST", path=Path("TEST.cbl"), fixed=True, program_id="TEST", files=[], fd_items={}, ws_items={}, proc_items={}, ws_records={}, accepts=[])
expected = Result(outputs={}, stdout="", return_code=1, error="CobolError: file not found")
actual = Result(outputs={}, stdout="", return_code=1, error="ZeroDivisionError: division by zero")

diffs, units = compare(model, expected, actual)
rep = Report(program="TEST", implementation="migrated.TEST")
rep.sets = [{"name": "test", "label": "test", "records": 0, "console_lines": 0, "compared": units, "differing": len(diffs), "python_error": actual.error, "cobol_error": expected.error}]
rep.diffs = diffs
print("diffs:", diffs)
print("units:", units)
print("rep.matched:", rep.matched)
```
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_verify_errors.py
diffs: []
units: 0
rep.matched: True
```
*Result*: Despite Python crashing with `ZeroDivisionError` while COBOL stopped on missing file, `diffs` is empty and `rep.matched` is `True` ("Spirit matched"). In `seance/gapfill.py:703`, `if not diffs:` evaluates to true, executing `save_set(...)` and certifying the broken case as a permanent passing test.

---

### Reproduction: F1.1 (UNSTRING pointer <= 0)
**Script**: `build/review/probe_unstring_ptr.py`
Compiles and runs `TUNSTR.cbl` with `PTR = 0`, then executes translated Python runtime `S.unstring(...)`.
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_unstring_ptr.py
COBOL output : 'TGT1=11111 TGT2=22222\n PTR=00 OVER=Y\n'
Python output: 'TGT1=H     TGT2=22222\n PTR=11 OVER=N\n'
```
*Result*: GnuCOBOL leaves targets untouched, leaves pointer at 00, and triggers `OVER=Y`. Python slices `text[-1:]` from end, corrupts `TGT1` with trailing `'H'`, increments pointer to 11, and fails to signal overflow (`OVER=N`).

---

### Reproduction: F1.2 (Alphanumeric signed move zeroing)
**Script**: `build/review/probe_translate_alpha.py`
Moves `"-123 "` from `PIC X(5)` to `PIC S9(5)` and `PIC 9(5)`.
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_translate_alpha.py
COBOL stdout : 'B=-00123 C=00123\n'
Python stdout: 'B=+00000 C=00000\n'
```
*Result*: GnuCOBOL parses the signed number `-00123`. Python's `_alpha_to_number` hits the leading `-` when `lenient_sign=False`, breaks immediately on `ch.isdigit()`, and stores zero.

---

### Reproduction: F1.3 (INSPECT REPLACING on signed field)
**Script**: `build/review/probe_inspect_num.py`
Initializes `PIC S9(5) SIGN LEADING SEPARATE` to `-12045` and runs `INSPECT N REPLACING ALL "0" BY "9"`.
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_inspect_num.py
COBOL output : 'N=-12945\n'
Python output: 'N=+12945\n'
```
*Result*: GnuCOBOL preserves the negative sign (`-12945`). Python inspects text formatted without sign via `_digits_text`, storing back `+12945`.

---

### Reproduction: F2.2 (Sequential binary record splitting)
**Script**: `build/review/probe_binary_record_split.py`
Passes a 20-byte file containing two 10-byte fixed binary records where record 1 contains `\n` (`0x0A`) at byte 4 to `_units(file_desc, data)`.
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_binary_record_split.py
len data: 20
units count: 3
unit 0: len=4 b'1234'
unit 1: len=10 b'67890ABCDE'
unit 2: len=5 b'FGHIJ'
```
*Result*: Rather than 2 units of length 10, the binary file is fragmented into 3 misaligned chunks of lengths 4, 10, and 5.

---

### Reproduction: F2.4 / F8.3 (Exported test suite catches all exceptions)
**Script**: `build/review/probe_export_exception.py`
Simulates exported test suite handling an error fixture when the Python migration raises an unexpected crash (`ZeroDivisionError`).
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe build\review\probe_export_exception.py
TEST PASSED: pytest.raises(Exception) caught completely unrelated Python crash!
```
*Result*: `with pytest.raises(Exception):` catches the unrelated crash and passes the test.

---

### Reproduction: F6.1 (Devpost write-up placeholder questions)
**Command & Output**:
```powershell
PS C:\Users\siddh\Desktop\Sid Project\Python\Kiro> . .\scripts\env.ps1; .\.venv\Scripts\python.exe scripts\check_rules.py
...
WARN  write-up on how Kiro was used
      4 bracketed question(s) only you can answer
```
*Result*: Lines 24, 28, 33, and 36 of `docs/hackathon/KIRO_WRITEUP.md` contain unedited author prompts.

---

### Reproduction: F8.1 (Missing test for differing errors)
**Evidence**: Inspection of `tests/test_pipeline.py:51-56`:
```python
@needs_cobol
def test_python_crash_is_reported_not_raised():
    report = verify("loan", "migrated.loan_naive", 5)
    assert not report.matched
    assert any("ZeroDivisionError" in (s["python_error"] or "") for s in report.sets)
```
Only cases where `expected.error is None` and `actual.error is not None` are tested. No test supplies mismatched non-None errors to `compare()`.

---

## 3. What Was Checked and Found Clean

1. **Sandboxing and Path Traversal**:
   - Program identifiers and copybook names are strictly validated by `NAME_RE` (`^[a-z][a-z0-9_]{1,23}$`) and `COPYBOOK_RE`.
   - File uploads in `seance/programs.py` sanitize input stems via `re.sub(r"[^a-z0-9]+", "-", ...)` and write strictly inside `fixtures/<program>/`.
   - Fixture removal strictly enforces `^(yours|golden|gap)-[a-z0-9-]{1,40}$`.
2. **Command Injection Safety**:
   - Subprocess executions (`cobc`, `python`) pass explicit argument lists with `shell=False`.
   - JCL utility steps (`IEBGENER`, `SORT`, `IEFBR14`) and dataset pipelines run in-memory within Python.
3. **Denial of Service and Upload Limits**:
   - Program source capped at 200 KB; test datasets capped at 5 MB text / 7 MB base64 (5,000 records).
   - Timeouts are strictly enforced on all executions (`COMPARE_TIMEOUT`, `RUN_TIMEOUT`, `VERIFY_TIMEOUT`).
4. **Timing Attacks and CSRF**:
   - Non-idempotent `/api/*` endpoints require timing-safe HMAC token comparison (`hmac.compare_digest`) with `app.state.token`.
5. **Accessibility and Visual Presentation**:
   - High-contrast candlelit theme passes WCAG AA contrast ratio (>= 4.5:1) verified by `tests/test_ui_contrast.py`.
   - System reduced-motion preference (`prefers-reduced-motion: reduce`) properly disables CSS animation durations, iteration counts, and animated JS counters.
   - Command palette dynamically anchors to the search button via `getBoundingClientRect()`.
   - Untrusted inputs and server error responses are sanitized with HTML entity escaping (`esc()`).
6. **Kiroween Hackathon Compliance**:
   - Working app in the **Resurrection** category.
   - Root `/.kiro` is tracked in git.
   - All sample legacy programs contain `SOURCE.md` attributing Open Mainframe Project CC-BY-4.0 license.
   - Timed demo script in `docs/hackathon/DEMO.md` runs under 3 minutes (2:45).
   - Test suite passes 161 tests.

---

## 4. What Was Not Checked

1. **Live Browser Automation via Playwright**:
   - `scripts/audit_ui.py` was not executed against an active live server in a headless browser, as review was conducted statically and through unit tests without spawning long-running background services.
2. **Exhaustive Mutation Sweeps Across All 15 Samples**:
   - Gap filling and mutation tests were executed on `payroll`, `accounts`, and `loan`. The remaining 12 sample programs were not put through full mutation search cycles.
3. **Non-PowerShell Environments**:
   - All verification scripts were executed under Windows PowerShell as mandated by project instructions. Bash / WSL / macOS runtime behaviors were not evaluated.
