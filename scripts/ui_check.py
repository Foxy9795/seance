"""Drive the real UI in Edge and assert the behaviors that matter. Needs the app running on :8000.

    python scripts/ui_check.py       # prints PASS/FAIL lines, writes build/shots/flow-*.png
"""

import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"
NAME = "ui_flow_test"
failures = []


def check(label, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{extra}]" if extra and not ok else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    for f in ("accounts.cbl", "ACCTREC.cpy"):
        shutil.copy(ROOT / "legacy" / "accounts" / f, tmp / f)
    data = tmp / "real_accounts.dat"
    data.write_text("".join(l.ljust(38) for l in (ROOT / "fixtures" / "accounts" / "random.in").read_text(encoding="latin-1").splitlines()[:25]), encoding="latin-1")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1360, "height": 900}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text else None)
        page.on("dialog", lambda d: d.accept())

        page.goto(URL)
        page.wait_for_selector(".stone")
        check("home explains the product", "write the Python for you" in page.inner_text("#v-home"))
        check("home offers the demo, chosen by the backend", page.is_visible("#demo"))
        check("support lists come from the API", page.locator("#supportLists li").count() >= 5)

        # --- demo: the naive draft fails
        page.click("#demo")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        check("demo shows a failing check", page.is_visible("#v-prog"))
        check("sidebar marks the demo program as differing", page.locator(".stone[aria-current=page] small").inner_text().endswith("Differs"))
        check("shipped examples are read-only", page.is_disabled("#saveRun"))
        check("titles are capitalized", page.inner_text("#pName")[:1].isupper() and "Run Check" in page.inner_text("#p-check"))

        # --- add a program with the file picker: a fixed-format program plus its copybook
        page.click("#goAdd")
        page.set_input_files("#filePick", [str(tmp / "accounts.cbl"), str(tmp / "ACCTREC.cpy")])
        page.wait_for_selector("#fileList li >> nth=1")
        roles = page.inner_text("#fileList")
        check("dropped files are sorted into program and copybook", "Program" in roles and "Copybook ACCTREC" in roles, roles)
        page.fill("#newName", NAME)
        page.click("#addProg")
        page.wait_for_selector(f".stone[data-name={NAME}][aria-current=page]", timeout=180000)
        status = page.inner_text("#status")
        check("adding drafts the Python for every statement", "drafted Python for all" in status, status)
        check("program chips show the format and files", "Fixed Format" in page.inner_text("#pChips") and "ACCTIN" in page.inner_text("#pChips"))

        # --- the automatic draft passes the check
        page.fill("#examples", "8")
        page.click("#go")
        page.wait_for_selector(".verdict", timeout=300000)
        check("the automatic draft matches the real COBOL", page.is_visible(".verdict.ok"), page.inner_text(".verdict")[:200])
        check("workflow strip shows the check result", "Check: Matched" in page.inner_text("#flow"))
        page.screenshot(path=OUT / "flow-1-draft-passes.png", full_page=True)

        # --- test strength
        page.click("#t-strength")
        page.click("#mutateBtn")
        page.wait_for_selector("#strength .meter", timeout=300000)
        text = page.inner_text("#strength")
        check("test strength reports caught planted bugs with COBOL lines", "Planted Bugs Caught" in text and "COBOL Line" in text, text[:200])
        check("workflow strip shows test strength", "Caught" in page.inner_text("#flow"))
        page.screenshot(path=OUT / "flow-2-strength.png", full_page=True)

        # --- break the draft in the editor, check it fails with a highlighted field
        page.click("#t-code")
        code = page.input_value("#migrated")
        bad = code.replace('lambda: S.n("WS-BAL") * (D("1") + S.n("WS-MONTH-RATE")), True)', 'lambda: S.n("WS-BAL") * (D("1") + S.n("WS-MONTH-RATE")), False)')
        check("the draft contains the compounding line", bad != code)
        page.fill("#migrated", bad)
        page.click("#saveRun")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        check("a dropped ROUNDED is caught and highlighted", page.locator("#result mark").count() > 0)
        page.screenshot(path=OUT / "flow-3-caught.png", full_page=True)

        page.locator("[data-try]").first.click()
        page.wait_for_selector("#tryout .case", timeout=60000)
        check("Try This Record opens the side-by-side view", page.get_attribute("#t-try", "aria-selected") == "true")

        # --- redraft from COBOL restores a passing version
        page.click("#t-code")
        page.click("#redraft")
        page.wait_for_function("document.querySelector('#status').textContent.includes('Redrafted')", timeout=120000)
        page.click("#t-check")
        page.click("#go")
        page.wait_for_selector(".verdict", timeout=300000)
        check("redraft restores a matching Python", page.is_visible(".verdict.ok"))

        # --- your own test data
        page.click("#t-data")
        page.wait_for_selector("#sets table")
        page.set_input_files("#dataPick", str(data))
        page.wait_for_function("document.querySelector('#status').textContent.includes('Added 25 records')", timeout=120000)
        check("uploaded fixed-length data becomes a test set", "Your data: real_accounts.dat" in page.inner_text("#sets"))

        # --- export
        page.click("#t-export")
        with page.expect_download() as dl:
            page.click("#dlZip")
        path = dl.value.path()
        check("the standalone program downloads", path is not None and Path(path).stat().st_size > 3000)
        page.screenshot(path=OUT / "flow-4-export.png", full_page=True)

        # --- keyboard
        page.focus("#t-check")
        page.keyboard.press("ArrowRight")
        check("arrow keys move between tabs", page.get_attribute("#t-strength", "aria-selected") == "true")
        check("only the selected tab is in the tab order", page.get_attribute("#t-check", "tabindex") == "-1")

        # --- delete
        page.click("#del")
        page.wait_for_function(f"!document.querySelector('.stone[data-name={NAME}]')", timeout=30000)
        check("delete removes the program and returns home", page.is_visible("#v-home"))

        check("no console or page errors", not errors, "; ".join(errors)[:300])
        browser.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print("\nFAILED: " + ", ".join(failures) if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
