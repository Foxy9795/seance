"""The user-facing flow: add your own COBOL, get a stub, edit it, verify it, delete it."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seance.api import app
from seance.programs import TEMPLATE, ProgramError, create_program, delete_program, program_names
from seance.recorder import ROOT, cobc_available
from seance.verify import verify

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")
NAME = "zz_tpl_test"


def authed() -> TestClient:
    """A client that looks like the real page: addressed to 127.0.0.1 and carrying the session token."""
    return TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-Seance-Token": app.state.token})

GOOD_MIGRATION = '''
from decimal import Decimal
from generated.zz_tpl_test_records import InRecord, OutRecord
from seance.cobol_num import store


def transform(rec: InRecord) -> OutRecord:
    discount = store(rec.amount * rec.pct / 100, 7, 2, signed=True, rounded=True)
    total = store(rec.amount - discount, 8, 2, signed=True)
    return OutRecord(order_id=rec.order_id, discount=discount, total=total, shown=total)
'''


@pytest.fixture
def cleanup():
    yield
    if (ROOT / "legacy" / NAME / ".user").exists():
        delete_program(NAME)


@pytest.mark.parametrize("bad", ["../evil", "Has Caps", "x", "class", "a" * 40, "with-dash"])
def test_bad_names_are_rejected(bad):
    with pytest.raises(ProgramError):
        create_program(bad, TEMPLATE["cobol"])


def test_cannot_overwrite_existing_program():
    with pytest.raises(ProgramError, match="already exists"):
        create_program("payroll", TEMPLATE["cobol"])


def test_cannot_delete_builtin_program():
    with pytest.raises(ProgramError, match="you added"):
        delete_program("payroll")


def test_unsupported_field_type_is_explained_and_leaves_nothing_behind():
    packed = TEMPLATE["cobol"].replace("05  IN-AMOUNT    PIC S9(5)V99.", "05  IN-AMOUNT    PIC S9(5)V99 COMP-3.")
    with pytest.raises(ProgramError, match="COMP-3"):
        create_program(NAME, packed)
    assert not (ROOT / "legacy" / NAME).exists()


def test_program_without_files_is_explained():
    with pytest.raises(ProgramError, match="No SELECT"):
        create_program(NAME, "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n")
    assert not (ROOT / "legacy" / NAME).exists()


@needs_cobol
def test_cobol_that_does_not_compile_leaves_nothing_behind():
    broken = TEMPLATE["cobol"].replace("STOP RUN.", "STOP RUNN RUN RUN")
    with pytest.raises(ProgramError, match="did not compile"):
        create_program(NAME, broken)
    assert not (ROOT / "legacy" / NAME).exists()
    assert not (ROOT / "migrated" / f"{NAME}.py").exists()


@needs_cobol
def test_full_user_flow(cleanup):
    info = create_program(NAME, TEMPLATE["cobol"])
    assert NAME in program_names()
    assert info["fixtures"]["edges"] > 5
    assert info["format"] == "fixed"
    assert (ROOT / "docs" / "specs" / f"{NAME}.md").exists()

    # adding a program drafts the Python automatically, and the draft matches the real COBOL
    assert info["draft"]["translated"] and info["draft"]["gaps"] == []
    stub = ROOT / "migrated" / f"{NAME}.py"
    drafted = stub.read_text(encoding="utf-8")
    assert "Written by the Séance translator" in drafted
    assert verify(NAME, examples=10).matched

    api = authed()
    assert api.put("/api/source", json={"program": NAME, "code": "def broken(:"}).status_code == 400  # syntax errors are refused, file untouched
    assert stub.read_text(encoding="utf-8") == drafted

    broken = drafted.replace('"OUT-DISCOUNT", lambda: S.n("IN-AMOUNT") * S.n("IN-PCT") / D("100"), True', '"OUT-DISCOUNT", lambda: S.n("IN-AMOUNT") * S.n("IN-PCT") / D("100"), False')
    assert broken != drafted
    assert api.put("/api/source", json={"program": NAME, "code": broken}).status_code == 200
    assert not verify(NAME, examples=10).matched  # a dropped ROUNDED is caught, and the edit is picked up

    assert api.post(f"/api/programs/{NAME}/draft", json={}).json()["translated"]  # redraft restores it, keeping a .bak
    assert (ROOT / "migrated" / f"{NAME}.py.bak").read_text(encoding="utf-8") == broken
    assert verify(NAME, examples=10).matched

    # your own test data: run through the COBOL once, then replayed by every check
    data = "ORD9A1" + "1234567" + "01250" + "\n" + "ORD9A2" + "999999y" + "10000"
    up = api.post(f"/api/data/{NAME}", json={"filename": "Prod Sample.dat", "text": data})
    assert up.status_code == 200, up.text
    assert up.json()["records"] == 2 and up.json()["label"] == "Your data: Prod Sample.dat"
    report = verify(NAME, examples=5)
    assert report.fixtures[up.json()["set"]]["records"] == 2 and report.matched
    assert api.post(f"/api/data/{NAME}", json={"filename": "x", "text": "X" * 200}).status_code == 400  # longer than the record
    assert api.delete(f"/api/data/{NAME}/{up.json()['set']}").status_code == 200

    delete_program(NAME)
    for p in (ROOT / "legacy" / NAME, ROOT / "generated" / f"{NAME}_records.py", ROOT / "fixtures" / NAME, stub, stub.with_suffix(".py.bak")):
        assert not Path(p).exists()


def test_program_name_defaults_to_the_program_id():
    from seance.programs import suggest_name

    assert suggest_name("       PROGRAM-ID. ACCT-UPDATE.") == "acct_update"
    assert suggest_name("PROGRAM-ID. 'PAY01'.") == "pay01"
    assert suggest_name("no id here") == "program"


@needs_cobol
def test_api_metadata_and_downloads():
    client = authed()
    data = client.get("/api/programs").json()
    acc = next(p for p in data["programs"] if p["name"] == "accounts")
    assert acc["title"] == "Accounts" and acc["format"] == "fixed" and acc["input"]["file"] == "ACCTIN" and not acc["input"]["lines"]
    assert data["demo"] in {p["name"] for p in data["programs"] if any(i["role"] == "naive" for i in p["implementations"])}
    about = client.get("/api/about").json()
    assert about["supported"] and about["not_yet"] and about["defaults"]["rounds"] > 0
    z = client.get("/api/download/accounts", params={"what": "bundle", "implementation": "migrated.accounts"})
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert client.get("/api/download/accounts", params={"what": "nope", "implementation": "migrated.accounts"}).status_code == 400
    sets = client.get("/api/data", params={"program": "accounts"}).json()["sets"]
    assert {s["set"] for s in sets} >= {"edges", "random"} and all(s["label"] for s in sets)


@needs_cobol
def test_api_programs_template_and_compare():
    client = authed()
    names = [p["name"] for p in client.get("/api/programs").json()["programs"]]
    assert {"payroll", "interest", "inventory", "loan"} <= set(names)
    assert client.get("/api/template").json()["name"] == "discount"

    r = client.post("/api/compare", json={"program": "payroll", "implementation": "migrated.payroll", "lines": ["A1    075000001", "-bad"]})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows[0]["match"] and rows[0]["legacy"] == "A1    0000009300000009-00001166"


def test_api_rejects_unknown_things():
    client = authed()
    assert client.get("/api/source", params={"program": "nope", "implementation": "x"}).status_code == 404
    assert client.post("/api/verify", json={"program": "payroll", "implementation": "os.system", "examples": 5}).status_code == 404
    assert client.put("/api/source", json={"program": "payroll", "code": "def broken(:"}).status_code == 403  # shipped examples are read-only
    assert client.delete("/api/programs/payroll").status_code == 400


def test_security_wrong_host_is_refused():
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 must not be answered."""
    c = TestClient(app, base_url="http://evil.example")
    assert c.get("/api/programs").status_code == 400


def test_security_state_changes_need_the_session_token():
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    body = {"name": "zz_nope", "cobol": "x"}
    assert c.post("/api/programs", json=body).status_code == 403
    assert c.put("/api/source", json={"program": "payroll", "code": "x = 1"}).status_code == 403
    assert c.delete("/api/programs/payroll").status_code == 403
    assert TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-Seance-Token": "guess"}).post("/api/programs", json=body).status_code == 403
    assert not (ROOT / "legacy" / "zz_nope").exists()


def test_security_json_content_type_is_required():
    c = authed()
    r = c.post("/api/verify", content='{"program":"payroll"}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_token_is_only_in_the_served_page():
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    page = c.get("/").text
    assert app.state.token in page and "__SESSION_TOKEN__" not in page
    assert c.get("/").headers["cache-control"] == "no-store"


def test_shipped_examples_cannot_be_overwritten():
    c = authed()
    before = (ROOT / "migrated" / "payroll.py").read_text(encoding="utf-8")
    assert c.put("/api/source", json={"program": "payroll", "code": "x = 1\n"}).status_code == 403
    assert (ROOT / "migrated" / "payroll.py").read_text(encoding="utf-8") == before
    src = c.get("/api/source", params={"program": "payroll", "implementation": "migrated.payroll"}).json()
    assert src["editable"] is False


def test_compare_rejects_multiline_and_nul_records():
    c = authed()
    for bad in ("A\nB", "A\x00B", "x" * 600):
        r = c.post("/api/compare", json={"program": "payroll", "implementation": "migrated.payroll", "lines": [bad]})
        assert r.status_code == 422

