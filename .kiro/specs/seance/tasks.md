# Séance tasks

Status is checked against the repository, not against intent. `[x]` means a test or a script covers it.

## R1 Ingest
- [x] Parse fixed and free format COBOL, copybooks, FD and WORKING-STORAGE layouts (`model.py`, `layout.py`)
- [x] Report the line and reason when a source cannot be parsed
- [x] `python -m seance analyze <program>`

## R2 Record ground truth
- [x] Compile and run with GnuCOBOL through `recorder.py` and `run_legacy_program` (MCP)
- [x] Generate edge, random and missing-file sets from the layout (`cases.generated_cases`)
- [x] Keep uploaded data (`yours-*`) and mainframe output (`golden-*`) across a re-record
- [x] Keep sets found by gap filling (`gap-*`) across a re-record

## R3 Spec
- [x] Plain-English spec with COBOL line numbers (`spec.py`, `describe_program`)
- [x] Business rules, Gherkin, data dictionary, lineage and flow graph (`analyze.py`, Analysis tab)

## R4 Generate
- [x] Rule-based translator writing `Decimal`-correct Python over `rt.py` (`translate.py`)
- [x] COMP-3, COMP, COMP-5, COMP-1/2, tables, REDEFINES, SORT, CALL, indexed and relative files
- [x] Embedded SQL and CICS through shared bridges
- [x] Translator stress harness over GnuCOBOL's own test programs; first round of fixes (113 to 141 of 466 usable programs, `docs/STRESS.md`)
- [x] Compiler directives, REPLACE, named constants, DECIMAL-POINT IS COMMA, several programs in one file, DELETE FILE, LENGTH OF (141 to 165 of 464)
- [ ] Next: POINTER and ADDRESS OF, the exception functions, the FORMATTED-DATE family, GLOBAL data across programs of one file, Report Writer

## R5 Verify
- [x] Replay saved sets byte for byte
- [x] Hypothesis random runs with bounded shrinking
- [x] Statement coverage of the saved runs
- [x] Test strength by planted bugs (`mutate.py`)
- [x] Find inputs that catch the survivors, with the COBOL as judge (`gapfill.py`)

## R6 Report
- [x] Web report, Markdown, HTML, JSON and JUnit; receipt with SHA-256 of COBOL, Python and data
- [x] Exported package with its own pytest suite

## R7 Demo programs
- [x] payroll, inventory and interest, plus loan, accounts, files, SQL and CICS samples in `samples/`
- [x] A deliberate rounding edge case that a naive port gets wrong (`samples/loan/naive.py`, `migrated/payroll_naive.py`)

## R8 Product
- [x] Empty workspace; sample library behind the guide; delete anything
- [x] Command palette, shortcuts, guided tour, settings, reduced-motion support
- [x] Code search in the command bar, Where Used across programs, record viewer with CSV export
- [x] `scripts/ui_check.py` (89 checks) and `scripts/audit_ui.py` run against the live app

## R9 Submission
- [x] `.kiro/` committed with steering, hooks, spec (requirements, design, tasks) and MCP config
- [x] `scripts/check_rules.py` and `tests/test_rules.py`
- [ ] Demo video recorded from `docs/hackathon/DEMO.md` (under 3 minutes)
- [ ] Devpost write-up questions answered in `docs/hackathon/KIRO_WRITEUP.md`

## R10 Release 1.2
- [x] Every floating surface opaque: menus, dropdowns, command bar, toasts, header, program bar (`scripts/audit_ui.py` checks it)
- [x] MCP for any machine and any MCP client: stdlib launcher `scripts/seance_mcp.py`, `seance mcp-config --client` for nine clients, HTTP at `/mcp` in the app and `seance mcp --http`, `docs/MCP.md`, `tests/test_mcp.py`
- [x] Home page that shows the product: hero with how to add a program, how it works, every feature with a way to open it, the sample library, agent settings, what runs (`scripts/ui_check.py` 96 checks)
- [x] Edited pictures measured against GnuCOBOL both ways on random pictures (`seance/editing.py`, `scripts/fuzz_editing.py`)
- [x] NIST COBOL-85 harness (`scripts/stress_nist.py`); nucleus 1 to 58 of 92 so far
- [x] Continued literals to column 72; qualified condition names; SET several / TO FALSE; paragraphs per section and PARA OF SECTION; ALTER; SPECIAL-NAMES (switches, CLASS, SYMBOLIC, devices); abbreviated conditions; EVALUATE of a condition; CORRESPONDING; RENAMES; INITIALIZE in full; SIGN and USAGE on groups; group moves; DISPLAY of numbers as stored (`tests/data/lang`)
- [ ] Rest of NIST: SM IC SQ RL IX ST SG OB IF RW DB modules; AWS CardDemo; Open Mainframe Project labs
- [ ] Language gaps left: exception functions, FORMATTED-DATE family, GLOBAL, POINTER and ADDRESS OF, Report Writer, SCREEN SECTION, BMS maps, IMS
- [ ] Divergence locator: when a check is restless, name the first paragraph and field where the Python and the COBOL disagree
- [ ] Antigravity review prompt for this release
- [ ] Docs (README, COMPARISON, STRESS, CHANGELOG, about lists), version, tag, archive
