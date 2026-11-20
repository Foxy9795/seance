# Scope 1 Findings: Translator Semantics

Where does the translated Python differ from what GnuCOBOL does, for a construct the tests do not cover?

---

### F1.1 UNSTRING with pointer <= 0 slices from end of string and misses OVERFLOW
Severity: High
Confidence: verified
Where: seance/rt.py:1168
What happens: When `pointer` is 0 or negative, `pos = int(self.n(pointer)) - 1` becomes negative (e.g. -1). Python slices `text[pos:]` from the end of the string, mutating receiving targets with trailing characters, updating pointer to a positive value, and failing to signal `ON OVERFLOW`.
Evidence: Running `build/review/probe_unstring_ptr.py` against GnuCOBOL on `TUNSTR.cbl` with `PTR = 0`:
- GnuCOBOL output: `TGT1=11111 TGT2=22222 PTR=00 OVER=Y` (receiving fields untouched, pointer unchanged, overflow triggered)
- Séance Python output: `TGT1=H     TGT2=22222 PTR=11 OVER=N` (target corrupted with trailing 'H', pointer incremented to 11, overflow not triggered)
Why it matters: Programs relying on UNSTRING input boundary checks or error handling silently execute corrupted logic instead of taking error branches.
Suggested fix: In `seance/rt.py`, add an explicit guard at the top of `unstring`: if `pointer is not None and (pos < 0 or pos >= len(text))`, immediately return `False` without modifying receiving targets or pointer.

---

### F1.2 Moving alphanumeric text with leading sign to numeric field stores zero
Severity: High
Confidence: verified
Where: seance/rt.py:1441
What happens: In `_alpha_to_number`, when `lenient_sign=False` (used for `MOVE`), the function checks `ch.isdigit()`. A leading `+` or `-` fails this check immediately and breaks the loop, returning `Decimal(0)`.
Evidence: Running `build/review/probe_translate_alpha.py` on `TMOVE.cbl` moving `"-123 "` from `PIC X(5)` to `PIC S9(5)`:
- GnuCOBOL output: `B=-00123 C=00123`
- Séance Python output: `B=+00000 C=00000`
Why it matters: COBOL programs moving formatted or signed alphanumeric records into numeric computation fields silently zero out the numbers.
Suggested fix: In `_alpha_to_number`, parse any leading `+` or `-` sign before scanning digits regardless of `lenient_sign`.

---

### F1.3 INSPECT REPLACING on signed numeric field strips negative sign
Severity: High
Confidence: verified
Where: seance/rt.py:1244
What happens: `inspect_replace` obtains text via `self._text(ref)`, which calls `_digits_text(val, spec)` for numeric fields. `_digits_text` uses `abs(value)` and omits the sign; when `inspect_replace` writes back with `self.move(..., ref)`, the signed field receives an unsigned string, flipping negative values to positive.
Evidence: Running `build/review/probe_inspect_num.py` on `TINSP.cbl` with `PIC S9(5) SIGN LEADING SEPARATE` holding `-12045` and running `INSPECT N REPLACING ALL "0" BY "9"`:
- GnuCOBOL output: `N=-12945`
- Séance Python output: `N=+12945`
Why it matters: Numeric data inspection/masking inadvertently changes negative monetary or quantity amounts to positive amounts.
Suggested fix: In `seance/rt.py`, preserve the sign formatting in `_text(ref)` when inspecting signed numeric fields, or ensure `inspect_replace` captures and restores the original sign state.

---

### F1.4 DIVIDE REMAINDER without GIVING produces invalid Python expression
Severity: Low
Confidence: verified
Where: seance/translate.py:823
What happens: When `DIVIDE INTO` is parsed with `REMAINDER` but without `GIVING`, `dividend` and `divisor` are set to `None`, which then renders into `f"{dividend} - {q.num} * {divisor}"` as `None - S.n(...) * None`.
Evidence: Read `seance/translate.py` lines 821-841:
```python
else:
    items = [(r, f"{r.num} / {a}", rd) for r, rd in dests]
    dividend = divisor = None
...
if self.accept("REMAINDER"):
    rem = self.ref()
    q = items[0][0]
    remainder = (rem, f"{dividend} - {q.num} * {divisor}")
```
Why it matters: Although standard COBOL requires GIVING with REMAINDER, a syntax variation could emit uncompilable Python code.
Suggested fix: In `s_DIVIDE`, raise `Unsupported` if `REMAINDER` is encountered when `dividend` or `divisor` is `None`.
