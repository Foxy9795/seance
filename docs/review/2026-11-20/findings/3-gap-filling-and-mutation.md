# Scope 3 Findings: Gap Filling and Mutation

Is each claim gap filling makes (closed, equivalent, mismatch) backed by what it did? Can it hang, lose data or save a wrong test?

---

### F3.1 Gap filler can save a broken test as passing when both programs produce differing errors
Severity: Critical
Confidence: verified
Where: seance/gapfill.py:703
What happens: In `fill_gaps`, when a mutant produces differing outputs from original Python and the generated input is evaluated against COBOL, `diffs, _ = compare(model, expected, actual)` is used to decide whether the COBOL and original Python agree. Due to the bug in `compare()` (F2.1), if COBOL produces an expected error (e.g. file error) and original Python crashes with an unrelated bug, `diffs` is empty. The gap filler concludes the original Python matched COBOL and executes `save_set(...)`, saving the failing case as a permanent passing `gap-*` fixture.
Evidence: Traced in `seance/gapfill.py` lines 701-714:
```python
expected = run_cobol(exe, model, case)
actual = run_python(impl, case)
diffs, _ = compare(model, expected, actual)
...
if not diffs:
    name = _name_for(program, m["cobol_line"] or m["line"], root) if save else None
    if name:
        save_set(program, name, case, expected, label, root)
        saved.append(name)
```
Combined with F2.1 demonstration where `compare(model, expected, actual)` returns `([], 0)` when both have different errors.
Why it matters: Ground rules classify "a wrong test saved as passing" as Critical. A false test fixture enters `fixtures/<program>/` and permanently shields subsequent migrations from detecting the bug.
Suggested fix: Once F2.1 is resolved in `compare()`, ensure `fill_gaps` explicitly asserts `expected.error == actual.error` and `expected.return_code == actual.return_code` before invoking `save_set`.

---

### F3.2 Equivalence bar of four inputs does not detect downstream-gated branches
Severity: Medium
Confidence: verified
Where: seance/gapfill.py:49
What happens: A mutant is labeled "equivalent" when `len(self.flips) >= EQUIVALENT_AFTER` (4 inputs). If the mutated comparison condition feeds an internal variable or flag whose output effect is gated by another un-triggered condition (e.g. `IF A <= B SET FLAG TO TRUE`, but `FLAG` is only read if `RECORD-TYPE == 'VIP'`), 4 generated inputs that do not meet the gating condition will show no output difference, causing a non-equivalent branch mutation to be declared equivalent.
Evidence: Read `seance/gapfill.py` lines 49, 391-393, 505-506. The test `test_payroll_gap_is_closed_and_the_equivalent_change_is_named` in `tests/test_gapfill.py:61` verifies the threshold.
Why it matters: Calling a mutant "equivalent" caches it in `gapfill.json` and suppresses further search. If the change was not actually equivalent under other record types, the gap is prematurely dismissed.
Suggested fix: Increase the edge hit threshold or require diversity across non-numeric categorical fields (e.g. record codes/types) before certifying equivalence, and qualify the report note with "empirically equivalent on tested paths; human review recommended".

---

### F3.3 Non-comparison mutations cannot record edge flips and remain perpetually "open"
Severity: Low
Confidence: verified
Where: seance/gapfill.py:372
What happens: For mutation sites that are not comparisons (such as arithmetic operator swap `+`/`-`, or constant modification where the value is not in a comparison), line 373 sets `ev.flipped = True`, but does not set `ev.edge`. Because line 391 only adds to `self.flips` if `ev.edge` is True, `self.flips` remains empty for these mutants, meaning they can never be marked equivalent even if their execution path is unreachable or has identical output.
Evidence: Read `seance/gapfill.py` lines 372-376 and 391-393:
```python
elif self.hits:
    ev.flipped, ev.dist = True, Decimal(0)
...
if ev.usable and ev.edge:
    self.flips.setdefault(_signature(self.model, st), st.copy())
```
Why it matters: Such mutants consume the full search budget and time limit before falling back to status "open" or "unreached".
Suggested fix: Set `ev.edge = True` when `self.hits > 0` for non-comparison mutations if edge-hit equivalence tracking is desired across all mutant kinds.
