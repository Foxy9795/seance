"""Cross-reference, the record viewer, deleting a program completely, and the plain-English description."""
from pathlib import Path

from fastapi.testclient import TestClient

from seance.api import app
from seance.programs import delete_program
from seance.spec import generate_spec
from seance.xref import hits, names

client = TestClient(app, base_url="http://127.0.0.1:8000")
INVOICE = Path(__file__).resolve().parent / "data" / "invoice"


def test_names_that_contain_the_query_are_counted_per_program():
    found = {n["name"]: n for n in names("gross")}
    assert "WS-GROSS" in found and found["WS-GROSS"]["programs"][0]["program"] == "payroll"
    assert all("GROSS" in n for n in found), "only names that contain the query"
    assert names("a") == [] and names("not a word") == []


def test_every_line_that_names_a_field_says_what_it_does_there():
    roles = {(h["line"], h["role"]) for h in hits("WS-GROSS")}
    assert (20, "defined") in roles and (42, "changed") in roles and (51, "used") in roles
    assert [h["role"] for h in hits("PROCESS-PARA") if h["role"] == "paragraph"], "the paragraph header is found"


def test_the_record_viewer_splits_records_into_fields():
    r = client.get("/api/records", params={"program": "payroll", "dataset": "edges", "side": "output"}).json()
    assert r["files"] == ["OUTPUT.DAT"] and r["fields"] == ["OUT-EMP-ID", "OUT-GROSS", "OUT-TAX", "OUT-NET"]
    assert r["total"] == len(r["rows"]) and not r["truncated"]
    csv = client.get("/api/records", params={"program": "payroll", "dataset": "edges", "side": "output", "format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0] == "OUT-EMP-ID,OUT-GROSS,OUT-TAX,OUT-NET"
    assert client.get("/api/records", params={"program": "payroll", "dataset": "nope"}).status_code == 404
    assert client.get("/api/xref", params={"name": "not a name"}).status_code == 400


def test_deleting_a_program_leaves_nothing_behind(tmp_path):
    (tmp_path / "legacy" / "gone").mkdir(parents=True)
    (tmp_path / "legacy" / "gone" / "gone.cbl").write_text("x", encoding="utf-8")
    history = tmp_path / "build" / "reports" / "history" / "migrated_gone.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("{}\n", encoding="utf-8")
    (tmp_path / "build" / "reports" / "migrated_gone.json").write_text("{}", encoding="utf-8")
    delete_program("gone", tmp_path)
    assert not history.exists() and not (tmp_path / "build" / "reports" / "migrated_gone.json").exists()
    assert not (tmp_path / "legacy" / "gone").exists()


def test_the_description_follows_an_evaluate_of_a_field(tmp_path):
    folder = tmp_path / "legacy" / "invoice"
    folder.mkdir(parents=True)
    for f in INVOICE.iterdir():
        (folder / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    text = generate_spec("invoice", tmp_path)
    text = getattr(text, "markdown", None) or str(text)
    assert "Compares IN-CLASS with the cases below" in text and 'When IN-CLASS is "F": copies .050 into WS-RATE.' in text
    assert "When IN-QTY >= 100: copies .150 into WS-DISCOUNT." in text
    assert "not summarized" not in text and "1 characters" not in text
