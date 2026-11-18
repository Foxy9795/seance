"""Take screenshots of the running app with the installed Edge. Used for design review.

    python scripts/shots.py            # writes build/shots/*.png
"""

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
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)

        page.goto(URL)
        page.wait_for_selector(".stone")
        page.screenshot(path=OUT / "1-home.png")

        page.click("#hideIntro")
        page.click(".stone[data-name=payroll]")
        page.wait_for_selector("#implSeg")
        page.screenshot(path=OUT / "2-program.png")

        # fail case: naive draft
        page.click("#implSeg label:has-text('Naive')")
        page.fill("#examples", "10")
        page.click("#go")
        page.wait_for_selector(".verdict", timeout=300000)
        page.screenshot(path=OUT / "3-fail.png", full_page=True)

        # pass case
        page.click("#implSeg label:has-text('Correct Python')")
        page.click("#go")
        page.wait_for_selector(".verdict.ok", timeout=300000)
        page.screenshot(path=OUT / "4-pass.png", full_page=True)

        page.click("#t-try")
        page.click("#tryit")
        page.wait_for_selector("#tryout table", timeout=60000)
        page.screenshot(path=OUT / "5-try.png", full_page=True)

        page.click("#t-code")
        page.screenshot(path=OUT / "6-code.png", full_page=True)

        page.click("#t-spec")
        page.screenshot(path=OUT / "7-spec.png")

        page.click("#t-add")
        page.click("#loadTpl")
        page.screenshot(path=OUT / "8-add.png", full_page=True)

        page.set_viewport_size({"width": 420, "height": 900})
        page.screenshot(path=OUT / "9-narrow.png", full_page=True)
        browser.close()
        print("errors:", errors or "none")


if __name__ == "__main__":
    main()


