"""End-to-end UI checks in Edge against a running server.  python scripts/ui_check.py  (python -m seance serve first)

Starts from an empty workspace, so run it on a workspace without programs of your own named payroll or accounts.
It loads samples through the guide, adds and deletes one program of its own, and removes the samples at the end.
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from sample_cobol import TEMPLATE  # noqa: E402

URL = "http://127.0.0.1:8000"
NAME = "zz_ui_check"
results: list[tuple[bool, str, str]] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    results.append((bool(ok), label, str(detail)[:160]))


def cli(*args: str) -> None:
    subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "seance", *args], cwd=ROOT, check=True, capture_output=True)


def main() -> int:
    cli("samples", "remove")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": 1360, "height": 900})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        hit = lambda sel: page.locator(sel).count()  # noqa: E731

        def close_dialogs() -> None:
            page.keyboard.press("Escape")
            page.wait_for_function("!document.querySelector('dialog[open]')")
            page.wait_for_timeout(150)  # focus returns to the page a moment after a dialog closes

        # ---- first run: the guide opens by itself, and the workspace has no examples in it
        page.goto(URL)
        page.wait_for_selector("#guideDlg[open]")
        check("the guide opens on first run", "Prove your COBOL migration" in page.inner_text("#guideBody"))
        check("the guide offers the tour, the samples and adding your own", all(page.locator(s).count() for s in ("#guideTour", "#guideSamples", "#guideAdd")))
        page.click("#guideFoot [data-close]")
        page.wait_for_selector("#vWork .welcome")
        check("the workspace starts empty", "No programs yet" in page.inner_text("#sideList") and hit("#vWork tr.link") == 0)
        page.reload()
        page.wait_for_selector("#vWork .welcome")
        check("the guide does not return once seen", not page.locator("#guideDlg[open]").count())
        check("runtime status is shown", "GnuCOBOL" in page.inner_text("#runtimeBtn"))

        # ---- palette, shortcuts, settings
        page.keyboard.press("Control+k")
        page.wait_for_selector("#palDlg[open]")
        check("the palette lists actions", "Add program" in page.inner_text("#palList"))
        close_dialogs()
        # the command bar grows out of the search button, at any window size, and focus goes back to it
        for w, h in ((1360, 900), (2050, 1000), (700, 800)):
            page.set_viewport_size({"width": w, "height": h})
            page.click("#palOpen")
            page.wait_for_selector("#palDlg[open]")
            page.wait_for_timeout(450)
            box, trig = page.locator("#palDlg").bounding_box(), page.locator("#palOpen").bounding_box()
            check(f"the command bar opens at the search button ({w} wide)", (abs(box["x"] - trig["x"]) <= 10 or (w < 720 and box["x"] <= 10)) and abs(box["y"] - trig["y"]) <= 4 and box["y"] < 60,
                  f"dialog {box['x']:.0f},{box['y']:.0f} button {trig['x']:.0f},{trig['y']:.0f}")
            close_dialogs()
            check(f"focus returns to the search button ({w} wide)", page.evaluate("document.activeElement && document.activeElement.id") == "palOpen")
        page.set_viewport_size({"width": 1360, "height": 900})
        page.keyboard.press("?")
        page.wait_for_selector("#keysDlg[open]")
        check("the shortcut list opens with ?", "Run the check" in page.inner_text("#keysBody"))
        close_dialogs()
        page.click("#setBtn")
        page.wait_for_selector("#setDlg[open]")
        page.select_option("[data-pref=density]", "compact")
        close_dialogs()
        check("a setting applies at once", page.evaluate("document.body.dataset.density") == "compact")
        page.reload()
        page.wait_for_selector("#vWork")
        check("settings persist across reloads", page.evaluate("document.body.dataset.density") == "compact")
        page.click("#setBtn")
        page.wait_for_selector("#setDlg[open]")
        page.click("#setReset")
        close_dialogs()

        # ---- load a sample through the guide (Help menu)
        page.click("#helpBtn")
        page.click("#helpMenu [data-act=samples]")
        page.wait_for_selector("[data-sample=payroll]")
        check("the sample library is grouped", page.locator(".group-title").count() >= 4)
        page.click("[data-sample=payroll]")
        page.wait_for_selector("#vProg:not([hidden]) #pTitle:has-text('Payroll')")
        check("a loaded sample opens as a program", "/p/payroll" in page.url)
        check("the sample is marked", "Sample" in page.inner_text("#pBadges"))
        check("the sidebar lists it", hit(".side-item[data-name=payroll]") == 1)
        check("a sample never starts with a verdict", "Not checked" in page.inner_text("#statusLine"), page.inner_text("#statusLine"))

        # ---- navigation: keys, hash, history
        for key, tab in (("2", "code"), ("3", "analysis"), ("4", "check"), ("5", "try"), ("6", "data"), ("1", "overview")):
            page.keyboard.press(key)
            page.wait_for_function(f"location.hash.endsWith('/{tab}')")
        page.wait_for_selector("#tab-overview[aria-selected=true]")
        check("keys 1 to 6 switch tabs and the address follows", True)
        page.go_back()
        page.wait_for_function("location.hash.endsWith('/data')")
        check("the back button returns to the previous tab", page.locator("#tab-data[aria-selected=true]").count() == 1)

        # ---- run the check on the translation, then on the buggy port
        page.keyboard.press("4")
        page.click("#runBtn")
        page.wait_for_selector("#result .word.good", timeout=300000)
        check("the check matches", True)
        check("the status line follows the check", "Spirit matched" in page.inner_text("#statusLine"))
        check("coverage and receipt are shown", hit("#result .meter") == 1 and hit("#result .receipt") == 1)
        check("the sidebar status changed", "Spirit matched" in page.locator(".side-item[data-name=payroll]").inner_text())
        page.select_option("#implSel", label="Hand-written port (floats)")
        page.wait_for_selector("#result .empty-state")
        page.click("#runBtn")
        page.wait_for_selector("#result .word.bad", timeout=300000)
        check("the buggy port is caught", True)
        check("a shrunk input is shown", "Smallest failing input" in page.inner_text("#result"))
        check("field differences are named", hit("#result .fields td.bad") > 0)
        check("the Check tab counts the differing lines", hit("#tab-check .count") == 1)
        page.select_option("#implSel", label="Your Python")

        # ---- code, edit, try, data
        page.keyboard.press("2")
        page.wait_for_selector("#pyPane .ln[data-cobol]")
        page.locator("#pyPane .ln[data-cobol]").nth(3).click()
        check("clicking Python highlights its COBOL line", hit("#cobolPane .ln.hl") == 1)
        page.click("#editPy")
        page.wait_for_selector("#pyEdit")
        page.click("#cancelEdit")
        check("editing can be cancelled", hit("#pyEdit") == 0 and hit("#pyPane .ln[data-cobol]") > 0)
        page.click("[data-opt=wrap]")
        check("wrap lines toggles", page.evaluate("document.body.classList.contains('wrap')"))
        page.click("[data-opt=wrap]")
        page.keyboard.press("5")
        page.wait_for_selector("#runTry")
        page.click("#runTry")
        page.wait_for_selector("#tryResult .note.good", timeout=120000)
        check("try shows both outputs and they match", hit("#tryResult .out") >= 2)
        page.keyboard.press("6")
        page.wait_for_selector("#pData tbody tr")
        check("test data lists the saved sets", hit("#pData tbody tr") >= 2)
        check("upload accepts EBCDIC", hit("#uploadCode option[value=cp037]") == 1)

        # ---- workspace: filters, sort, views, Check All
        cli("samples", "load", "accounts")
        page.keyboard.press("g")
        page.keyboard.press("w")
        page.wait_for_selector("#vWork .stats")
        page.reload()
        page.wait_for_selector("#vWork tr.link")
        check("g then w opens the workspace", page.url.endswith("#/"))
        check("both programs are listed", hit("#vWork tr.link") == 2)
        page.click("[data-filter=new]")
        check("a result filter narrows the list", hit("#vWork tr.link") == 1 and "Accounts" in page.inner_text("#vWork tbody"))
        page.click("[data-filter=all]")
        page.fill("#wsSearch", "pay")
        check("the search filters by name", hit("#vWork tr.link") == 1)
        page.fill("#wsSearch", "")
        page.click("[data-view=cards]")
        check("cards view works", hit("#vWork .card") == 2)
        page.click("[data-view=list]")
        page.click("[data-act=checkAll]")
        page.wait_for_selector(".toast:has-text('Checked 2 programs')", timeout=600000)
        check("Check All finishes and reports", True)
        check("both programs show a verdict", page.locator("#vWork .status.good").count() == 2)

        # ---- every list is the page's own, not the system's
        page.goto(URL + "/#/")
        page.wait_for_selector("#sortSel")
        page.click("#sortSel")
        check("a dropdown opens the page's own list", hit(".dd .dd-opt") == 4, hit(".dd .dd-opt"))
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_function("!document.querySelector('.dd')")
        check("a dropdown choice applies", page.input_value("#sortSel") == "status", page.input_value("#sortSel"))
        page.click("#setBtn")
        page.wait_for_selector("#setDlg[open]")
        page.wait_for_timeout(350)  # the dialog is still fading in
        page.click("[data-pref=density]")
        page.wait_for_selector("#setDlg .dd .dd-opt", timeout=5000)
        check("a dropdown inside a dialog is usable", hit("#setDlg .dd .dd-opt") == 2, hit(".dd .dd-opt"))
        page.keyboard.press("Escape")
        check("Escape closes the list and leaves the dialog open", page.locator("#setDlg[open]").count() == 1 and hit(".dd") == 0)
        close_dialogs()

        # ---- analysis
        page.goto(URL + "/#/p/payroll/analysis")
        page.wait_for_selector("#pAnalysis .gn", state="attached")
        check("the analysis shows metrics and a flow graph", hit("#pAnalysis .mcard") >= 8 and hit("#pAnalysis .gn") == 2)
        page.click("[data-ana=rules]")
        page.wait_for_selector("#pAnalysis .rule")
        check("business rules are listed in plain words", "IN-HOURS is greater than 40" in page.inner_text("#pAnalysis"))
        with page.expect_download() as dl:
            page.click("#pAnalysis [data-act=rules]")
        check("rules export as a Gherkin file", dl.value.suggested_filename.endswith(".feature"), dl.value.suggested_filename)
        page.click("[data-ana=dict]")
        page.wait_for_selector("#dictQ")
        page.fill("#dictQ", "OUT-")
        check("the data dictionary filters", 3 <= hit("#pAnalysis tbody tr") <= 6, hit("#pAnalysis tbody tr"))
        page.click("[data-ana=lineage]")
        check("lineage names the source fields", "IN-HOURS" in page.inner_text("#pAnalysis") and "WS-TAX" in page.inner_text("#pAnalysis"))
        page.click("[data-ana=deps]")
        check("dependencies list the files", "INPUT.DAT" in page.inner_text("#pAnalysis"))

        # ---- the assessment of the whole workspace
        page.goto(URL + "/#/assessment")
        page.wait_for_selector("#vPort tbody tr")
        check("the assessment lists every program", hit("#vPort tbody tr") == 2)
        page.click("#vPort [data-sort=lines]")
        check("the assessment sorts by a column", page.locator("#vPort [aria-sort]").count() == 1)
        check("the assessment orders the migration in waves", "Wave 1" in page.inner_text("#vPort"))
        with page.expect_download() as dl:
            page.click("#vPort a[href='/api/portfolio.csv']")
        check("the assessment exports as CSV", dl.value.suggested_filename.endswith(".csv"))

        # ---- history and the new exports, after two checks of Payroll
        page.goto(URL + "/#/p/payroll/check")
        page.wait_for_selector("#result")
        page.click("#runBtn")
        page.wait_for_selector("#result .word.good", timeout=300000)
        page.wait_for_selector("#pCheck .hist tbody tr")
        check("each check is kept in the history", hit("#pCheck .hist tbody tr") >= 2, hit("#pCheck .hist tbody tr"))
        page.click("#exportBtn")
        with page.expect_download() as dl:
            page.click("#exportMenu [data-arg=html]")
        check("the check report exports as HTML", dl.value.suggested_filename.endswith(".html"))

        # ---- a parallel run against output from the mainframe
        page.goto(URL + "/#/p/payroll/data")
        page.wait_for_selector("#mfPanel")
        check("Test Data offers a parallel run with mainframe output", "your mainframe" in page.inner_text("#mfPanel"))

        # ---- single and bulk deletion of samples, from the workspace list
        page.goto(URL + "/#/")
        page.wait_for_selector("#vWork tr.link")
        page.click("#vWork tr.link:has-text('Accounts') [data-rowmenu]")
        page.wait_for_selector("#floatMenu")
        check("a row menu offers deleting a sample", "Delete this sample" in page.inner_text("#floatMenu"))
        page.click("#floatMenu [data-act=rowDelete]")
        page.wait_for_selector("#confirmDlg[open]")
        page.click("#cfYes")
        page.wait_for_function("document.querySelectorAll('#vWork tr.link').length === 1")
        check("one sample can be deleted from its row", hit(".side-item[data-name=accounts]") == 0)
        cli("samples", "load", "accounts")
        cli("samples", "load", "loan")
        page.reload()
        page.wait_for_selector("#vWork tr.link:has-text('Loan')")
        page.check("#selAll")
        check("selecting rows shows what can be done with them", "3 selected" in page.inner_text("#vWork .selbar"), page.inner_text("#vWork .selbar")[:40])
        check("the selection bar is compact", page.locator("#vWork .selbar").bounding_box()["width"] < 560, page.locator("#vWork .selbar").bounding_box())
        check("the select boxes are small", page.locator("#selAll").bounding_box()["width"] <= 16)
        # each action is offered in one place: no label appears in two different parts of the page
        page.click("#helpBtn")
        page.wait_for_selector("#helpMenu:not([hidden])")
        twice = page.evaluate("""() => {
            const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest('[hidden]'); };
            const seen = {};
            document.querySelectorAll('button, a[href], [role=menuitem]').forEach((e) => {
                if (!vis(e) || e.matches('.side-item, .tabs button, .chip, [data-sel], .icon-btn[data-rowmenu]')) return;
                const t = (e.getAttribute('aria-label') || e.innerText || '').replace(/\\s+/g, ' ').trim().split(' ').slice(0, 4).join(' ').toLowerCase();
                const where = (e.closest('.side-foot, .top, .menu, #vWork, .pbar') || document.body).className.split(' ')[0] || 'page';
                if (t.length > 2) (seen[t] = seen[t] || new Set()).add(where);
            });
            return Object.entries(seen).filter(([, w]) => w.size > 1).map(([t, w]) => t + ' in ' + [...w].join(' and '));
        }""")
        check("no action is offered in two places", not twice, "; ".join(twice))
        page.keyboard.press("Escape")
        page.click("#vWork [data-act=selDelete]")
        page.wait_for_selector("#confirmDlg[open]")
        page.click("#cfYes")
        page.wait_for_selector("#vWork .welcome")
        check("several programs can be deleted at once", hit(".side-item") == 0)
        cli("samples", "load", "payroll")
        cli("samples", "load", "accounts")
        page.reload()
        page.wait_for_selector("#vWork tr.link")

        # ---- palette navigation and next/previous
        page.keyboard.press("Control+k")
        page.keyboard.type("accounts")
        page.keyboard.press("Enter")
        page.wait_for_function("location.hash.includes('/p/accounts')")
        check("the palette jumps to a program", True)
        page.keyboard.press("]")
        page.wait_for_function("location.hash.includes('/p/payroll')")
        check("] moves to the next program", True)

        # ---- add a program of your own, check it, delete it
        page.click("#addBtn")
        page.wait_for_selector("#addDlg[open]")
        check("the add dialog offers no example program", "example" not in page.inner_text("#addDlg").lower())
        page.fill("#addCobol", TEMPLATE["cobol"])
        check("the name is suggested from PROGRAM-ID", page.input_value("#addName") == "discount", page.input_value("#addName"))
        page.fill("#addName", NAME)
        page.click("#addGo")
        page.wait_for_selector("#pTitle:has-text('Zz Ui Check')", timeout=300000)
        check("an added program opens", NAME in page.url)
        check("it is not marked as a sample", "Sample" not in page.inner_text("#pBadges"))
        page.keyboard.press("r")
        page.wait_for_selector("#result .word.good", timeout=300000)
        check("an added program matches", True)
        page.click("#moreBtn")
        page.click("#moreMenu [data-act=remove]")
        page.wait_for_selector("#confirmDlg[open]")
        page.click("#cfYes")
        page.wait_for_selector("#vWork:not([hidden])")
        check("deleting asks first and returns to the workspace", hit(f".side-item[data-name={NAME}]") == 0)

        # ---- a JCL job: dropped as a file, recorded, checked, deleted
        cli("samples", "load", "customer_master")
        page.reload()
        page.wait_for_selector("#vWork tr.link")
        page.click("#addBtn")
        page.wait_for_selector("#addDlg[open]")
        page.set_input_files("#pickFiles", str(ROOT / "samples" / "nightly_batch" / "legacy" / "nightly_batch.jcl"))
        page.wait_for_function("document.querySelector('#addJobPane') && !document.querySelector('#addJobPane').hidden")
        check("a dropped .jcl file switches to the job form", "//NIGHTLY" in page.input_value("#addJcl").upper() or "JOB" in page.input_value("#addJcl").upper())
        page.fill("#addName", "zz_ui_job")
        page.click("#addGo")
        page.wait_for_selector("#pTitle:has-text('Zz Ui Job')", timeout=300000)
        page.wait_for_selector(".steps tbody tr")
        check("an added job opens with its steps", hit(".steps tbody tr") == 4, hit(".steps tbody tr"))
        check("a job has no Try Input tab", page.locator("#tab-try").is_hidden())
        page.keyboard.press("r")
        page.wait_for_selector("#result .word.good", timeout=300000)
        check("an added job matches", True)
        page.click("#moreBtn")
        page.click("#moreMenu [data-act=remove]")
        page.wait_for_selector("#confirmDlg[open]")
        page.click("#cfYes")
        page.wait_for_selector("#vWork:not([hidden])")
        check("a job can be deleted", hit(".side-item[data-name=zz_ui_job]") == 0)

        # ---- unsaved Python edits survive a trip to another tab
        page.goto(URL + "/#/p/payroll/code")
        page.wait_for_selector("#editPy")
        page.click("#editPy")
        page.fill("#pyEdit", "# my unsaved note\n")
        page.evaluate("document.querySelector('#tab-overview').click()")
        page.wait_for_function("location.hash.endsWith('/overview')")
        page.evaluate("document.querySelector('#tab-code').click()")
        page.wait_for_selector("#pyEdit")
        check("unsaved Python edits are kept across tabs", page.input_value("#pyEdit") == "# my unsaved note\n")
        page.click("#cancelEdit")

        # ---- the tour can be left at any time
        page.click("#helpBtn")
        page.click("#helpMenu [data-act=tour]")
        page.wait_for_selector("[data-sample=payroll]")
        page.click("[data-sample=payroll]")
        page.wait_for_selector("#tcard h3")
        check("the tour starts on a real program", page.inner_text("#tcard h3") == "Your workspace")
        page.click("#tcard [data-t=next]")
        page.wait_for_function("document.querySelector('#tcard h3').textContent.startsWith('Six sections')")
        page.keyboard.press("Escape")
        check("Escape ends the tour", page.locator("#tour").evaluate("e => e.hidden"))

        # ---- narrow screens
        page.set_viewport_size({"width": 400, "height": 800})
        page.goto(URL + "/#/")
        page.wait_for_selector("#vWork .stats")
        page.wait_for_function("document.body.dataset.side === 'off'", timeout=5000)
        check("the program list is closed on a narrow screen", page.evaluate("document.body.dataset.side") == "off")
        page.click("#sideToggle")
        page.wait_for_function("document.body.dataset.side === 'on'", timeout=5000)
        check("the program list opens as a drawer", page.evaluate("document.body.dataset.side") == "on")
        page.click("#scrim", position={"x": 380, "y": 400})
        check("tapping outside closes the drawer", page.evaluate("document.body.dataset.side") == "off")
        check("nothing scrolls sideways", page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        page.set_viewport_size({"width": 1360, "height": 900})

        # ---- remove the samples
        page.goto(URL + "/#/")
        page.wait_for_selector("[data-act=removeSamples]")
        page.click("[data-act=removeSamples]")
        page.wait_for_selector("#confirmDlg[open]")
        page.click("#cfYes")
        page.wait_for_selector("#vWork .welcome")
        check("samples can be removed in one step", hit(".side-item") == 0)
        check("no script errors", not errors, errors[:2])
        browser.close()

    bad = [r for r in results if not r[0]]
    for ok, label, detail in results:
        print(("PASS  " if ok else "FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(results) - len(bad)} of {len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
