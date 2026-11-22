# Scope 6 Findings: Submission Compliance

Does the repository meet every Kiroween rule, as a stranger who clones it would see?

---

### F6.1 Devpost write-up has four unfilled placeholder questions
Severity: High
Confidence: verified
Where: docs/hackathon/KIRO_WRITEUP.md:24
What happens: `docs/hackathon/KIRO_WRITEUP.md` retains four bracketed prompts intended for the author:
- Line 24: `[Did you use another surface? What differed?]`
- Line 28: `[How did the spec shape the build compared with vibe coding?]`
- Line 33: `[Which rule changed Kiro's output the most?]`
- Line 36: `[Confirm it fired in your session, and what it caught.]`
Evidence: Running `.\.venv\Scripts\python.exe scripts\check_rules.py`:
```
WARN  write-up on how Kiro was used
      4 bracketed question(s) only you can answer
```
Why it matters: Submission rules require a write-up explaining how Kiro was used. Submitting unedited prompt brackets will negatively impact hackathon judging.
Suggested fix: Author must answer the four personal experience questions and remove the brackets before final submission.

---

### F6.2 MCP server configuration holds absolute machine path
Severity: Note
Confidence: verified
Where: .kiro/settings/mcp.json:4
What happens: `.kiro/settings/mcp.json` contains `C:\Users\user\Desktop\Sid Project\Python\Kiro\...`, which will fail on any other machine cloning the repo.
Evidence: Read `.kiro/settings/mcp.json` lines 4 and 10:
```json
"command": "C:\\Users\\user\\Desktop\\Sid Project\\Python\\Kiro\\.venv\\Scripts\\python.exe"
```
Flagged as `WARN` by `scripts/check_rules.py`.
Why it matters: External judges running Kiro against the repository will encounter an MCP server that fails to start unless updated to a relative or environment python invocation.
Suggested fix: Known author decision; replace with generic python command or document local configuration requirement.

---

### Clean Areas Checked
The following Kiroween submission requirements were audited and verified:
1. **Working App & Category**:
   - Séance migrates COBOL programs to Python and differentials outputs against GnuCOBOL under the **Resurrection** category.
2. **Kiro Integration**:
   - `.kiro/specs/seance/` includes `requirements.md`, `design.md`, and `tasks.md`.
   - `.kiro/steering/` includes `product.md` and `cobol-migration.md`.
   - `.kiro/hooks/` includes `verify-migration-on-save.kiro.hook`.
   - MCP server (`seance/mcp_server.py`) implements 13 tools with 7 auto-approved read-only operations.
3. **Repository Cleanliness**:
   - Root `/.kiro` is present and confirmed not ignored by git (`git check-ignore -q .kiro/steering/product.md` exits 1).
   - `.gitignore` properly keeps scratch assets, `tools/`, `.venv/`, and user workspace files (`legacy/*`, `fixtures/*`, `migrated/*`) clean while preserving samples.
4. **License & Third-Party Attribution**:
   - `LICENSE` file contains standard MIT License.
   - All third-party sample programs (`account_report`, `add_amounts`, `table_search`) contain `SOURCE.md` attributing Open Mainframe Project CC-BY-4.0 license.
5. **Timed Demo Script**:
   - `docs/hackathon/DEMO.md` provides a timed step-by-step video script completing at 2:45 (< 3 minute rule).
6. **Install Instructions**:
   - `README.md` provides complete Windows PowerShell quick-start setup and execution commands.
