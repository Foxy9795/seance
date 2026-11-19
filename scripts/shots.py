"""Screenshots of the running app for design review.  python scripts/shots.py [--no-check]  -> build/shots/*.png

Loads every sample (they are removed again at the end), runs Check All, and photographs the main screens.
The app must be running (python -m seance serve).
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def cli(*args: str) -> None:
    subprocess.run([str(PY), "-m", "seance", *args], cwd=ROOT, check=True, capture_output=True)


def main() -> None:
    for old in OUT.glob("s-*.png"):
        old.unlink()
    cli("samples", "load", "nightly_batch")
    for n in ("payroll", "loan", "interest", "inventory", "account_report", "add_amounts", "table_search", "order_pricing", "transaction_sort",
              "seat_bookings", "payment_posting", "customer_inquiry"):
        cli("samples", "load", n)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": 1360, "height": 860})
        ctx.add_init_script("localStorage.setItem('seance.prefs.v1', JSON.stringify({guideSeen: true}))")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(URL)
        page.wait_for_selector(".stats")
        page.screenshot(path=OUT / "s-01-workspace-unchecked.png")
        if "--no-check" not in sys.argv:
            page.click("[data-act=checkAll]")
            page.wait_for_selector("#stopAll", timeout=30000)
            page.screenshot(path=OUT / "s-02-checking.png")
            page.wait_for_selector(".toast:has-text('Checked')", timeout=1_500_000)
            page.wait_for_timeout(500)
        page.screenshot(path=OUT / "s-03-workspace-checked.png", full_page=True)
        page.click("[data-view=cards]")
        page.wait_for_selector(".cards")
        page.screenshot(path=OUT / "s-04-cards.png", full_page=True)
        page.click("[data-view=list]")
        page.goto(URL + "/#/p/customer_inquiry/try")
        page.wait_for_selector("#runTry")
        page.select_option("#trySet", index=1)
        page.click("#runTry")
        page.wait_for_selector("#tryResult .panel", timeout=180000)
        page.wait_for_timeout(400)
        page.screenshot(path=OUT / "s-05-cics-try.png", full_page=True)
        page.goto(URL + "/#/p/payment_posting/try")
        page.wait_for_selector("#runTry")
        page.select_option("#trySet", index=1)
        page.click("#runTry")
        page.wait_for_selector("#tryResult .panel", timeout=180000)
        page.wait_for_timeout(400)
        page.screenshot(path=OUT / "s-06-sql-try.png", full_page=True)
        page.goto(URL + "/#/p/nightly_batch/overview")
        page.wait_for_selector(".steps")
        page.screenshot(path=OUT / "s-07-job-overview.png", full_page=True)
        page.goto(URL + "/#/p/nightly_batch/check")
        page.wait_for_selector("#result .sumhead")
        page.screenshot(path=OUT / "s-08-job-check.png", full_page=True)
        page.goto(URL + "/#/p/customer_master/code")
        page.wait_for_selector("#pyPane .ln")
        page.locator("#pyPane .ln[data-cobol]").nth(30).click()
        page.screenshot(path=OUT / "s-09-code.png")
        page.goto(URL + "/#/p/customer_master/test-data".replace("test-data", "data"))
        page.wait_for_selector("#recordAgain")
        page.screenshot(path=OUT / "s-10-data.png", full_page=True)
        page.keyboard.press("Control+k")
        page.wait_for_selector("#palDlg[open]")
        page.keyboard.type("pay")
        page.wait_for_timeout(200)
        page.screenshot(path=OUT / "s-11-palette.png")
        page.keyboard.press("Escape")
        page.click("#setBtn")
        page.wait_for_selector("#setDlg[open]")
        page.screenshot(path=OUT / "s-12-settings.png")
        page.keyboard.press("Escape")
        page.keyboard.press("?")
        page.wait_for_selector("#keysDlg[open]")
        page.screenshot(path=OUT / "s-13-keys.png")
        page.keyboard.press("Escape")
        page.click("#runtimeBtn")
        page.click("#runtimeMenu [data-act=about]")
        page.wait_for_selector("#aboutDlg[open]")
        page.screenshot(path=OUT / "s-14-about.png")
        page.keyboard.press("Escape")
        page.click("#addBtn")
        page.wait_for_selector("#addDlg[open]")
        page.screenshot(path=OUT / "s-15-add.png")
        page.keyboard.press("Escape")
        page.goto(URL + "/#/p/payroll/check")
        page.click("#moreBtn")
        page.screenshot(path=OUT / "s-16-more-menu.png")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 400, "height": 820})
        page.goto(URL + "/#/")
        page.wait_for_selector(".stats")
        page.screenshot(path=OUT / "s-17-narrow-workspace.png")
        page.goto(URL + "/#/p/payroll/check")
        page.wait_for_selector("#result .sumhead")
        page.screenshot(path=OUT / "s-18-narrow-check.png")
        page.click("#sideToggle")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "s-19-narrow-drawer.png")
        print("errors:", errors)
        browser.close()
    cli("samples", "remove")


if __name__ == "__main__":
    main()
