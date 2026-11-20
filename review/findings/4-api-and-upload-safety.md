# Scope 4 Findings: API and Upload Safety

Can a request read or write outside the workspace, run unintended commands, or exhaust the machine?

---

### F4.1 TrustedHostMiddleware omits IPv6 loopback [::1]
Severity: Low
Confidence: verified
Where: seance/api.py:44
What happens: `app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])` omits `"[::1]"`. On dual-stack systems where a client or browser resolves `localhost` or connects directly via `http://[::1]:8000`, requests are rejected with HTTP 400 Invalid Host header.
Evidence: Read `seance/api.py` line 44:
```python
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
```
Why it matters: Legitimate local connections attempting to access the service via IPv6 loopback fail unexpectedly.
Suggested fix: Include `"[::1]"` in `allowed_hosts`.

---

### Clean Areas Checked
The following security controls and boundaries were audited and found clean:
1. **Path Traversal**:
   - `seance/programs.py`: `NAME_RE` enforces strict validation `^[a-z][a-z0-9_]{1,23}$`.
   - `COPYBOOK_RE` enforces `^[A-Za-z0-9_-]{1,32}$`.
   - File uploads in `add_uploaded` and `add_golden` sanitize stems via `re.sub(r"[^a-z0-9]+", "-", ...)` and constrain destinations to `fixtures/<program>/`.
   - File removal in `remove_uploaded` strictly validates `^(yours|golden|gap)-[a-z0-9-]{1,40}$`.
2. **Command Injection**:
   - All subprocess invocations across `api.py`, `recorder.py`, `mutate.py`, and `gapfill.py` use executable argument lists (`[sys.executable, ...]` or `[cobc_path(), ...]`) with `shell=False`.
   - JCL utility emulation (`IEBGENER`, `SORT`, `IEFBR14`) and dataset pipelines run entirely in-memory within Python; no external shell utilities are invoked.
3. **Machine Exhaustion & DoS**:
   - Program uploads capped at `MAX_SOURCE_BYTES` (200 KB).
   - Test data uploads capped at 5 MB text / 7 MB base64; records capped at `MAX_DATA_RECORDS` (5000 records).
   - Try request inputs capped at 10 files and 200 lines per file (max 2000 chars per line).
   - Strict timeouts enforced on verification, comparison, and CLI executions (`COMPARE_TIMEOUT`, `RUN_TIMEOUT`, `VERIFY_TIMEOUT`).
4. **Cross-Site & Rebinding Protection**:
   - Host header filtering blocks DNS rebinding.
   - Non-idempotent `/api/*` endpoints require timing-safe HMAC token comparison (`x-seance-token`) with `app.state.token`.
