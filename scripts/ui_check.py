"""End-to-end checks of the page in Edge, on a throwaway copy of the project (its own empty workspace, port 8100).
    python scripts/ui_check.py
It never touches your workspace. Needs playwright (pip install playwright) and Microsoft Edge."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path(__file__).resolve().parent.parent


def program(name: str) -> bytes:
    """A small program that counts the records of a 10-byte record file (Windows line ends, on purpose)."""
    lines = ["       IDENTIFICATION DIVISION.", f"       PROGRAM-ID. {name}.", "       ENVIRONMENT DIVISION.", "       INPUT-OUTPUT SECTION.",
             "       FILE-CONTROL.", "           SELECT IN-FILE ASSIGN TO INFILE.", "       DATA DIVISION.", "       FILE SECTION.", "       FD IN-FILE.",
             "       01 REC PIC X(10).", "       WORKING-STORAGE SECTION.", "       01 N PIC 9(7) VALUE 0.", '       01 EOF PIC X VALUE "N".',
             "       PROCEDURE DIVISION.", "           OPEN INPUT IN-FILE.", '           PERFORM UNTIL EOF = "Y"',
             '               READ IN-FILE AT END MOVE "Y" TO EOF', "                   NOT AT END ADD 1 TO N", "               END-READ",
             "           END-PERFORM.", '           DISPLAY "RECORDS " N.', "           CLOSE IN-FILE.", "           STOP RUN."]
    return ("\r\n".join(lines) + "\r\n").encode()
T = Path(tempfile.mkdtemp(prefix="seance_ui_"))
for d in ("seance", "web"):
    shutil.copytree(SRC / d, T / d, ignore=shutil.ignore_patterns("__pycache__"))
for d in ("legacy", "migrated", "fixtures"):
    (T / d).mkdir()
(T / "migrated" / "__init__.py").write_text("")
(T / "samples").mkdir()
shutil.copy(SRC / "samples" / "catalog.json", T / "samples" / "catalog.json")
for f in ("pyproject.toml",):
    if (SRC / f).exists():
        shutil.copy(SRC / f, T / f)
env = dict(os.environ, PYTHONPATH=str(T))
srv = subprocess.Popen([sys.executable, "-m", "seance", "serve", "--no-browser", "--port", "8100"], cwd=T, env=env,
                       stdout=subprocess.DEVNULL, stderr=open(T / "server.log", "w"))
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def api(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8100" + path, timeout=30))


try:
    for _ in range(60):
        try:
            api("/api/about")
            break
        except Exception:
            time.sleep(0.5)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        page = b.new_context(viewport={"width": 1360, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto("http://127.0.0.1:8100")
        page.wait_for_selector("#addBtn")
        time.sleep(1)
        body = page.inner_text("body")
        adds = page.locator("button:visible", has_text="Add Program").count()
        check("one visible Add Program button", adds == 1, f"found {adds}")
        check("no word 'sample' on the home page", "sample" not in body.lower(), [w for w in body.split("\n") if "sample" in w.lower()][:2])
        check("empty workspace shows the import box with accepted types", "Drop your COBOL files here" in body and ".cbl" in body and ".cpy" in body)
        check("empty workspace shows the 5-step wizard", all(w in body for w in ("Import", "Analyze", "Translate", "Verify", "Export")))
        check("no wall of locked features, and no tutorial button on the empty page", "Requires a COBOL program" not in body and "What you can do" not in body and "Open the tutorial" not in body)
        check("no documentation wall on the home page", "Supported COBOL" not in body and "What it runs" not in body and "mcpServers" not in body)
        page.hover("#infoBtn")
        time.sleep(0.4)
        check("the info button is there, labelled, and explains the product on hover", page.locator("#infoBtn").is_visible() and "What is Séance?" in page.inner_text("#infoBtn") and page.locator("#infoTip").is_visible() and "What Séance does" in page.inner_text("#infoTip"))
        page.mouse.move(600, 600)

        def drop(files):
            payload = [{"name": n, "b64": __import__("base64").b64encode(d).decode()} for n, d in files]
            page.evaluate("""async (items) => { const dt = new DataTransfer();
                for (const it of items) { const bin = Uint8Array.from(atob(it.b64), c => c.charCodeAt(0)); dt.items.add(new File([bin], it.name)); }
                window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""", payload)

        # a data file dropped on the home page: refused, said in words, no empty dialog
        drop([("ACCTREC.dat", bytes((i * 7) % 256 for i in range(5000)))])
        time.sleep(1.2)
        check("binary file on the home page is refused with a message", "binary" in page.inner_text("#toasts").lower(), page.inner_text("#toasts")[:90])
        check("no empty Add dialog is left open", not page.locator("#addDlg[open]").count())
        drop([("customers.txt", b"JOHN SMITH   0001  100.00\n" * 40)])
        time.sleep(1.2)
        check("a .txt data file is refused, not added as a copybook", "does not look like COBOL" in page.inner_text("#toasts"), page.inner_text("#toasts")[-120:])

        # three programs dropped at once
        files = [(f"{n}.cbl", program(n)) for n in ("ALPHA1", "BETA2", "GAMMA3")]
        drop(files)
        t0 = time.time()
        while time.time() - t0 < 600 and len(api("/api/programs")["programs"]) < 3:
            time.sleep(2)
        print(f"  (three programs took {time.time() - t0:.0f} s; page says: {page.inner_text('#toasts')[:200]!r})", flush=True)
        names = sorted(x["name"] for x in api("/api/programs")["programs"])
        check("three programs dropped together are all added", names == ["alpha1", "beta2", "gamma3"], names)
        page.wait_for_function("document.body.innerText.includes('ALPHA1')", timeout=30000)  # the page lists them a moment after the server has them
        body = page.inner_text("body")
        check("every program says what it does", all(x.get("purpose") for x in api("/api/programs")["programs"]))
        check("workspace titles use the PROGRAM-ID (ALPHA1)", "ALPHA1" in body, body[:0])

        check("dashboard shows health, funnel and wizard", all(w.lower() in body.lower() for w in ("Workspace health", "Translated", "Verified", "Copybooks")))
        check("import statistics are shown at once", all(w in body.lower() for w in ("import complete", "copybooks", "jcl jobs", "sql blocks", "call relationships")))
        # a program that needs a copybook that is not there: it says so, and Locate finishes the job
        miss = b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MISS1.\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       COPY CUSTOMER.\n       PROCEDURE DIVISION.\n           DISPLAY \"X\".\n           STOP RUN.\n"
        drop([("MISS1.cbl", miss)])
        page.wait_for_selector("text=Missing copybook CUSTOMER", timeout=60000)
        check("a missing copybook is reported with a Locate button", page.locator("label:has-text('Locate CUSTOMER')").count() == 1)
        cpy = T / "CUSTOMER.cpy"
        cpy.write_text("       01 CUST.\n          05 CUST-NAME PIC X(10).\n")
        page.set_input_files("#loc0", str(cpy))
        t0 = time.time()
        while time.time() - t0 < 120 and "miss1" not in [x["name"] for x in api("/api/programs")["programs"]]:
            time.sleep(2)
        check("Locate adds the program with its copybook", "miss1" in [x["name"] for x in api("/api/programs")["programs"]])
        page.goto("http://127.0.0.1:8100/#/docs")
        page.wait_for_function("document.body.innerText.includes('What you can do')", timeout=15000)
        body = page.inner_text("body")
        check("documentation page holds the words and the feature list", "Spirit matched" in body and "What you can do" in body)
        page.goto("http://127.0.0.1:8100/#/agent")
        page.wait_for_function("document.body.innerText.includes('mcpServers')", timeout=20000)
        check("AI Agent page holds the MCP settings", "mcpServers" in page.inner_text("body") or "mcp" in page.inner_text("body").lower())
        page.goto("http://127.0.0.1:8100/#/activity")
        time.sleep(1)
        check("activity log lists what happened", "Added" in page.inner_text("body") or "missing" in page.inner_text("body").lower())
        # a program's page
        page.goto("http://127.0.0.1:8100/#/p/alpha1/data")
        page.wait_for_selector("#uploadFile", state="attached", timeout=20000)
        (T / "one.dat").write_bytes(b"0123456789" * 50000)
        (T / "two.dat").write_bytes(b"ABCDEFGHIJ" * 20)
        up = [str(T / "one.dat"), str(T / "two.dat")]
        page.set_input_files("#uploadFile", up)
        t0 = time.time()
        sets = []
        while time.time() - t0 < 120:
            sets = [s for s in api("/api/programs/alpha1")["sets"] if s.get("label", s.get("name", "")).startswith("Your Data")]
            if len(sets) >= 2:
                break
            time.sleep(1.5)
        check("two data files chosen together are both uploaded", len(sets) >= 2, [s.get("label") for s in sets])

        # the Check tab keeps advanced panels folded
        page.goto("http://127.0.0.1:8100/#/p/alpha1/check")
        page.wait_for_selector("#strengthPanel", timeout=20000)
        time.sleep(0.5)
        hidden_before = page.evaluate("() => !('advStrength' in document.body.dataset)")
        page.click("#strengthPanel > .head")
        time.sleep(0.3)
        check("Mutation testing starts folded and opens on a click", hidden_before and page.evaluate("() => 'advStrength' in document.body.dataset"))

        # delete one
        page.goto("http://127.0.0.1:8100/#/")
        time.sleep(1)
        page.evaluate("() => { prefs.confirmDelete = false; return deleteProgram('beta2'); }")
        time.sleep(1.5)
        names = sorted(x["name"] for x in api("/api/programs")["programs"])
        check("delete removes the program", names == ["alpha1", "gamma3", "miss1"], names)
        check("the page no longer lists the deleted program", "BETA2" not in page.inner_text("#sideList"))
        page.goto("http://127.0.0.1:8100/#/assessment")
        time.sleep(1.5)
        check("assessment explains an empty dependency graph", "nothing to draw" in page.inner_text("body"))
        check("a step that failed shows a cross, not a check", page.evaluate("() => { const h = wizardHtml([{ name: 'x', title: 'X', error: 'boom', implementations: [] }]); return h.includes('✕'); }"))
        page.hover("#sideList .side-row")
        page.click("#sideList .side-more")
        page.wait_for_function("document.body.innerText.includes('Show the Code')", timeout=5000)
        menu = page.inner_text("body")
        check("each program in the list has a three-dot menu with more options", all(w in menu for w in ("Run check", "Show the Code", "Add test data", "Export Python file", "Delete")))
        page.keyboard.press("Escape")
        # settings is a page of its own, with the tutorial under Help; the tutorial walks five steps and is remembered
        page.goto("http://127.0.0.1:8100/#/")
        time.sleep(0.8)
        page.click("#setBtn")
        page.wait_for_selector("#helpGroup", timeout=10000)
        check("settings opens as a page with a Help section", page.url.endswith("#/settings") and not page.locator("#setDlg[open]").count() and "Start The Tutorial" in page.inner_text("#helpGroup"))
        page.click("#setTour")
        page.wait_for_selector("#tutDlg[open]", timeout=5000)
        steps = 1
        while page.locator("#tutNext").inner_text() != "Done" and steps < 10:
            page.click("#tutNext")
            steps += 1
        page.click("#tutNext")
        time.sleep(0.4)
        check("the tutorial has five steps and closes on Done", steps == 5 and not page.locator("#tutDlg[open]").count() and page.evaluate("() => prefs.tutorialSeen === true"))
        # search finds help and features while the workspace is full or empty
        page.keyboard.press("Control+k")
        page.wait_for_selector("#palDlg[open]", timeout=5000)
        page.fill("#palInput", "tutorial")
        time.sleep(0.4)
        check("search finds the tutorial", "Tutorial" in page.inner_text("#palList"))
        page.fill("#palInput", "business rules")
        time.sleep(0.4)
        check("search finds a feature by name", "Business rules" in page.inner_text("#palList"))
        page.keyboard.press("Escape")
        errs = [e for e in errors if "favicon" not in e and "400 (Bad Request)" not in e]  # the 400s are the missing-copybook tests
        check("no errors in the browser console", not errs, errs[:3])
        b.close()
finally:
    srv.terminate()
    time.sleep(1)
    shutil.rmtree(T, ignore_errors=True)
bad = [r for r in results if not r[1]]
print(f"\n{len(results) - len(bad)} of {len(results)} passed")
sys.exit(1 if bad else 0)
