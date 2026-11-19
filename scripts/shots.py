"""Screenshots of the running app for design review.  python scripts/shots.py  -> build/shots/*.png"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "build" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"
DONE = ".summary .word.good, .summary .word.bad"


def main() -> None:
    for old in OUT.glob("*.png"):
        old.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL)
        page.wait_for_selector("#plist tr.link")
        page.screenshot(path=OUT / "1-workspace.png", full_page=True)
        page.click("#openAdd")
        page.click("#loadTpl")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "2-add.png")
        page.keyboard.press("Escape")
        page.goto(URL + "/#/customer_master/overview")
        page.wait_for_selector("#panel-overview .panel")
        page.screenshot(path=OUT / "3-overview.png", full_page=True)
        page.goto(URL + "/#/customer_master/check")
        page.wait_for_selector("#result .summary", timeout=60000)
        page.screenshot(path=OUT / "4-check.png", full_page=True)
        page.goto(URL + "/#/customer_master/code")
        page.wait_for_selector("#pyPane .ln")
        page.locator("#pyPane .ln[data-cobol]").nth(30).click()
        page.screenshot(path=OUT / "5-code.png")
        page.goto(URL + "/#/")
        page.click("#homeDemo")
        page.wait_for_selector(DONE, timeout=300000)
        page.screenshot(path=OUT / "6-fail.png", full_page=True)
        page.goto(URL + "/#/order_pricing/try")
        page.wait_for_selector("#tryInputs textarea")
        page.click("#runTry")
        page.wait_for_selector("#tryResult .note", timeout=120000)
        page.screenshot(path=OUT / "7-try.png", full_page=True)
        page.goto(URL + "/#/account_report/data")
        page.wait_for_selector("#sets table")
        page.screenshot(path=OUT / "8-data.png", full_page=True)
        page.set_viewport_size({"width": 420, "height": 900})
        page.goto(URL + "/#/")
        page.wait_for_selector("#plist tr.link")
        page.screenshot(path=OUT / "9-narrow.png", full_page=True)
        browser.close()
        print("errors:", errors or "none")


if __name__ == "__main__":
    main()
