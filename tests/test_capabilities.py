"""Analysis, assessment, parallel runs against mainframe output, history, reports and CI output, on the real samples."""

import io
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest
from fastapi.testclient import TestClient

from seance.analyze import analyze, gherkin, plain, portfolio, portfolio_csv
from seance.api import app
from seance.cases import add_golden, describe_sets, load_set, remove_uploaded, run_cobol, set_names
from seance.export import bundle, report_html
from seance.recorder import ROOT, cobc_available, compile_legacy, get_model
from seance.report import history, junit_xml
from seance.verify import verify

needs_cobol = pytest.mark.skipif(not cobc_available(), reason="GnuCOBOL not installed")
client = TestClient(app, base_url="http://127.0.0.1")
H = {"x-seance-token": app.state.token}


# ---------------------------------------------------------------- analysis
def test_conditions_are_put_into_plain_words_and_literals_are_left_alone():
    assert plain("IN-HOURS > 40") == "IN-HOURS is greater than 40"
    assert plain("WS-EOF = 'Y' AND A NOT = B") == "WS-EOF equals 'Y' and A does not equal B"
    assert plain("X >= 5 OR Y <= 'a>=b'") == "X is at least 5 or Y is at most 'a>=b'"
    assert plain("AT-END", {"AT-END": "WS-EOF = 'Y'"}) == "AT-END (WS-EOF = 'Y')"


def test_payroll_analysis_finds_the_rules_the_flow_and_the_lineage():
    a = analyze("payroll")
    m = a["metrics"]
    assert m["paragraphs"] == 2 and m["goto"] == 0 and m["complexity"] == 7 and m["rating"] == "Low"
    whens = {r["when"] for r in a["rules"]}
    assert "IN-HOURS is greater than 40" in whens and "WS-GROSS is at most 500" in whens and "in every other case" in whens
    rounded = [r for r in a["rules"] if r["kind"] == "calculation" or r["kind"] == "decision"]
    assert any("rounded half away from zero" in t for r in rounded for t in r["then"])
    assert {(e["from"], e["to"], e["kind"]) for e in a["edges"]} == {("MAIN-PARA", "PROCESS-PARA", "perform")}
    out_net = next(l for l in a["lineage"] if l["field"] == "OUT-NET")
    assert out_net["from"] == ["IN-HOURS", "IN-RATE"] and "WS-TAX" in out_net["via"]
    assert a["unreferenced"] == []


def test_a_decision_is_not_listed_twice():
    a = analyze("payroll")
    lines = [r["line"] for r in a["rules"] if r["kind"] in ("decision", "case", "calculation")]
    assert len(lines) == len(set(lines)), "every statement is described once"


def test_gherkin_reads_like_scenarios():
    text = gherkin(analyze("payroll"))
    assert text.startswith("Feature: PAYROLL") and "Scenario: R" in text and "Given IN-HOURS is greater than 40" in text
    assert 'until WS-EOF equals "Y"' in text


def test_unreferenced_paragraphs_and_fall_through_are_found(tmp_path, monkeypatch):
    from seance.analyze import _build, _flow
    from seance.cobol_src import normalize

    src = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WORK-PARA THRU WORK-END
           GO TO FINISH-PARA.
       WORK-PARA.
           DISPLAY 'A'.
       WORK-MID.
           DISPLAY 'B'.
       WORK-END.
           DISPLAY 'C'.
       ORPHAN-PARA.
           DISPLAY 'never'.
       FINISH-PARA.
           STOP RUN.
"""
    lines = normalize(src, True)
    start = next(i for i, l in enumerate(lines) if l.text.strip().startswith("PROCEDURE DIVISION"))
    paras, _ = _build(lines, start)
    edges, flow, _calls = _flow(paras, {p.name for p in paras} - {"(start)"}, {})
    assert {p.name for p in paras} >= {"MAIN-PARA", "WORK-MID", "ORPHAN-PARA"}
    dead = [p.name for p in paras if p.name not in flow["live"]]
    assert dead == ["ORPHAN-PARA"], "WORK-MID is inside the PERFORM THRU range, so it runs"
    assert ("MAIN-PARA", "FINISH-PARA", "goto") in {(e["from"], e["to"], e["kind"]) for e in edges}


def test_job_analysis_lists_steps_and_conditions():
    a = analyze("nightly_batch")
    assert a["job"] and a["metrics"]["steps"] == 4 and [p["name"] for p in a["paragraphs"]] == ["SORTTRAN", "UPDATE", "MONTHEND", "BACKUP"]
    assert "UPDATE.RC = 0" in next(p for p in a["paragraphs"] if p["name"] == "MONTHEND")["condition"]


def test_sql_and_cics_programs_do_not_count_supplied_records_as_their_own_data():
    for name in ("payment_posting", "customer_inquiry"):
        d = analyze(name)["dictionary"]
        assert not [x for x in d if x["name"].startswith(("DFHAID", "DFHBMSCA", "DFHEIBLK", "SQLCA", "CIB-", "SQB-"))]
        assert not [x for x in d if x["unused"]], f"{name}: host variables and map fields are used"


def test_assessment_covers_everything_and_orders_migration_waves():
    p = portfolio()
    names = {r["name"] for r in p["rows"]}
    assert {"payroll", "nightly_batch", "order_pricing"} <= names
    assert p["totals"]["uses_sql"] == 1 and p["totals"]["uses_cics"] == 1 and p["totals"]["jobs"] == 1
    kinds = {n["id"]: n["kind"] for n in p["nodes"]}
    assert kinds["pricer"] == "called" and kinds["nosuchpg"] == "missing"
    wave_of = {n: i for i, w in enumerate(p["waves"]) for n in w}
    assert wave_of["nightly_batch"] > wave_of["customer_master"] and "pricer" not in wave_of
    csv = portfolio_csv(p).splitlines()
    assert csv[0].startswith("Program,Kind") and len(csv) == len(p["rows"]) + 1


def test_analysis_api_and_downloads():
    r = client.get("/api/analysis?program=payroll")
    assert r.status_code == 200 and r.json()["metrics"]["paragraphs"] == 2
    g = client.get("/api/analysis/rules?program=payroll")
    assert g.status_code == 200 and "attachment" in g.headers["content-disposition"] and g.text.startswith("Feature: PAYROLL")
    assert client.get("/api/analysis?program=nothing_here").status_code == 404
    assert client.get("/api/portfolio").json()["totals"]["programs"] >= 10
    assert client.get("/api/portfolio.csv").headers["content-type"].startswith("text/csv")


# ---------------------------------------------------------------- history, reports, CI output
@needs_cobol
def test_every_check_is_kept_in_the_history_and_a_report_page_can_be_made():
    verify("inventory", None, 5)
    from seance.report import write_reports

    write_reports(verify("inventory", None, 5), ROOT)
    write_reports(verify("inventory", None, 5), ROOT)
    rows = history("migrated.inventory", ROOT)
    assert len(rows) >= 2 and rows[0]["matched"] is True and rows[0]["cobol"] and rows[0]["python"]
    page = report_html("inventory")
    assert "Spirit matched" in page and "<style>" in page and "inventory" in page and "<script" not in page
    r = client.get("/api/history?program=inventory&implementation=migrated.inventory")
    assert r.status_code == 200 and len(r.json()["history"]) >= 2
    assert client.get("/api/download/inventory?what=html&implementation=migrated.inventory").headers["content-type"].startswith("text/html")


def test_a_report_page_escapes_what_it_shows():
    results = [{"name": "<b>x</b>", "matched": False, "summary": 'say "hi" & <leave>', "detail": "a<b>", "seconds": 1.5}]
    root = ET.fromstring(junit_xml(results, 1.5))
    assert root.get("failures") == "1" and root[0].get("name") == "<b>x</b>" and root[0][0].get("message") == 'say "hi" & <leave>'


def test_junit_output_separates_failures_from_errors_and_passes():
    xml = junit_xml([{"name": "a", "matched": True, "summary": "", "seconds": 1}, {"name": "b", "matched": False, "summary": "3 lines differ", "detail": "x", "seconds": 2},
                     {"name": "c", "matched": False, "error": "boom", "summary": "could not run", "seconds": 0}], 3)
    root = ET.fromstring(xml)
    assert (root.get("tests"), root.get("failures"), root.get("errors")) == ("3", "1", "1")
    assert [c.find("failure") is not None for c in root] == [False, True, False] and root[2].find("error") is not None


@needs_cobol
def test_check_all_returns_the_exit_code_a_pipeline_needs(tmp_path):
    out = tmp_path / "junit.xml"
    run = subprocess.run([sys.executable, "-m", "seance", "check-all", "--only", "inventory,interest", "--rounds", "5", "--junit", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    root = ET.parse(out).getroot()
    assert root.get("tests") == "2" and root.get("failures") == "0"
    nothing = subprocess.run([sys.executable, "-m", "seance", "check-all", "--only", "no_such_program"], cwd=ROOT, capture_output=True, text=True)
    assert nothing.returncode == 2


# ---------------------------------------------------------------- the packaged test suite
@needs_cobol
@pytest.mark.parametrize("program", ["payroll", "customer_master", "account_report", "order_pricing"])
def test_the_package_carries_a_suite_that_passes_without_seance(program, tmp_path):
    name, data = bundle(program)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert f"{program}_python/tests/test_{program}.py" in z.namelist() and any("/tests/data/edges/" in n for n in z.namelist())
    assert z.namelist().count(f"{program}_python/README.md") == 1
    z.extractall(tmp_path)
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=tmp_path / f"{program}_python", capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-1500:]


def test_the_package_skips_the_suite_for_programs_that_need_a_database_or_cics():
    names = zipfile.ZipFile(io.BytesIO(bundle("payment_posting")[1])).namelist()
    assert not [n for n in names if "/tests/" in n]


# ---------------------------------------------------------------- parallel run against mainframe output
@needs_cobol
def test_a_parallel_run_checks_the_python_against_the_mainframes_output():
    model = get_model("payroll")
    case, expected, _ = load_set("payroll", set_names("payroll")[0])
    inp = case.files["INPUT.DAT"]
    cobol = run_cobol(compile_legacy("payroll"), model, case)
    mainframe_out = cobol.outputs["OUTPUT.DAT"]
    ebcdic_in = inp.decode("latin-1").encode("cp037")
    ebcdic_out = mainframe_out.decode("latin-1").replace("\r\n", "\n").encode("cp037")  # a mainframe writes text in EBCDIC
    made = add_golden("payroll", "prod-run.dat", {"INPUT.DAT": inp}, {"OUTPUT.DAT": mainframe_out}, root=ROOT)
    try:
        assert made["set"].startswith("golden-") and made["cobol_agrees"] is True and made["filled_from_cobol"] == []
        listed = next(s for s in describe_sets("payroll") if s["set"] == made["set"])
        assert listed["golden"] and listed["removable"] and listed["cobol_agrees"]
        assert verify("payroll", None, 5).matched, "the Python matches what the mainframe wrote"
        # the mainframe disagrees with GnuCOBOL on one amount: the Python (which matches GnuCOBOL) is now restless, and the set says why
        lines = mainframe_out.split(b"\n")
        lines[0] = lines[0][:-1] + (b"9" if lines[0][-1:] != b"9" else b"8")
        other = add_golden("payroll", "disagree.dat", {"INPUT.DAT": inp}, {"OUTPUT.DAT": b"\n".join(lines)}, root=ROOT)
        try:
            assert other["cobol_agrees"] is False and other["cobol_differences"] >= 1
            assert not verify("payroll", None, 5).matched
        finally:
            remove_uploaded("payroll", other["set"])
        assert verify("payroll", None, 5).matched
        text = add_golden("payroll", "ebcdic.dat", {"INPUT.DAT": ebcdic_in}, {"OUTPUT.DAT": ebcdic_out}, root=ROOT, code_page="cp037")
        remove_uploaded("payroll", text["set"])
    finally:
        remove_uploaded("payroll", made["set"])
    assert made["set"] not in set_names("payroll")


@needs_cobol
def test_parallel_runs_survive_recording_the_cobol_again_and_are_validated():
    from seance.cases import record_sets

    case, _, _ = load_set("payroll", "edges")
    cobol = run_cobol(compile_legacy("payroll"), get_model("payroll"), case)
    made = add_golden("payroll", "keep.dat", {"INPUT.DAT": case.files["INPUT.DAT"]}, {"OUTPUT.DAT": cobol.outputs["OUTPUT.DAT"]}, root=ROOT)
    try:
        record_sets("payroll")
        assert made["set"] in set_names("payroll"), "recording again must not replace the mainframe's answer with GnuCOBOL's"
        with pytest.raises(ValueError, match="at least one output"):
            add_golden("payroll", "x.dat", {}, {}, root=ROOT)
        with pytest.raises(ValueError, match="not an output file"):
            add_golden("payroll", "x.dat", {}, {"INPUT.DAT": b"x"}, root=ROOT)
        with pytest.raises(ValueError, match="not an input file"):
            add_golden("payroll", "x.dat", {"OUTPUT.DAT": b"x"}, {"OUTPUT.DAT": b"y"}, root=ROOT)
    finally:
        remove_uploaded("payroll", made["set"])


@needs_cobol
def test_parallel_run_through_the_api():
    import base64

    case, _, _ = load_set("payroll", "edges")
    out = run_cobol(compile_legacy("payroll"), get_model("payroll"), case).outputs["OUTPUT.DAT"]
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    r = client.post("/api/golden/payroll", headers=H, json={"filename": "api.dat", "inputs": [{"file": "INPUT.DAT", "base64": b64(case.files["INPUT.DAT"])}], "outputs": [{"file": "OUTPUT.DAT", "base64": b64(out)}]})
    assert r.status_code == 200, r.text
    try:
        assert r.json()["cobol_agrees"] is True
        assert any(s["golden"] for s in client.get("/api/data?program=payroll").json()["sets"])
    finally:
        assert client.delete(f"/api/data/payroll/{r.json()['set']}", headers=H).status_code == 200
    assert client.post("/api/golden/payroll", headers=H, json={"filename": "x", "outputs": [{"file": "OUTPUT.DAT", "base64": "###"}]}).status_code == 400
    assert client.post("/api/golden/payroll", json={}).status_code == 403
    assert json.dumps(client.get("/api/data?program=nightly_batch").json())  # jobs still list their sets
