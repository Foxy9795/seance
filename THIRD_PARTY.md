# Third-party material

Séance is MIT licensed (`LICENSE`). Everything in this repository was written during the Kiroween 2026 submission period
(the first commit is dated 2026-11-18), with the exceptions below. Nothing here is code from before that period.

## Included in the repository
| What | Where | Licence | Notes |
| --- | --- | --- | --- |
| Three COBOL programs from the Open Mainframe Project COBOL Programming Course (`CBL0011`, `ADDAMT`, `SRCHBIN`) | `samples/account_report`, `samples/add_amounts`, `samples/table_search` | CC-BY-4.0 | Unchanged; credited in `SOURCE.md` beside each. https://github.com/openmainframeproject/cobol-programming-course |

The other twelve sample programs, every test, probe and script were written for this project.

## Downloaded or installed when you use it (not stored in the repository)
| What | Used for | Licence |
| --- | --- | --- |
| GnuCOBOL 3.1.2 (`seance setup` downloads it on Windows; elsewhere install it with your package manager) | The compiler and runtime that judge every migration. It runs as a separate program. | GPL-3.0 (compiler), LGPL-3.0 (runtime library) |
| NIST COBOL-85 test suite (`python scripts/stress_nist.py --fetch`) | Measuring the translator against 366 programs. Fetched on demand, never committed. | Public domain (US government work) |
| FastAPI, Uvicorn, Pydantic, MCP SDK, Hypothesis, pytest | The app, the MCP server, property-based tests | MIT, BSD-3-Clause, MIT, MIT, MPL-2.0, MIT |
| Playwright (development only) | `scripts/ui_check.py`, the browser test | Apache-2.0 |
| SQLite (Python standard library) | The embedded SQL and CICS bridges | Public domain |

## Fonts, icons and images
The page uses the system fonts and inline SVG drawn for this project. No third-party images, fonts or music are included.

## Tools used to build it
Kiro (IDE) wrote and changed the code, using the specification, steering and hook in `.kiro/`. A second AI agent
(Antigravity) was used as an independent reviewer: its reports are in `docs/review/`; every fix was made with Kiro and
checked against GnuCOBOL.
