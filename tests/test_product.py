"""The product as a user meets it: add a program, check it, try input, upload data, and the API's defenses."""

import pytest
from fastapi.testclient import TestClient

from seance.api import app
from seance.programs import TEMPLATE, ProgramError, create_program, delete_program, program_names
from seance.recorder import cobc_available
from seance.verify import verify

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")
NAME = "zz_tpl_test"
client = TestClient(app, base_url="http://127.0.0.1")
H = {"x-seance-token": app.state.token}


@pytest.fixture
def added():
    if NAME in program_names():
        delete_program(NAME)
    info = create_program(NAME, TEMPLATE["cobol"])
    yield info
    delete_program(NAME)


@needs_cobol
def test_added_program_is_translated_and_matches(added):
    assert added["draft"]["translated"] and added["draft"]["gaps"] == []
    assert added["sets"]["edges"] > 0 and added["sets"]["random"] > 0
    assert verify(NAME, None, 5).matched


@needs_cobol
def test_broken_edit_is_caught(added):
    path = __import__("seance.recorder", fromlist=["ROOT"]).ROOT / "migrated" / f"{NAME}.py"
    text = path.read_text(encoding="utf-8")
    assert "True)], " in text, "the template's COMPUTE ... ROUNDED"
    path.write_text(text.replace("True)], ", "False)], ", 1), encoding="utf-8")
    report = verify(NAME, None, 5)
    assert not report.matched


@needs_cobol
def test_try_upload_and_remove_through_the_api(added):
    r = client.post("/api/try", headers=H, json={"program": NAME, "implementation": f"migrated.{NAME}",
                                                 "files": {"ORDERIN": ["A00001001000001000    "]}})
    assert r.status_code == 200 and r.json()["match"], r.text
    r = client.post(f"/api/data/{NAME}", headers=H, json={"filename": "orders.dat", "text": "A000010010000010000000"})
    assert r.status_code == 200, r.text
    assert any(s["set"] == r.json()["set"] for s in client.get(f"/api/data?program={NAME}").json()["sets"])
    assert client.delete(f"/api/data/{NAME}/{r.json()['set']}", headers=H).status_code == 200
    bad = client.post(f"/api/data/{NAME}", headers=H, json={"filename": "x", "text": "short"})
    assert bad.status_code == 400 and "whole number" in bad.json()["detail"]


def test_unknown_name_and_duplicates_are_refused():
    with pytest.raises(ProgramError):
        create_program("Bad Name", TEMPLATE["cobol"])
    with pytest.raises(ProgramError):
        create_program("payroll", TEMPLATE["cobol"])


@needs_cobol
def test_program_that_does_not_compile_is_cleaned_up():
    with pytest.raises(ProgramError, match="did not compile"):
        create_program("zz_broken", TEMPLATE["cobol"].replace("MOVE IN-ORDER-ID", "MOVE NOPE-NOPE"))
    assert "zz_broken" not in program_names()


def test_examples_are_read_only():
    r = client.put("/api/source", headers=H, json={"program": "payroll", "code": "x = 1"})
    assert r.status_code == 403
    r = client.delete("/api/programs/payroll", headers=H)
    assert r.status_code == 400


def test_writes_need_the_session_token_and_json():
    assert client.post("/api/verify", json={"program": "payroll", "implementation": "migrated.payroll"}).status_code == 403
    r = client.post("/api/verify", headers={**H, "content-type": "text/plain"}, content="{}")
    assert r.status_code == 415


def test_other_hosts_are_refused():
    assert TestClient(app, base_url="http://evil.example").get("/api/about").status_code == 400


def test_catalog_reports_files_and_status():
    progs = {p["name"]: p for p in client.get("/api/programs").json()["programs"]}
    assert progs["account_report"]["files"][0]["assign"] in ("PRTLINE", "ACCTREC")
    assert progs["add_amounts"]["console_input"]
    layout = client.get("/api/layout?program=account_report").json()
    acct = next(f for f in layout["files"] if f["assign"] == "ACCTREC")
    assert acct["text"] is False, "packed fields cannot be typed as text"
