"""End-to-end UI checks in Edge against a running server.  python scripts/ui_check.py  (server on 127.0.0.1:8000)"""

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000"
NAME = "zz_ui_check"
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
        page.wait_for_selector(".pcard")
        check("home explains the product", "Prove Nothing Changed" in page.inner_text("#home"))
        check("every example is listed", page.locator("#examples .pcard").count() >= 8, page.locator("#examples .pcard").count())
        check("runtime status is shown", "GnuCOBOL" in page.inner_text("#runtime"))

        page.click("#homeDemo")
        page.wait_for_selector(".verdict.good, .verdict.bad", timeout=300000)
        check("the demo catches the naive draft", page.locator(".verdict.bad").count() == 1)
        check("the demo shows a shrunk case", "Smallest Input" in page.inner_text("#result"))
        check("field differences are named", page.locator("#result .fields td.bad").count() > 0)

        page.click(".seg button:has-text('Séance Python')")
        page.click("#runCheck")
        page.wait_for_selector(".verdict.good", timeout=300000)
        check("the reference Python matches", True)
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

        # add a program through the dialog
        page.click("#openAdd")
        page.click("#loadTpl")
        page.wait_for_function("document.getElementById('addCobol').value.length > 100")
        page.fill("#addName", NAME)
        page.click("#addGo")
        page.wait_for_selector(f".pcard[data-p={NAME}]", timeout=300000)
        check("an added program appears under Your Programs", not page.locator("#yoursHead").is_hidden())
        page.click("#tab-code")
        page.wait_for_selector("#pyEdit")
        check("your Python is editable", page.locator("#savePy").count() == 1)
        page.click("#tab-prove")
        page.fill("#rounds", "5")
        page.click("#runCheck")
        page.wait_for_selector(".verdict.good, .verdict.bad", timeout=300000)
        check("the translated draft matches", page.locator(".verdict.good").count() == 1)
        page.click("#tab-overview")
        page.wait_for_selector("#delProg")
        page.click("#delProg")
        page.wait_for_selector("#home:not([hidden])")
        check("deleting removes the program", page.locator(f".pcard[data-p={NAME}]").count() == 0)

        page.set_viewport_size({"width": 420, "height": 900})
        page.goto(URL + "/#/payroll/overview")
        page.wait_for_selector("#panel-overview .step")
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
