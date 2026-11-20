# Séance Review Plan

This review plan covers the exhaustive verification and review of **Séance**, a local tool that migrates COBOL programs to Python and proves migrations using differential compilation and execution against GnuCOBOL.

The product's defining guarantee is **proof**: a false "Spirit matched" is the most severe defect possible.

---

## 1. Phase 0: Baseline & Orientation Findings

- **Steering and Specs**:
  - `README.md`, `docs/COMPARISON.md`, `.kiro/steering/product.md`, `.kiro/steering/cobol-migration.md`, and `.kiro/specs/seance/` (`design.md`, `requirements.md`, `tasks.md`) read and analyzed.
- **Rule Verification (`scripts/check_rules.py`)**:
  - `20 checks: 18 pass, 2 warn, 0 fail`
  - `WARN`: MCP config runs on other machines (`.kiro/settings/mcp.json` contains author machine's absolute path; author-retained decision).
  - `WARN`: Write-up on how Kiro was used (`docs/hackathon/KIRO_WRITEUP.md` has 4 bracketed questions reserved for the author).
- **Test Suite (`pytest -q -p no:cacheprovider`)**:
  - `161 passed, 1 warning in 153.66s (0:02:33)`
  - Warning: `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
- **Line Count Survey (`seance/*.py`)**:
  - Total files scanned: 34 Python modules.
  - Files over 800 lines:
    - `seance/translate.py`: 1,730 lines
    - `seance/rt.py`: 1,398 lines
  - Key modules near threshold: `seance/cases.py` (756 lines), `seance/analyze.py` (720 lines), `seance/gapfill.py` (637 lines).

---

## 2. Sub-Agent Execution Plan (Phase 2)

All sub-agents operate strictly independently. Sub-agents do not share findings or influence one another. Each sub-agent must generate findings in the standard format with concrete evidence (command output or exact file:line references).

### Common Ground Rules for All Sub-Agents
- Read-only across the entire workspace, except output files written to `review/findings/` and temporary probe scripts written to `build/review/`.
- Absolutely forbidden to touch or modify: `legacy/`, `fixtures/`, `samples/*/legacy/`, and `.kiro/settings/mcp.json`.
- PowerShell commands must run via `.venv\Scripts\python.exe` and load GnuCOBOL tools using `. .\scripts\env.ps1`.
- Any observation with zero findings must explicitly state what was checked and confirmed clean. Silence is not an acceptable result.

---

### Agent 1: Translator Semantics

- **The One Question**: Where does the translated Python differ from what GnuCOBOL does, for a construct the tests do not cover?
- **Allowed Files to Read**:
  - `seance/translate.py`
  - `seance/rt.py`
  - `seance/cobol_num.py`
  - `seance/codec.py`
  - `docs/STRESS.md`
  - `scripts/stress_translate.py`
  - Contextual references in `seance/model.py` and `seance/layout.py` if needed for parse tree types.
- **Commands Allowed to Run**:
  - `. .\scripts\env.ps1; .\.venv\Scripts\python.exe tests/test_translator_stress.py`
  - Probe scripts created in `build/review/probe_translate_*.py` comparing isolated COBOL compilation/execution against `seance.rt` and `seance.translate`.
- **What It Must NOT Touch**:
  - Any production file (`seance/*.py`), fixtures, or tests outside `build/review/`.
- **Output File**:
  - `review/findings/1-translator-semantics.md`

---

### Agent 2: Proof Integrity

- **The One Question**: Can the checker say "Spirit matched" when the programs differ?
- **Allowed Files to Read**:
  - `seance/verify.py`
  - `seance/cases.py` (specifically `compare`, `_units`, `_record_units`, execution wrappers)
  - `seance/report.py`
  - `seance/export.py`
  - `seance/coverage.py`
- **Commands Allowed to Run**:
  - Probe scripts created in `build/review/probe_verify_*.py` testing comparison logic with mismatched byte buffers, return codes, console outputs, trailing spaces, newline discrepancies, floating-point representations, and receipt hash computations.
- **What It Must NOT Touch**:
  - Any production code, fixtures, or legacy directories.
- **Output File**:
  - `review/findings/2-proof-integrity.md`

---

### Agent 3: Gap Filling and Mutation

- **The One Question**: Is each claim gap filling makes (closed, equivalent, mismatch) backed by what it did? Can it hang, lose data or save a wrong test?
- **Allowed Files to Read**:
  - `seance/gapfill.py`
  - `seance/mutate.py`
  - `tests/test_gapfill.py`
  - `seance/cases.py`
- **Commands Allowed to Run**:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_gapfill.py -v`
  - Probe scripts in `build/review/probe_gapfill_*.py` stress-testing the equivalence threshold (the 4-input edge evaluation bar), mutant generation, loop timeout limits, and fixture persistence logic (`gap-*` files).
- **What It Must NOT Touch**:
  - `fixtures/`, production code, or sample programs.
- **Output File**:
  - `review/findings/3-gap-filling-and-mutation.md`

---

### Agent 4: API and Upload Safety

- **The One Question**: Can a request read or write outside the workspace, run unintended commands, or exhaust the machine?
- **Allowed Files to Read**:
  - `seance/api.py`
  - `seance/jobs.py`
  - `seance/jcl.py`
  - `seance/programs.py`
  - `seance/samples.py`
  - `seance/config.py`
- **Commands Allowed to Run**:
  - Probe scripts in `build/review/probe_api_*.py` using `starlette.testclient.TestClient` or `requests` to test path traversal in program names, upload file endpoints, session token enforcement, Host header spoofing / DNS rebinding rejection, and payload size bounds.
- **What It Must NOT Touch**:
  - Production code, deleting files outside `build/`, running commands that alter system state.
- **Output File**:
  - `review/findings/4-api-and-upload-safety.md`

---

### Agent 5: UI Behavior and Accessibility

- **The One Question**: Are keyboard use, focus handling, reduced motion, contrast, command palette anchoring to the search button, and untrusted text escaping compliant?
- **Allowed Files to Read**:
  - `web/index.html`
  - `scripts/ui_check.py`
  - `scripts/audit_ui.py`
  - `tests/test_ui_contrast.py`
- **Commands Allowed to Run**:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_contrast.py`
  - Static HTML/JS analysis scripts in `build/review/audit_html_*.py` scanning DOM elements, ARIA attributes, event listeners (`keydown`), contrast ratios, CSS `@media (prefers-reduced-motion)` rules, innerHTML/DOM insertion safety, and command palette popover anchors.
- **What It Must NOT Touch**:
  - `web/index.html`, any UI assets.
- **Output File**:
  - `review/findings/5-ui-behavior-and-accessibility.md`

---

### Agent 6: Submission Compliance

- **The One Question**: Does the repository meet every Kiroween rule, as a stranger who clones it would see?
- **Allowed Files to Read**:
  - `.kiro/` (all subdirectories: `steering/`, `specs/`, `hooks/`, `settings/`)
  - `README.md`
  - `LICENSE`
  - `docs/hackathon/` (`DEMO.md`, `KIRO_WRITEUP.md`, `SUBMISSION.md`)
  - `samples/*/legacy/SOURCE.md`
  - `.gitignore`
  - `.gitattributes`
- **Commands Allowed to Run**:
  - `. .\scripts\env.ps1; .\.venv\Scripts\python.exe scripts\check_rules.py`
  - Git status / check commands verifying repository root cleanliness, untracked/ignored file rules, and license compliance.
- **What It Must NOT Touch**:
  - Any repository file, especially `.kiro/settings/mcp.json`.
- **Output File**:
  - `review/findings/6-submission-compliance.md`

---

### Agent 7: Docs Against Code

- **The One Question**: Does every number, command and claim in the docs match what the code does today?
- **Allowed Files to Read**:
  - `README.md`
  - `docs/*.md` (`docs/COMPARISON.md`, `docs/STRESS.md`, `docs/hackathon/*.md`)
  - `.kiro/specs/seance/*.md`
  - Source verification targets: `seance/mcp_server.py`, `seance/cli.py`, `seance/config.py`, `samples/` directory structure.
- **Commands Allowed to Run**:
  - Targeted verification commands: `.\.venv\Scripts\python.exe -m seance --help`, inspect tool list in `seance/mcp_server.py`, count sample programs in `samples/`, check options in `seance/config.py`.
- **What It Must NOT Touch**:
  - Documentation files or source code.
- **Output File**:
  - `review/findings/7-docs-against-code.md`

---

### Agent 8: Test Quality

- **The One Question**: Which behavior has no test, and which tests could pass while the code is wrong?
- **Allowed Files to Read**:
  - `tests/*.py`
  - `scripts/*.py`
  - Corresponding `seance/*.py` files for behavioral verification.
- **Commands Allowed to Run**:
  - Targeted test execution: `.\.venv\Scripts\python.exe -m pytest tests/<test_file>.py -v`
  - Test inspection scripts in `build/review/inspect_tests_*.py` evaluating assertion rigor, exception catching without assertions, mock validity, and untested edge cases.
- **What It Must NOT Touch**:
  - Any test files or source code.
- **Output File**:
  - `review/findings/8-test-quality.md`

---

## 3. Finding Format Contract

Every finding across all sub-agents must adhere strictly to the following specification:

```markdown
### F<scope>.<n> <short title>
Severity: Critical | High | Medium | Low | Note
Confidence: verified | probable | speculative
Where: path:line
What happens: one or two sentences.
Evidence: the command and the relevant output, or the lines read.
Why it matters: the effect on a user or on the proof.
Suggested fix: one or two sentences. Do not apply it.
```

---

## 4. Execution Sequence After Approval

1. **Phase 2**: Dispatch 8 independent sub-agents under the exact scopes and constraints outlined above.
2. **Phase 3**: Consolidated review:
   - Deduplicate findings.
   - Attempt concrete reproduction for every Critical and High finding; downgrade or remove any unverified claim.
   - Synthesize and publish `review/REPORT.md` with explicit verdict (`ship`, `ship after fixes`, or `do not ship`).
   - Stop and wait for user instruction on selected fixes.
