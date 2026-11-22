# Kiroween 2026: submission checklist
Dates (Pacific Time): submissions close **December 4, 2026, 2:00 pm**; Kiro credit requests by December 1, 12:00 pm; credits must be redeemed by December 4.
No extensions and no late submissions.

## In the repository (checked)
| Rule | Status | Evidence |
| --- | --- | --- |
| Built with Kiro; category | Done | Category **Resurrection**. Kiro IDE; spec, steering, hook and MCP settings in `.kiro/`. |
| Newly created during the Submission Period (from Oct 30) | Done | First commit 2026-11-18 (`git log --reverse`). Nothing pre-dates it. |
| Disclose any pre-existing code or work | Done | `THIRD_PARTY.md`: three CC-BY-4.0 course programs (credited in `SOURCE.md`), tools that are downloaded and not stored. |
| Public GitHub repo with an open source licence | Needs you | `LICENSE` (MIT) is at the root so GitHub shows it in the About box. Create the repo as **public** on GitHub (not GitLab or Bitbucket). |
| `/.kiro` at the root, not ignored | Done | `.kiro/specs`, `.kiro/steering`, `.kiro/hooks`, `.kiro/settings`. `.gitignore` does not mention it. Do not add it. |
| Source, assets and instructions to run | Done | `README.md` (setup, `seance serve`), `scripts/setup.ps1`, `seance doctor`. |
| Works as depicted | Done | README, `DEMO.md` and the write-up describe the current page (tutorial, dashboard, Settings page). `python scripts/ui_check.py` drives the page in a browser (32 checks). |
| Nothing personal in what is published | Done | The one local path in `samples/seat_bookings/fixtures/missing/set.json` and the paths in `docs/review/` are replaced. Search before you push: `git grep -n -i "<your user name>"`. |
| No third-party trademarks or music in the video | Needs you | The page names GnuCOBOL and Kiro; use no logos and no music. |
| Language | Done | Everything is in English. |
| Tests that prove it | Done | `python -m pytest -q` (275), NIST harness 325 of 366, `python scripts/check_rules.py`. |

## Only you can do these
1. **Push to GitHub**: `gh auth login`, create a public repository, push `main` and the tags. Check the About box shows "MIT License".
2. **Video** (under 3 minutes, public on YouTube, shows the app working on your machine): follow `docs/hackathon/DEMO.md`.
3. **Devpost form** (kiroween.devpost.com): category *Resurrection*; the GitHub URL; the YouTube URL; the text description (use "What Séance is"
   and "What it does today" from `KIRO_WRITEUP.md`); the Kiro write-up (answer the bracketed questions in `KIRO_WRITEUP.md` first).
4. **Functional application**: the app runs on the judge's machine from the repository (Windows first). Put the setup in the
   "testing instructions" field: `git clone`, `.\scripts\setup.ps1`, `python -m seance serve`. No login is needed.
5. **Kiro credits** (optional): request through the Credit Request Form by Dec 1, 12:00 pm PT; redeem by Dec 4.
6. **Bonus prizes you can still enter**
   - *Bonus Blog Prize*: publish a public post about Kiro and the build on a third-party blog during the Submission Period; it must say it was
     written as part of the Kiroween 2026 hackathon; paste the URL in the form.
   - *Social Blitz*: a public post that **starts with** `#KiroweenHackathon26`, with your favourite thing about Kiro and how it changed your approach;
     paste the link in the form.
   - *Best Ghost of Kiroween Past*: only if you registered for Kiroween 2025.
   - *Best Startup* and *Best Student*: only with the founder and student details the rules ask for.
   - *Best Kiro Crew App*: only if you built one in Kiro Crew, in its own repo, during the period.
7. **Verify the team**: up to 3 people; one Representative enters the submission.

## Things judges may notice
- A second AI agent (Antigravity) reviewed the work; the write-up and `THIRD_PARTY.md` say so, and say the fixes were made with Kiro.
- The rules say insufficient use of Kiro can disqualify: the write-up should say what Kiro actually did, in your words (spec, steering, hook, MCP, PBT).
- Do not delete `.kiro/`, and do not rename `LICENSE`.
