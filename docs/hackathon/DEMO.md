# Demo script (under 3 minutes)

Category: Resurrection (bring a dead technology back to life). COBOL is the dead technology. Séance's claim is that a
migration is only done when it is proven against the original.

Goal: show a real migration failing, being caught, and being fixed, with the original COBOL as the judge. Then show
that the proof itself is tested.

| Time | Screen | Say |
| --- | --- | --- |
| 0:00 | Title card, then the `loan` program in the Code tab | "Banks still run COBOL, and migrations fail because nobody can prove the new code matches the old. Séance proves it." |
| 0:15 | Kiro chat: ask Kiro to migrate `loan` using the Séance tools | "Kiro reads the spec through our MCP server first." Show the `describe_program` output. |
| 0:30 | Pick "Hand-written port (floats)" in the Python menu | "A typical first draft: floats, no size-error handling." |
| 0:40 | Check tab, Run Check | The verdict turns red: Spirit restless. |
| 0:55 | Evidence panel | "Hypothesis shrank the failure to one record of zeros. The COBOL finished normally. The Python raised ZeroDivisionError." |
| 1:15 | Kiro fixes it and saves `migrated/loan.py` | Show the on-save hook running the check. Name the steering rules: Decimal, `store`, size error. |
| 1:35 | Verdict: Spirit matched | "31 edge-case lines and 300 random records replayed from the real COBOL, then 40 fresh random runs. All identical." |
| 1:50 | Switch to `payroll`, Check tab, Run Mutation Test | "Passing is not enough. Séance plants bugs in the Python and checks that the tests notice. Two slipped through." |
| 2:05 | Find Inputs That Catch These | "It searches for an input that tells each one apart, runs it through the real COBOL, and saves it as a test set. One is closed. The other is shown to make no difference at its edge, and it says so." |
| 2:30 | Show the `.kiro` folder | Spec (requirements, design, tasks), steering, hook, MCP server: one line each. |
| 2:45 | Close | "Séance: raise legacy code from the dead, and prove it." |

Before recording:

- `. .\scripts\env.ps1`, then `python -m seance samples load loan` and `python -m seance samples load payroll`.
- Start the app with `python -m seance serve`.
- To have Kiro write `migrated/loan.py` live, keep a copy of the current file and delete it first.
- Run `python scripts/check_rules.py` and `python -m pytest -q` so the numbers on screen match the repository.

No third-party trademarks or copyrighted music in the video. The three course programs in the sample library are
CC-BY-4.0 and are credited in `samples/*/legacy/SOURCE.md`; do not show them as your own work.
