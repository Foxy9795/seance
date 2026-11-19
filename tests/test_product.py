"""The product as a user meets it: add a program, check it, try input, upload data, and the API's defenses."""

import pytest
from fastapi.testclient import TestClient

from sample_cobol import TEMPLATE
from seance.api import app
from seance.programs import ProgramError, create_program, delete_program, implementations, program_names
from seance.recorder import cobc_available
from seance.samples import SAMPLES, catalog, install, remove_all, sample_names
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


def test_every_workspace_program_can_be_edited_and_deleted():
    src = client.get("/api/source?program=payroll&implementation=migrated.payroll").json()
    assert src["editable"] is True
    same = client.put("/api/source", headers=H, json={"program": "payroll", "code": src["migrated"]})
    assert same.status_code == 200, same.text
    assert client.put("/api/source", headers=H, json={"program": "payroll", "code": "x = ("}).status_code == 400


def test_the_product_ships_no_example_in_the_workspace():
    """Examples live in samples/ and reach the workspace only when the guide (or `seance samples load`) copies them in."""
    assert not (SAMPLES.parent / "examples").exists()


def test_sample_catalog_is_complete():
    data = catalog()
    names = [s["name"] for s in data["samples"]]
    assert len(names) == len(set(names)) and "payroll" in names and "nightly_batch" in names
    groups = {g["id"] for g in data["groups"]}
    for s in data["samples"]:
        assert s["group"] in groups and s["summary"] and s["tags"], s["name"]
        folder = SAMPLES / s["name"]
        assert (folder / "legacy").is_dir() and (folder / "fixtures").is_dir(), s["name"]
        job = (folder / "legacy" / f"{s['name']}.jcl").exists()
        assert job or (folder / "migrated.py").exists(), s["name"]
        assert all(r in names for r in s["requires"])
    assert sorted(names) == sorted(sample_names())


def test_sample_loads_into_a_workspace_and_removes_cleanly(tmp_path):
    r = install("payroll", tmp_path)
    assert r["added"] == ["payroll"]
    assert (tmp_path / "legacy/payroll/.sample").exists() and (tmp_path / "migrated/payroll_naive.py").exists()
    assert {i.role for i in implementations("payroll", tmp_path)} == {"yours", "naive"}
    assert install("payroll", tmp_path)["already"] == ["payroll"], "loading twice changes nothing"
    assert remove_all(tmp_path) == ["payroll"]
    assert not (tmp_path / "legacy/payroll").exists() and not (tmp_path / "migrated/payroll.py").exists()
    assert not (tmp_path / "migrated/payroll_naive.py").exists() and not (tmp_path / "fixtures/payroll").exists()


def test_a_job_sample_brings_the_programs_it_runs(tmp_path):
    assert install("nightly_batch", tmp_path)["added"] == ["customer_master", "accounts", "nightly_batch"]
    assert sorted(remove_all(tmp_path)) == ["accounts", "customer_master", "nightly_batch"]


def test_a_sample_never_replaces_your_own_program(tmp_path):
    (tmp_path / "legacy" / "payroll").mkdir(parents=True)
    with pytest.raises(ProgramError, match="already has a program named 'payroll'"):
        install("payroll", tmp_path)
    assert not (tmp_path / "legacy/payroll/.sample").exists()


def test_samples_api():
    cat = client.get("/api/samples").json()
    assert {s["name"] for s in cat["samples"]} == set(sample_names())
    assert client.post("/api/samples/nothing_here", headers=H, json={}).status_code == 400
    assert client.post("/api/samples/payroll").status_code == 403, "loading needs the session token"


def test_catalog_and_about_describe_the_product():
    about = client.get("/api/about").json()
    assert about["version"].count(".") == 2 and about["workspace"] and about["supported"]
    listing = client.get("/api/programs").json()
    progs = {p["name"]: p for p in listing["programs"]}
    assert progs["payroll"]["sample"] is True and "demo" not in listing
    assert "indexed" in progs["customer_master"]["kinds"] and "calls" in progs["order_pricing"]["kinds"]
    assert "sql" in progs["payment_posting"]["kinds"] and "cics" in progs["customer_inquiry"]["kinds"]
    assert progs["nightly_batch"]["kinds"] == ["jcl"]
    one = client.get("/api/programs/payroll").json()
    assert one["name"] == "payroll" and one["implementations"]
    assert client.get("/api/programs/nothing_here").status_code == 404


@needs_cobol
def test_a_job_can_be_added_and_deleted_through_the_api():
    jcl = (SAMPLES / "nightly_batch" / "legacy" / "nightly_batch.jcl").read_text(encoding="utf-8")
    r = client.post("/api/jobs", headers=H, json={"name": "zz_job_test", "jcl": jcl})
    try:
        assert r.status_code == 200, r.text
        assert r.json()["sets"]["edges"] > 0
        info = client.get("/api/programs/zz_job_test").json()
        assert info["kind"] == "job" and info["sample"] is False and len(info["steps"]) == 4
        assert client.post("/api/jobs", headers=H, json={"name": "zz_job_test", "jcl": jcl}).status_code == 400
    finally:
        assert client.delete("/api/programs/zz_job_test", headers=H).status_code == 200
    missing = client.post("/api/jobs", headers=H, json={"name": "zz_job_two", "jcl": jcl.replace("PGM=CUSTMAST", "PGM=NOSUCH")})
    assert missing.status_code == 400 and "NOSUCH" in missing.json()["detail"]
    assert "zz_job_two" not in [p["name"] for p in client.get("/api/programs").json()["programs"]]


@needs_cobol
def test_cobol_answers_can_be_recorded_again(added):
    r = client.post(f"/api/programs/{NAME}/record", headers=H, json={})
    assert r.status_code == 200 and r.json()["sets"]["edges"] > 0, r.text


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
