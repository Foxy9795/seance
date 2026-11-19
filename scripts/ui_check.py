"""End-to-end UI checks in Edge against a running server.  python scripts/ui_check.py  (server on 127.0.0.1:8000)"""

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000"
NAME = "zz_ui_check"
DONE = ".summary .word.good, .summary .word.bad"
results: list[tuple[bool, str, str]] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    results.append((bool(ok), label, str(detail)[:160]))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(URL)
        page.wait_for_selector("#plist tr.link")
        check("the workspace explains the product", "Workspace" in page.inner_text("#home"))
        check("every example is listed", page.locator("#plist tr.link").count() >= 12, page.locator("#plist tr.link").count())
        check("runtime status is shown", "GnuCOBOL" in page.inner_text("#runtime"))
        page.fill("#search", "customer")
        check("the list filters by name", page.locator("#plist tr.link").count() == 1)
        page.fill("#search", "")

        page.click("#homeDemo")
        page.wait_for_selector(DONE, timeout=300000)
        check("the demo catches the buggy port", page.locator(".summary .word.bad").count() == 1)
        check("the demo shows a shrunk case", "Smallest Failing Input" in page.inner_text("#result"))
        check("field differences are named", page.locator("#result .fields td.bad").count() > 0)

        page.select_option("#implSel", index=0)
        page.wait_for_timeout(300)
        page.click("#runCheck")
        page.wait_for_selector(".summary .word.good", timeout=300000)
        check("the translation matches", True)
        check("coverage is reported", page.locator("#result .bar-meter").count() == 1)
        page.click("#runStrength")
        page.wait_for_selector("#strength table", timeout=300000)
        check("test strength lists planted bugs", page.locator("#strength tr").count() > 2)

        page.click("#tab-code")
        page.wait_for_selector("#pyPane .ln[data-cobol]")
        page.locator("#pyPane .ln[data-cobol]").nth(3).click()
        check("clicking Python highlights its COBOL line", page.locator("#cobolPane .ln.hl").count() == 1)

        page.click("#tab-try")
        page.wait_for_selector("#tryInputs textarea")
        page.click("#runTry")
        page.wait_for_selector("#tryResult .note", timeout=120000)
        check("try shows both outputs", page.locator("#tryResult .out").count() >= 2)

        page.click("#tab-data")
        page.wait_for_selector("#sets table")
        check("test data lists the saved sets", page.locator("#sets tbody tr").count() >= 2)

        page.goto(URL + "/#/order_pricing/code")
        page.wait_for_function("document.querySelectorAll('#cobolFile option').length === 3", timeout=30000)
        check("called programs can be viewed", page.locator("#cobolFile option").count() == 3)

        page.click("#openAdd")
        page.click("#loadTpl")
        page.wait_for_function("document.getElementById('addCobol').value.length > 100")
        page.fill("#addName", NAME)
        page.click("#addGo")
        page.wait_for_url(f"**/#/{NAME}/overview", timeout=300000)
        page.click("#tab-code")
        page.wait_for_selector("#pyEdit")
        check("your Python is editable", page.locator("#savePy").count() == 1)
        page.click("#tab-check")
        page.fill("#rounds", "5")
        page.click("#runCheck")
        page.wait_for_selector(DONE, timeout=300000)
        check("the translated draft matches", page.locator(".summary .word.good").count() == 1)
        page.click("#tab-overview")
        page.wait_for_selector("#delProg")
        page.click("#delProg")
        page.wait_for_selector("#home:not([hidden])")
        page.wait_for_timeout(300)
        check("deleting removes the program", page.locator(f"#plist tr[data-p={NAME}]").count() == 0)

        page.set_viewport_size({"width": 420, "height": 900})
        page.goto(URL + "/#/payroll/overview")
        page.wait_for_selector("#panel-overview .panel")
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check("no sideways scrolling on a phone", overflow <= 1, overflow)
        check("no script errors", not errors, errors)
        browser.close()
    for ok, label, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok or not detail else f"  ({detail})"))
    failed = sum(not ok for ok, _, _ in results)
    print(f"{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
