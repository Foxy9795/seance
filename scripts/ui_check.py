"""Drive the real UI in Edge and assert the behaviors that matter. Needs the app running on :8000.

    python scripts/ui_check.py       # prints PASS/FAIL lines, writes build/shots/flow-*.png
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "build" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"
NAME = "ui_flow_test"
GOOD = '''from generated.ui_flow_test_records import InRecord, OutRecord
from seance.cobol_num import store


def transform(rec: InRecord) -> OutRecord:
    discount = store(rec.amount * rec.pct / 100, 7, 2, signed=True, rounded=True)
    total = store(rec.amount - discount, 8, 2, signed=True)
    return OutRecord(order_id=rec.order_id, discount=discount, total=total, shown=total)
'''
failures = []


def check(label, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  [{extra}]" if extra and not ok else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("dialog", lambda d: d.accept())

        page.goto(URL)
        page.wait_for_selector(".stone")
        check("sidebar lists the four built-in programs", page.locator(".stone").count() >= 4)
        check("intro explains the product", "same inputs" in page.inner_text("#intro"))

        # --- the first-screen demo button runs the naive payroll draft and shows it failing
        page.click("#demo")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        check("demo button shows a failing check", "payroll" in page.inner_text("#pName"))
        check("demo marks payroll as differing in the sidebar", "differs" in page.inner_text(".stone[data-name=payroll]"))
        check("shipped example code is read-only in the editor", page.is_disabled("#saveRun"))

        # --- add a program through the UI
        page.click("#goAdd")
        page.click("#loadTpl")
        page.fill("#newName", NAME)
        page.click("#addProg")
        page.wait_for_selector(f".stone[aria-current=page]:has-text('{NAME}')", timeout=120000)
        page.click("#t-try")
        layout_text = page.inner_text("#layout")
        check("template is read as fixed-format source", "fixed-format source" in layout_text, layout_text[:120])
        check("template uses the DD file name ORDERIN as fixed-length records", "ORDERIN" in layout_text and "fixed-length records" in layout_text, layout_text[:120])
        check("group-free layout lists FILLER and the signed amount", "FILLER" in layout_text and "sign in last digit" in layout_text, layout_text[:200])
        page.click("#t-verify")
        check("added program is selected and marked as yours", "yours" in page.inner_text(f".stone[data-name={NAME}]"))
        page.screenshot(path=OUT / "flow-1-added.png", full_page=True)

        # --- the unwritten stub must fail
        page.click("#t-verify")
        check("empty-starter notice is shown", page.is_visible("#stubNote"))
        page.fill("#examples", "5")
        page.click("#go")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        check("unwritten migration fails", True)
        check("failure shows a field table with crash text", "NotImplementedError" in page.inner_text("#result"))
        page.screenshot(path=OUT / "flow-2-stub-fails.png", full_page=True)

        # --- edit WITHOUT saving, then run: the edited code must be what is tested
        page.click("#t-code")
        page.fill("#migrated", GOOD)
        page.click("#t-verify")
        check("editing clears the old result", not page.is_visible(".verdict"))
        page.click("#go")
        page.wait_for_selector(".verdict.ok", timeout=300000)
        check("unsaved edit is saved and tested (stale pass impossible)", "Spirit matched" in page.inner_text(".verdict"))
        check("pass lists what is not covered", "Not covered" in page.inner_text("#result"))
        check("sidebar candle state updated", "matched" in page.inner_text(f".stone[data-name={NAME}]"))
        page.screenshot(path=OUT / "flow-3-pass.png", full_page=True)

        # --- break it again, confirm a diff with highlighted characters
        page.click("#t-code")
        page.fill("#migrated", GOOD.replace("rounded=True", "rounded=False"))
        page.click("#saveRun")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        check("subtle rounding bug is caught", page.locator("mark").count() > 0)
        page.screenshot(path=OUT / "flow-4-diff.png", full_page=True)

        # --- "Try this record" jumps from a failing case to the side-by-side view
        check("failing case offers Try this record", page.locator("[data-try]").count() > 0)
        page.locator("[data-try]").first.click()
        page.wait_for_selector("#tryout .case", timeout=60000)
        check("Try this record opens the side-by-side view", page.get_attribute("#t-try", "aria-selected") == "true")

        # --- try one record
        page.click("#t-try")
        page.fill("#lines", "ORD001001000000050")
        page.click("#tryit")
        page.wait_for_selector("#tryout .case", timeout=60000)
        check("try-one-record shows a field table", page.locator("#tryout tr").count() > 3)

        # --- keyboard: tabs use arrow keys and roving tabindex
        page.focus("#t-try")
        page.keyboard.press("ArrowRight")
        check("arrow key moves to the next tab", page.get_attribute("#t-code", "aria-selected") == "true")
        check("only the selected tab is in the tab order", page.get_attribute("#t-verify", "tabindex") == "-1")

        # --- delete
        page.click(f".stone[data-name={NAME}]")
        page.click("#del")
        page.wait_for_function(f"!document.querySelector('.stone[data-name={NAME}]')", timeout=30000)
        check("delete removes the program", True)

        check("no console or page errors", not errors, "; ".join(errors)[:300])
        browser.close()
    print("\nFAILED: " + ", ".join(failures) if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())




