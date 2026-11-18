"""Screenshots of the running app for design review.  python scripts/shots.py  -> build/shots/*.png"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "build" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(URL)
        page.wait_for_selector(".pcard")
        page.screenshot(path=OUT / "1-home.png")
        page.click("#openAdd")
        page.click("#loadTpl")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "2-add.png")
        page.keyboard.press("Escape")
        page.click(".pcard[data-p=account_report]")
        page.wait_for_selector("#panel-overview .step")
        page.screenshot(path=OUT / "3-overview.png", full_page=True)
        page.click("#tab-code")
        page.wait_for_selector("#pyPane .ln")
        page.locator("#pyPane .ln[data-cobol]").nth(20).click()
        page.screenshot(path=OUT / "4-code.png")
        page.click("#tab-prove")
        page.fill("#rounds", "8")
        page.click("#runCheck")
        page.wait_for_selector(".verdict.good", timeout=300000)
        page.screenshot(path=OUT / "5-pass.png", full_page=True)
        page.click("#tab-try")
        page.wait_for_selector("#trySet option[value=edges]", state="attached")
        page.select_option("#trySet", "edges")
        page.click("#runTry")
        page.wait_for_selector("#tryResult .note", timeout=120000)
        page.screenshot(path=OUT / "6-try.png", full_page=True)
        page.click("#goHome")
        page.click("#homeDemo")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        page.screenshot(path=OUT / "7-fail.png", full_page=True)
        page.click("#runStrength")
        page.wait_for_timeout(500)
        page.click(".seg button:has-text('Séance Python')")
        page.click("#runStrength")
        page.wait_for_selector("#strength table", timeout=300000)
        page.screenshot(path=OUT / "8-strength.png", full_page=True)
        page.click(".pcard[data-p=add_amounts]")
        page.click("#tab-try")
        page.wait_for_selector("#tryInputs [data-console]")
        page.click("#runTry")
        page.wait_for_selector("#tryResult .note", timeout=120000)
        page.screenshot(path=OUT / "9-console.png", full_page=True)
        page.set_viewport_size({"width": 420, "height": 900})
        page.click("#tab-overview")
        page.screenshot(path=OUT / "10-narrow.png", full_page=True)
        browser.close()
        print("errors:", errors or "none")


if __name__ == "__main__":
    main()
