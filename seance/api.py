"""FastAPI app: serves the UI and runs checks.

Start with scripts/run.ps1 (or: python -m uvicorn seance.api:app). It binds to 127.0.0.1 only. Keep it that
way: the editor saves Python that the checker then runs.
"""

from __future__ import annotations

import functools
import hmac
import json
import secrets
import subprocess
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, config
from .programs import (
    MAX_SOURCE_BYTES,
    ProgramError,
    create_program,
    delete_program,
    draft_python,
    implementations,
    program_info,
    program_names,
)
from .recorder import ROOT, LegacyRuntimeError, cobc_available, cobc_path, cobol_env

sys.path.insert(0, str(ROOT))

app = FastAPI(title="Séance")

# Threat model: this app compiles and runs code you give it, so a hostile web page must not be able
# to drive it. Two defenses: (1) only answer requests addressed to 127.0.0.1/localhost, which stops
# DNS rebinding; (2) every state-changing request must carry a random per-launch token that only
# the page we serve knows, which stops cross-site requests.
app.state.token = secrets.token_urlsafe(32)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def require_token(request: Request, call_next):
    if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-seance-token", "")
        if not hmac.compare_digest(sent, app.state.token):
            return JSONResponse({"detail": "Missing or wrong session token. Reload the page."}, status_code=403)
        if request.method in ("POST", "PUT") and "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"detail": "Content-Type must be application/json."}, status_code=415)
    return await call_next(request)


def _is_job(name: str) -> bool:
    from .jobs import job_names

    return name in job_names()


def _require(program: str, implementation: str | None = None) -> None:
    if _is_job(program):
        if implementation is not None and implementation != f"jobs.{program}":
            raise HTTPException(404, f"unknown implementation {implementation!r}")
        return
    if program not in program_names():
        raise HTTPException(404, f"unknown program {program!r}")
    if implementation is not None and implementation not in [i.module for i in implementations(program)]:
        raise HTTPException(404, f"unknown implementation {implementation!r}")


def _run_cli(args: list[str], timeout: int, stdin: str | None = None) -> dict:
    """Run the CLI in a fresh process: no stale imports, and a hung migration cannot hang the server."""
    env = cobol_env()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # never run a stale .pyc after a same-second edit
    try:
        proc = subprocess.run([sys.executable, "-m", "seance", *args], cwd=ROOT, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"Timed out after {timeout} seconds. Does the Python loop forever?")
    try:
        body = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(500, (proc.stderr or proc.stdout or "no output").strip()[-1500:])
    if isinstance(body, dict) and "error" in body:
        raise HTTPException(422, body["error"])
    return body


# ---------------------------------------------------------------- request bodies

class Copybook(BaseModel):
    name: str
    text: str


class NewProgram(BaseModel):
    name: str = ""
    cobol: str
    copybooks: list[Copybook] = Field(default_factory=list, max_length=40)
    programs: list[Copybook] = Field(default_factory=list, max_length=20)  # programs it CALLs


class NewJob(BaseModel):
    name: str = ""
    jcl: str


class VerifyRequest(BaseModel):
    program: str
    implementation: str
    rounds: int = Field(default=config.DEFAULT_ROUNDS, ge=5, le=config.MAX_ROUNDS)


def _plain_lines(lines: list[str]) -> list[str]:
    for line in lines:
        if len(line) > 2000 or any(c in line for c in "\r\n\x00"):
            raise ValueError("Each line must be one line of at most 2000 characters.")
    return lines


class TryRequest(BaseModel):
    program: str
    implementation: str
    files: dict[str, list[str]] = Field(default_factory=dict)
    stdin: list[str] = Field(default_factory=list, max_length=200)
    set: str | None = None

    @field_validator("files")
    @classmethod
    def _files(cls, files: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(files) > 10:
            raise ValueError("At most 10 input files.")
        for lines in files.values():
            if len(lines) > 200:
                raise ValueError("At most 200 lines per file.")
            _plain_lines(lines)
        return files

    @field_validator("stdin")
    @classmethod
    def _stdin(cls, lines: list[str]) -> list[str]:
        return _plain_lines(lines)


class MutateRequest(BaseModel):
    program: str
    implementation: str


class SaveSource(BaseModel):
    program: str
    code: str


class TestData(BaseModel):
    filename: str = "data.txt"
    text: str | None = Field(default=None, max_length=5_000_000)
    base64: str | None = Field(default=None, max_length=7_000_000)
    file: str | None = None  # which input file it is for (ASSIGN name); None when there is only one
    console: bool = False  # the upload is console input, one value per line
    code_page: str | None = None  # EBCDIC code page of a mainframe file, such as cp037


# ---------------------------------------------------------------- endpoints

@functools.lru_cache(maxsize=1)
def _cobc_version() -> str:
    try:
        out = subprocess.run([cobc_path(), "--version"], capture_output=True, text=True, env=cobol_env(), timeout=20).stdout
        return (out.splitlines() or [""])[0].strip()
    except Exception:
        return ""


@app.get("/api/about")
def about():
    return {
        "version": __version__,
        "workspace": str(ROOT),
        "cobc": _cobc_version() if cobc_available() else "",
        "legacy_runtime": cobc_available(),
        "defaults": {"rounds": config.DEFAULT_ROUNDS, "max_rounds": config.MAX_ROUNDS, "max_data_records": config.MAX_DATA_RECORDS,
                     "random_records": config.RANDOM_RECORDS},
        "supported": config.SUPPORTED,
        "not_yet": config.NOT_YET,
    }


@app.get("/api/programs")
def programs():
    from .jobs import job_info, job_names

    infos = [program_info(n) for n in program_names()] + [job_info(n) for n in job_names()]
    infos.sort(key=lambda p: p["title"])
    return {"legacy_runtime": cobc_available(), "programs": infos}


@app.get("/api/programs/{name}")
def one_program(name: str):
    """One program, as listed in the workspace. Cheaper than the whole list after a check or an edit."""
    _require(name)
    if _is_job(name):
        from .jobs import job_info

        return job_info(name)
    return program_info(name)


@app.get("/api/samples")
def samples():
    from .samples import catalog

    return catalog()


@app.post("/api/samples/{name}")
async def load_sample(name: str):
    from .samples import install

    try:
        result = await run_in_threadpool(install, name)
    except ProgramError as exc:
        raise HTTPException(400, str(exc))
    return result


@app.delete("/api/samples")
def remove_samples():
    from .samples import remove_all

    try:
        return {"removed": remove_all()}
    except ProgramError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/programs")
async def add_program(req: NewProgram):
    try:
        return await run_in_threadpool(create_program, req.name, req.cobol, {c.name: c.text for c in req.copybooks}, ROOT,
                                    {c.name: c.text for c in req.programs})
    except ProgramError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/jobs")
async def add_job(req: NewJob):
    from .jobs import create_job

    try:
        return await run_in_threadpool(create_job, req.name, req.jcl)
    except ProgramError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/programs/{name}/record")
async def re_record(name: str):
    """Run the real COBOL again on the generated inputs and save its answers (after the COBOL or the data changed)."""
    _require(name)
    if _is_job(name):
        from .jobs import record

        return {"sets": await run_in_threadpool(record, name)}
    from .cases import record_sets

    try:
        return {"sets": await run_in_threadpool(record_sets, name)}
    except LegacyRuntimeError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/programs/{name}")
def remove_program(name: str):
    try:
        delete_program(name)
    except ProgramError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": name}


@app.post("/api/programs/{name}/draft")
async def redraft(name: str):
    _require(name)
    if _is_job(name):
        raise HTTPException(400, "A job runs the Python of its programs. Translate those instead.")
    result = await run_in_threadpool(draft_python, name, ROOT, True)
    return result


@app.get("/api/source")
def source(program: str, implementation: str):
    _require(program, implementation)
    if _is_job(program):
        from .jobs import job_programs

        return {"legacy": (ROOT / "legacy" / program / f"{program}.jcl").read_text(encoding="utf-8-sig", errors="replace"), "called": {},
                "migrated": "", "spec": "", "editable": False, "job": True, "programs": job_programs(program)}
    impl_path = ROOT / (implementation.replace(".", "/") + ".py")
    spec_path = ROOT / "docs" / "specs" / f"{program}.md"
    return {
        "legacy": (ROOT / "legacy" / program / f"{program}.cbl").read_text(encoding="utf-8-sig", errors="replace"),
        # the programs it CALLs, by PROGRAM-ID, so the code view can show them too
        "called": {m.program_id: m.path.read_text(encoding="utf-8-sig", errors="replace") for m in _called(program)},
        "migrated": impl_path.read_text(encoding="utf-8-sig"),
        "spec": spec_path.read_text(encoding="utf-8") if spec_path.exists() else "",
        "editable": implementation == f"migrated.{program}",
    }


def _called(program: str):
    from .recorder import get_model

    try:
        return get_model(program)._every()[1:]
    except Exception:
        return []


@app.put("/api/source")
def save_source(req: SaveSource):
    _require(req.program)
    if _is_job(req.program):
        raise HTTPException(400, "A job has no Python of its own.")
    if len(req.code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(400, "Code is too large.")
    try:
        compile(req.code, f"migrated/{req.program}.py", "exec")
    except SyntaxError as exc:
        raise HTTPException(400, f"Syntax error on line {exc.lineno}: {exc.msg}")
    target = ROOT / "migrated" / f"{req.program}.py"
    target.parent.mkdir(exist_ok=True)
    target.write_text(req.code, encoding="utf-8")
    return {"saved": target.relative_to(ROOT).as_posix()}


@app.get("/api/layout")
def layout(program: str):
    _require(program)
    from .layout import leaves
    from .recorder import get_model

    model = get_model(program)
    files = []
    for f in model.all_files:
        rec = f.record
        fields = []
        for lf in leaves(rec) if rec else []:
            it = lf.item
            fields.append({"name": lf.name, "start": lf.offset + 1, "end": lf.offset + lf.width, "kind": it.kind, "usage": it.usage,
                           "digits": it.digits, "scale": it.scale, "signed": it.signed, "pic": it.pic})
        files.append({"name": f.name, "assign": f.assign, "input": f.is_input, "output": f.is_output, "lines": f.organization == "line",
                      "record": rec.name if rec else None, "size": f.size, "fields": fields,
                      "text": all(x["usage"] == "display" for x in fields)})
    return {"format": "fixed" if model.fixed else "free", "files": files, "console_input": model.all_accepts, "notes": model.notes,
            "unsupported": model.unsupported}


@app.get("/api/sample")
def sample(program: str, limit: int = 6):
    """Input to start a try from: the first records of the first saved test set, as text."""
    _require(program)
    from .cases import load_set, set_names, show
    from .recorder import get_model

    model = get_model(program)
    names = set_names(program)
    out = {"files": {f.assign: [] for f in model.inputs}, "stdin": [], "set": None}
    pick = "random" if "random" in names else (names[0] if names else None)
    if pick:
        case, _, _ = load_set(program, pick)
        for f in model.inputs:
            from .cases import _units

            units = _units(f, case.files.get(f.assign, b""))
            out["files"][f.assign] = [show(u).rstrip() for u in units[:max(1, min(limit, 50))]]
        out["stdin"] = case.stdin[:200]  # all of it: a shorter list can leave an input loop waiting forever
        out["set"] = pick
    return out


@app.get("/api/data")
def list_data(program: str):
    _require(program)
    if _is_job(program):
        from .jobs import load, set_names

        return {"sets": [{"set": n, "label": load(program, n)[2]["label"], "records": load(program, n)[2].get("records", 0), "console_lines": 0,
                          "removable": False, "cobol_error": load(program, n)[2].get("error")} for n in set_names(program)]}
    from .cases import describe_sets

    return {"sets": describe_sets(program)}


@app.post("/api/data/{program}")
async def upload_data(program: str, body: TestData):
    _require(program)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    import base64
    import binascii

    from .cases import ENC, add_uploaded

    try:
        if body.base64 is not None:
            data = base64.b64decode(body.base64, validate=True)
        else:
            data = (body.text or "").encode(ENC, errors="replace")
    except binascii.Error:
        raise HTTPException(400, "The file could not be read.")
    if body.console:
        stdin, data, target = data.decode(ENC).splitlines(), b"", None
    else:
        stdin, target = None, body.file
    try:
        return await run_in_threadpool(add_uploaded, program, body.filename, data, target, stdin, ROOT, body.code_page)
    except (ValueError, LegacyRuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/data/{program}/{name}")
def delete_data(program: str, name: str):
    _require(program)
    from .cases import remove_uploaded

    try:
        remove_uploaded(program, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": name}


@app.post("/api/verify")
async def run_verify(req: VerifyRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    args = ["verify", req.program, "--impl", req.implementation, "--rounds", str(req.rounds), "--json"]
    return await run_in_threadpool(_run_cli, args, config.VERIFY_TIMEOUT)


@app.post("/api/mutate")
async def run_mutate(req: MutateRequest):
    _require(req.program, req.implementation)
    return await run_in_threadpool(_run_cli, ["mutate", req.program, "--impl", req.implementation, "--json"], config.VERIFY_TIMEOUT)


@app.post("/api/try")
async def try_input(req: TryRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    payload = json.dumps({"files": req.files, "stdin": req.stdin, "set": req.set})
    return await run_in_threadpool(_run_cli, ["try", req.program, "--impl", req.implementation], config.COMPARE_TIMEOUT, payload)


@app.get("/api/report")
def last_report(program: str, implementation: str):
    """The last check of this Python, if any, with a flag saying whether the code changed since."""
    _require(program, implementation)
    from .programs import last_check

    p = ROOT / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
    if not p.exists():
        return {"report": None}
    body = json.loads(p.read_text(encoding="utf-8"))
    md = p.with_suffix(".md")
    body["markdown"] = md.read_text(encoding="utf-8") if md.exists() else ""
    return {"report": body, "status": last_check(implementation)}


@app.get("/api/download/{program}")
def download(program: str, what: str, implementation: str):
    _require(program, implementation)
    from .export import bundle, report_markdown, safe_filename

    if what == "bundle":
        name, data = bundle(program, implementation)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe_filename(name)}"'})
    if what == "python":
        text = (ROOT / (implementation.replace(".", "/") + ".py")).read_text(encoding="utf-8-sig")
        return Response(text, media_type="text/x-python", headers={"Content-Disposition": f'attachment; filename="{safe_filename(program)}.py"'})
    if what == "json":
        p = ROOT / "build" / "reports" / f"{implementation.replace('.', '_')}.json"
        if not p.exists():
            raise HTTPException(404, "No check has been run for this Python yet.")
        return Response(p.read_text(encoding="utf-8"), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{safe_filename(program)}-report.json"'})
    if what == "report":
        text = report_markdown(program, implementation)
        if text is None:
            raise HTTPException(404, "No check has been run for this Python yet.")
        return Response(text, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{safe_filename(program)}-report.md"'})
    raise HTTPException(400, "what must be bundle, python, report or json")


@app.get("/", response_class=HTMLResponse)
def index():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", app.state.token)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
