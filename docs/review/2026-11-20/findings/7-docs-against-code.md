# Scope 7 Findings: Docs Against Code

Does every number, command and claim in the docs match what the code does today?

---

### F7.1 Settings documentation omits SEANCE_HOST and SEANCE_PORT environment variables
Severity: Low
Confidence: verified
Where: README.md:200
What happens: In `README.md` section "Settings", the text lists check environment variables:
`SEANCE_ROUNDS, SEANCE_MAX_ROUNDS, SEANCE_VERIFY_TIMEOUT, SEANCE_COMPARE_TIMEOUT, SEANCE_MUTANTS, SEANCE_MAX_DATA_RECORDS, SEANCE_RANDOM_RECORDS, SEANCE_RUN_TIMEOUT`.
It does not document `SEANCE_HOST` or `SEANCE_PORT` which are also supported by `seance/config.py`.
Evidence: Read `seance/config.py` lines 15-16:
```python
HOST = os.environ.get("SEANCE_HOST", "127.0.0.1")
PORT = _int("SEANCE_PORT", 8000)
```
Why it matters: Users configuring server deployment or container environments may not realize host and port can be specified via environment variables in addition to CLI `--port`.
Suggested fix: Add `SEANCE_HOST` and `SEANCE_PORT` to the environment variables list in `README.md`.

---

### Clean Areas Checked
1. **Sample Library Counts**:
   - `README.md:88` states "Fifteen small programs ship in samples/". Verified: `samples/catalog.json` contains exactly 15 programs (`payroll`, `accounts`, `loan`, `interest`, `inventory`, `account_report`, `add_amounts`, `table_search`, `customer_master`, `order_pricing`, `transaction_sort`, `seat_bookings`, `payment_posting`, `customer_inquiry`, `nightly_batch`).
2. **Test Suite Counts**:
   - `README.md:252` states "python -m pytest # 161 tests". Verified: exactly 161 tests passed in 153.66s.
3. **MCP Server Tool List**:
   - `README.md:228` lists 13 MCP tools. Verified: `seance/mcp_server.py` implements all 13 tools (`list_programs`, `describe_program`, `describe_layout`, `run_legacy_program`, `record_legacy_fixtures`, `draft_python`, `verify_migration`, `measure_test_strength`, `fill_test_gaps`, `extract_business_rules`, `assess_workspace`, `list_samples`, `load_sample`).
4. **Stress Testing Figures**:
   - `README.md:278` and `docs/STRESS.md:5` state 142 of 465 matched (31%). Verified matching numbers and coverage in `tests/test_translator_stress.py`.
5. **Feature Scope Agreement**:
   - Supported feature list in `seance/config.py` (`SUPPORTED`) aligns statement-by-statement with `README.md` ("What COBOL It Runs") and `/api/about`.
