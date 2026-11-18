# Demo script (under 3 minutes)

Goal: show a real migration failing, being caught, and being fixed, with the original COBOL as the judge.

| Time | Screen | Say |
| --- | --- | --- |
| 0:00 | Title card, then `legacy/loan/loan.cbl` | "Banks still run COBOL, and migrations fail because nobody can prove the new code matches the old. Séance proves it." |
| 0:15 | Kiro chat: ask Kiro to migrate `loan` using the Séance tools | "Kiro reads the spec through our MCP server first." Show `describe_program` output. |
| 0:35 | Kiro writes a first draft (use `examples/naive/loan_naive.py` as the starting point) | "A typical first draft: floats, no size-error handling." |
| 0:50 | Web UI: pick loan, naive draft, "Perform the séance" | Verdict turns red: SPIRIT RESTLESS. |
| 1:05 | Evidence panel | "Hypothesis shrank thousands of inputs to this one. The original COBOL returns status E where Python crashed." |
| 1:25 | Kiro fixes it, saves `migrated/loan.py` | Show the on-save hook running verification. Mention steering rules (Decimal, `store`, `size_error`). |
| 1:50 | Verdict: SPIRIT MATCHED | "33 edge cases, 300 random records and 100 generated batches, all identical to the real program." |
| 2:10 | Show `.kiro/` folder | Specs, steering, hook, MCP server: one line each. |
| 2:35 | Close | "Séance: raise legacy code from the dead, and prove it." |

Before recording: `. .\scripts\env.ps1`, start `python -m uvicorn seance.api:app`, and clear `migrated/loan.py` if you want Kiro to write it live (keep a copy).
