# Scope 5 Findings: UI Behavior and Accessibility

Keyboard use, focus handling, reduced motion, contrast, the command palette anchored to the search button, escaping of untrusted text.

---

### F5.1 Modal dialogs do not restore focus to triggering element on close
Severity: Medium
Confidence: verified
Where: web/index.html:1120
What happens: When closing modal dialogs (`palDlg`, `addDlg`, `setDlg`, `keysDlg`, `aboutDlg`, `guideDlg`) via Escape or close buttons, the previously focused element (`document.activeElement` prior to opening) is not remembered and focus drops to `document.body`.
Evidence: Inspected all modal dialog open/close event listeners in `web/index.html`. Only `#floatMenu` uses `activeElement`. `$('palDlg').close()` and `d.close()` do not restore focus to `$('palOpen')` or the originating trigger button.
Why it matters: Breaks WCAG 2.1 Success Criterion 2.4.3 (Focus Order) for keyboard-only and screen reader navigation, forcing users to re-tab through the entire page after closing dialogs.
Suggested fix: In `openPalette` and other dialog openers, record `const priorFocus = document.activeElement;` and attach a `'close'` event listener to the dialog that calls `priorFocus?.focus()`.

---

### F5.2 Several modal dialogs lack explicit initial focus assignment
Severity: Low
Confidence: verified
Where: web/index.html:1130
What happens: While `palDlg` focuses `$('palInput')`, `cfDlg` focuses confirmation buttons, and `guideDlg` focuses `$('guideTour')`, other dialogs (`setDlg`, `keysDlg`, `aboutDlg`, `addDlg`) invoke `d.showModal()` without explicitly focusing their primary control or close button.
Evidence: Read lines 1125-1160 of `web/index.html`:
```javascript
$('setDlg').showModal();
$('keysDlg').showModal();
$('aboutDlg').showModal();
```
Why it matters: Depending on browser implementations, focus may default to the dialog container rather than an actionable control, requiring extra keystrokes to begin interaction.
Suggested fix: Explicitly call `.focus()` on the dialog's primary control or close button immediately after `showModal()`.

---

### Clean Areas Checked
The following UI and accessibility areas were audited and found compliant:
1. **WCAG AA Contrast**:
   - `tests/test_ui_contrast.py` passed all assertions verifying text colors against surfaces (`bg`, `panel`, `panel2`, `sunk`, `hover`) with contrast ratio >= 4.5:1.
   - Primary button contrast (`amber-ink` on `amber`) and code gutter contrast meet WCAG AA.
2. **Command Palette Positioning**:
   - `placePalette()` dynamically computes `r = $('palOpen').getBoundingClientRect()` and positions `dialog#palDlg` directly anchored to the search button.
3. **Reduced Motion**:
   - Comprehensive `@media (prefers-reduced-motion: reduce)` block disables CSS animation durations, iteration counts, and transitions (`body[data-motion=system] * { animation-duration: .001s !important; transition: none !important; }`).
   - `motionOn()` checks `matchMedia('(prefers-reduced-motion: reduce)').matches` and disables animated numeric counters (`countUp`).
4. **Untrusted Text Escaping**:
   - Dedicated `esc()` sanitizes `&`, `<`, `>`, `"`, and `'`.
   - All dynamic DOM insertions via `innerHTML` across error messages, notes, titles, and filenames wrap dynamic values with `esc()`.
5. **Keyboard Input Safety**:
   - Global keyboard shortcuts inspect `const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;` preventing accidental shortcut activations while typing.
