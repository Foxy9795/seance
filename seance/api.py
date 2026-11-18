"""FastAPI app: serves the UI and runs checks.

Start with scripts/run.ps1 (or: python -m uvicorn seance.api:app). It binds to 127.0.0.1 only. Keep it that
way: the editor saves Python that the checker then runs.
"""

from __future__ import annotations

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

from . import config
from .programs import (
    MAX_SOURCE_BYTES,
    TEMPLATE,
    ProgramError,
    create_program,
    delete_program,
    draft_python,
    implementations,
    is_user_program,
    program_info,
    program_names,
)
from .recorder import ROOT, cobc_available, cobol_env

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


def _require(program: str, implementation: str | None = None) -> None:
    if program not in program_names():
        raise HTTPException(404, f"unknown program {program!r}")
    if implementation is not None and implementation not in [i.module for i in implementations(program)]:
        raise HTTPException(404, f"unknown implementation {implementation!r}")


def _run_cli(args: list[str], timeout: int) -> dict:
    """Run the CLI in a fresh process: no stale imports, and a hung migration cannot hang the server."""
    env = cobol_env()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # never run a stale .pyc after a same-second edit
    try:
        proc = subprocess.run([sys.executable, "-m", "seance", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
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
    copybooks: list[Copybook] = Field(default_factory=list, max_length=20)


class VerifyRequest(BaseModel):
    program: str
    implementation: str
    examples: int = Field(default=config.DEFAULT_ROUNDS, ge=5, le=config.MAX_ROUNDS)


class CompareRequest(BaseModel):
    program: str
    implementation: str
    lines: list[str] = Field(min_length=1, max_length=50)

    @field_validator("lines")
    @classmethod
    def _plain_records(cls, lines: list[str]) -> list[str]:
        for line in lines:
            if len(line) > 500 or any(c in line for c in "\r\n\x00"):
                raise ValueError("Each record must be one line of at most 500 characters.")
        return lines


class MutateRequest(BaseModel):
    program: str
    implementation: str


class SaveSource(BaseModel):
    program: str
    code: str


class TestData(BaseModel):
    filename: str = "data.txt"
    text: str = Field(max_length=5_000_000)


# ---------------------------------------------------------------- endpoints

@app.get("/api/about")
def about():
    return {
        "legacy_runtime": cobc_available(),
        "defaults": {"rounds": config.DEFAULT_ROUNDS, "max_rounds": config.MAX_ROUNDS, "max_data_records": config.MAX_DATA_RECORDS},
        "supported": config.SUPPORTED,
        "not_yet": config.NOT_YET,
    }


@app.get("/api/programs")
def programs():
    infos = [program_info(n) for n in program_names()]
    demo = next((p["name"] for p in infos if any(i["role"] == "naive" for i in p["implementations"])), None)
    return {"legacy_runtime": cobc_available(), "programs": infos, "demo": demo}


@app.get("/api/template")
def template():
    return {"name": TEMPLATE["name"], "cobol": TEMPLATE["cobol"], "copybooks": TEMPLATE["copybooks"]}


@app.post("/api/programs")
async def add_program(req: NewProgram):
    try:
        return await run_in_threadpool(create_program, req.name, req.cobol, {c.name: c.text for c in req.copybooks})
    except ProgramError as exc:
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
    if not is_user_program(name):
        raise HTTPException(403, "The shipped examples keep their reference Python. Add your own program to draft one.")
    result = await run_in_threadpool(draft_python, name, ROOT, True)
    return result


@app.get("/api/source")
def source(program: str, implementation: str):
    _require(program, implementation)
    impl_path = ROOT / (implementation.replace(".", "/") + ".py")
    spec_path = ROOT / "docs" / "specs" / f"{program}.md"
    return {
        "legacy": (ROOT / "legacy" / program / f"{program}.cbl").read_text(encoding="utf-8-sig", errors="replace"),
        "migrated": impl_path.read_text(encoding="utf-8-sig"),
        "spec": spec_path.read_text(encoding="utf-8") if spec_path.exists() else "",
        # The shipped examples are reference solutions: read-only. Only programs you added can be edited here.
        "editable": implementation == f"migrated.{program}" and is_user_program(program),
    }


@app.put("/api/source")
def save_source(req: SaveSource):
    _require(req.program)
    if not is_user_program(req.program):
        raise HTTPException(403, "The shipped examples are read-only. Add your own program to edit its Python.")
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
    from .recorder import get_model

    model = get_model(program)
    out = {"format": "fixed" if model.fixed else "free", "notes": model.notes}
    for key, lay, io in (("input", model.in_layout, model.input), ("output", model.out_layout, model.output)):
        out[key] = {
            "width": lay.width,
            "file": io.assign,
            "organization": io.organization,
            "fields": [
                {"name": f.name, "start": f.offset + 1, "end": f.offset + f.width, "kind": f.kind, "digits": f.digits, "scale": f.scale, "signed": f.signed, "sign": f.sign, "pic": f.pic}
                for f in lay.fields
            ],
        }
    return out


@app.get("/api/sample")
def sample(program: str):
    """A realistic input record to start from: the first saved random record, or a generated one."""
    _require(program)
    from .recorder import get_model, random_inputs

    saved = ROOT / "fixtures" / program / "random.in"
    if saved.exists():
        lines = saved.read_text(encoding="latin-1").splitlines()
        if lines:
            return {"line": lines[0]}
    return {"line": random_inputs(get_model(program).in_layout, 1, seed=7)[0]}


@app.get("/api/data")
def list_data(program: str):
    _require(program)
    from .testdata import describe_sets

    return {"sets": describe_sets(program)}


@app.post("/api/data/{program}")
async def upload_data(program: str, body: TestData):
    _require(program)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    from .testdata import add_set

    try:
        return await run_in_threadpool(add_set, program, body.filename, body.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/data/{program}/{name}")
def delete_data(program: str, name: str):
    _require(program)
    from .testdata import remove_set

    try:
        remove_set(program, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": name}


@app.post("/api/verify")
async def run_verify(req: VerifyRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    args = ["verify", req.program, "--impl", req.implementation, "--examples", str(req.examples), "--json"]
    return await run_in_threadpool(_run_cli, args, config.VERIFY_TIMEOUT)


@app.post("/api/mutate")
async def run_mutate(req: MutateRequest):
    _require(req.program, req.implementation)
    return await run_in_threadpool(_run_cli, ["mutate", req.program, "--impl", req.implementation, "--json"], config.VERIFY_TIMEOUT)


@app.post("/api/compare")
async def compare(req: CompareRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    args = ["compare", req.program, "--impl", req.implementation]
    for line in req.lines:
        args.append(f"--line={line.rstrip()}")  # '=' form: a record may start with '-'
    return await run_in_threadpool(_run_cli, args, config.COMPARE_TIMEOUT)


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
    if what == "report":
        text = report_markdown(program, implementation)
        if text is None:
            raise HTTPException(404, "No check has been run for this Python yet.")
        return Response(text, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{safe_filename(program)}-report.md"'})
    raise HTTPException(400, "what must be bundle, python or report")


@app.get("/", response_class=HTMLResponse)
def index():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", app.state.token)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
