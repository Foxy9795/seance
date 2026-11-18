"""FastAPI app: serves the UI and runs verifications.

Start with: python -m uvicorn seance.api:app   (binds to 127.0.0.1 only, keep it that way:
the editor lets you save Python that the verifier then runs).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .programs import (
    MAX_SOURCE_BYTES,
    TEMPLATE,
    ProgramError,
    create_program,
    delete_program,
    implementations,
    is_user_program,
    program_names,
    scaffold,
)
from .recorder import ROOT, cobc_available, cobol_env
from .report import to_markdown  # noqa: F401  (kept for API symmetry)

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


VERIFY_TIMEOUT = int(os.environ.get("SEANCE_VERIFY_TIMEOUT", "600"))
COMPARE_TIMEOUT = 120


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
        raise HTTPException(504, f"Timed out after {timeout} seconds. Does the migration loop forever?")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(500, (proc.stderr or proc.stdout or "no output").strip()[-1500:])


class VerifyRequest(BaseModel):
    program: str
    implementation: str
    examples: int = Field(default=40, ge=5, le=200)


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


class Copybook(BaseModel):
    name: str
    text: str


class NewProgram(BaseModel):
    name: str
    cobol: str
    copybooks: list[Copybook] = Field(default_factory=list, max_length=10)


class SaveSource(BaseModel):
    program: str
    code: str


@app.get("/api/programs")
def programs():
    return {
        "legacy_runtime": cobc_available(),
        "programs": [
            {
                "name": n,
                "user_added": is_user_program(n),
                "implementations": [{"module": i.module, "label": i.label} for i in implementations(n)],
            }
            for n in program_names()
        ],
    }


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


@app.get("/api/source")
def source(program: str, implementation: str):
    _require(program, implementation)
    impl_path = ROOT / (implementation.replace(".", "/") + ".py")
    spec_path = ROOT / "docs" / "specs" / f"{program}.md"
    return {
        "legacy": (ROOT / "legacy" / program / f"{program}.cbl").read_text(encoding="utf-8"),
        "migrated": impl_path.read_text(encoding="utf-8"),
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


@app.post("/api/scaffold/{program}")
def make_stub(program: str):
    _require(program)
    path = scaffold(program)
    return {"path": path.relative_to(ROOT).as_posix()}


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


@app.post("/api/verify")
async def run_verify(req: VerifyRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    args = ["verify", req.program, "--impl", req.implementation, "--examples", str(req.examples), "--json"]
    body = await run_in_threadpool(_run_cli, args, VERIFY_TIMEOUT)
    if "error" in body:
        raise HTTPException(422, body["error"])
    return body


@app.post("/api/compare")
async def compare(req: CompareRequest):
    _require(req.program, req.implementation)
    if not cobc_available():
        raise HTTPException(503, "GnuCOBOL runtime not found")
    args = ["compare", req.program, "--impl", req.implementation]
    for line in req.lines:
        args.append(f"--line={line.rstrip()}")  # '=' form: a record may start with '-'
    body = await run_in_threadpool(_run_cli, args, COMPARE_TIMEOUT)
    if "error" in body:
        raise HTTPException(422, body["error"])
    return body


@app.get("/", response_class=HTMLResponse)
def index():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", app.state.token)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

