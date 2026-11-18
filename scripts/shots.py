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
        page.goto(URL)
        page.wait_for_selector(".stone")
        page.screenshot(path=OUT / "1-home.png")
        page.click("#goAdd")
        page.click("#loadTpl")
        page.screenshot(path=OUT / "2-add.png", full_page=True)
        page.click(".stone[data-name=accounts]")
        page.wait_for_selector("#flow button")
        page.click("#t-check")
        page.screenshot(path=OUT / "3-program.png")
        page.fill("#examples", "8")
        page.click("#go")
        page.wait_for_selector(".verdict", timeout=300000)
        page.screenshot(path=OUT / "4-pass.png", full_page=True)
        page.click("#t-strength")
        page.click("#mutateBtn")
        page.wait_for_selector("#strength .meter", timeout=300000)
        page.screenshot(path=OUT / "5-strength.png", full_page=True)
        page.click("#t-code")
        page.screenshot(path=OUT / "6-code.png")
        page.click(".stone[data-name=payroll]")
        page.wait_for_selector("#implSeg input")
        page.click("#implSeg label:has-text('Naive')")
        page.click("#t-check")
        page.fill("#examples", "8")
        page.click("#go")
        page.wait_for_selector(".verdict.bad", timeout=300000)
        page.screenshot(path=OUT / "7-fail.png", full_page=True)
        page.click("#t-data")
        page.wait_for_selector("#sets table")
        page.screenshot(path=OUT / "8-data.png")
        page.click("#t-export")
        page.screenshot(path=OUT / "9-export.png")
        page.set_viewport_size({"width": 420, "height": 900})
        page.click("#t-check")
        page.screenshot(path=OUT / "10-narrow.png", full_page=True)
        browser.close()
        print("errors:", errors or "none")


if __name__ == "__main__":
    main()

