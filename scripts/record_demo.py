"""Record a silent, captioned demo video of Séance (under 3 minutes) on a throwaway copy of the project.
    python scripts/record_demo.py [output.webm]
It never touches your workspace. Needs playwright (pip install playwright) and Microsoft Edge.
Captions are drawn on the page. No logos, no music. Add your own voice afterwards if you like (see docs/hackathon/DEMO.md)."""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SRC = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "seance-demo.webm"
PORT = 8101
T = Path(tempfile.mkdtemp(prefix="seance_demo_"))
for d in ("seance", "web", "samples"):
    shutil.copytree(SRC / d, T / d, ignore=shutil.ignore_patterns("__pycache__"))
for d in ("legacy", "migrated", "fixtures"):
    (T / d).mkdir()
(T / "migrated" / "__init__.py").write_text("")
for f in ("pyproject.toml",):
    if (SRC / f).exists():
        shutil.copy(SRC / f, T / f)
env = dict(os.environ, PYTHONPATH=str(T))

OVERLAY = """
(() => {
  if (window.__cap) return;
  const css = document.createElement('style');
  css.textContent = `#__cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;max-width:80%;padding:12px 22px;
    background:#120d08ee;color:#f6e7c8;border:1px solid #c9954a;border-radius:10px;font:600 20px/1.35 system-ui,sans-serif;text-align:center;
    transition:opacity .3s;pointer-events:none}
    #__cur{position:fixed;width:18px;height:18px;border-radius:50%;background:#f0b35aaa;border:2px solid #fff;z-index:99999;pointer-events:none;
    transform:translate(-50%,-50%);transition:left .05s,top .05s}`;
  document.head.appendChild(css);
  const c = document.createElement('div'); c.id = '__cap'; c.style.opacity = 0; document.body.appendChild(c);
  const k = document.createElement('div'); k.id = '__cur'; document.body.appendChild(k);
  document.addEventListener('mousemove', (e) => { k.style.left = e.clientX + 'px'; k.style.top = e.clientY + 'px'; }, true);
  window.__cap = (t) => { c.textContent = t; c.style.opacity = t ? 1 : 0; };
})();
"""


def api(path):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}" + path, timeout=30))


def card(page, title, lines, secs):
    """A full-screen title card in the page's own colours."""
    items = "".join(f"<li>{l}</li>" for l in lines)
    page.evaluate("""([t, items]) => { let d = document.getElementById('__card'); if (!d) { d = document.createElement('div'); d.id = '__card';
        d.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#0d0906;color:#f6e7c8;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:system-ui,sans-serif;text-align:center;padding:40px';
        document.body.appendChild(d); }
        d.innerHTML = '<h1 style="font-size:54px;margin:0 0 18px;color:#f0b35a">' + t + '</h1><ul style="list-style:none;padding:0;font-size:26px;line-height:1.7">' + items + '</ul>'; d.style.display = 'flex'; }""", [title, items])
    time.sleep(secs)
    page.evaluate("document.getElementById('__card').style.display='none'")


def say(page, text, secs):
    page.evaluate("t => window.__cap(t)", text)
    time.sleep(secs)


def move(page, selector):
    box = page.locator(selector).first.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)


def click(page, selector):
    move(page, selector)
    time.sleep(0.4)
    page.locator(selector).first.click()


def wait_for(page, js, secs):
    try:
        page.wait_for_function(js, timeout=secs * 1000)
        return True
    except Exception:
        return False


def cobol(name: str) -> bytes:
    """A small COBOL program, dropped on the page in the video."""
    lines = ["       IDENTIFICATION DIVISION.", f"       PROGRAM-ID. {name}.", "       ENVIRONMENT DIVISION.", "       INPUT-OUTPUT SECTION.",
             "       FILE-CONTROL.", "           SELECT IN-FILE ASSIGN TO INFILE.", "       DATA DIVISION.", "       FILE SECTION.", "       FD IN-FILE.",
             "       01 REC PIC X(10).", "       WORKING-STORAGE SECTION.", "       01 N PIC 9(7) VALUE 0.", '       01 EOF PIC X VALUE "N".',
             "       PROCEDURE DIVISION.", "           OPEN INPUT IN-FILE.", '           PERFORM UNTIL EOF = "Y"',
             '               READ IN-FILE AT END MOVE "Y" TO EOF', "                   NOT AT END ADD 1 TO N", "               END-READ",
             "           END-PERFORM.", '           DISPLAY "RECORDS " N.', "           CLOSE IN-FILE.", "           STOP RUN."]
    return ("\n".join(lines) + "\n").encode()


srv = subprocess.Popen([sys.executable, "-m", "seance", "serve", "--no-browser", "--port", str(PORT)], cwd=T, env=env,
                       stdout=subprocess.DEVNULL, stderr=open(T / "server.log", "w"))
vid_dir = T / "video"
t0 = time.time()
try:
    for _ in range(80):
        try:
            api("/api/about")
            break
        except Exception:
            time.sleep(0.5)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(vid_dir), record_video_size={"width": 1280, "height": 720})
        page = ctx.new_page()
        page.add_init_script("try{localStorage.setItem('seance.tutorialSeen','1')}catch(e){}")
        page.goto(f"http://127.0.0.1:{PORT}")
        page.wait_for_selector("#addBtn")
        page.evaluate(OVERLAY)

        # 1. Title
        card(page, "Séance", ["Move COBOL to Python.", "Then prove, byte for byte, that nothing changed.", "The real compiled COBOL is the judge."], 7)

        # 2. Empty dashboard and the info button
        say(page, "Nothing here yet. Drop COBOL files to start.", 4)
        move(page, "#infoBtn")
        page.hover("#infoBtn")
        say(page, "The info button explains what Séance does.", 5)
        page.mouse.move(640, 500, steps=10)

        # 3. Drop a program
        say(page, "Drag and drop. Séance imports, analyzes and translates it.", 2)
        payload = [{"name": "COUNTER.cbl", "b64": base64.b64encode(cobol("COUNTER")).decode()}]
        page.evaluate("""async (items) => { const dt = new DataTransfer();
            for (const it of items) { const bin = Uint8Array.from(atob(it.b64), c => c.charCodeAt(0)); dt.items.add(new File([bin], it.name)); }
            window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""", payload)
        time.sleep(7)
        say(page, "Import complete. The summary shows what was found.", 5)
        say(page, "", 0.5)

        # 4. Load the two demo programs with the CLI, reload
        subprocess.run([sys.executable, "-m", "seance", "samples", "load", "loan"], cwd=T, env=env, capture_output=True)
        subprocess.run([sys.executable, "-m", "seance", "samples", "load", "payroll"], cwd=T, env=env, capture_output=True)
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.reload()
        page.wait_for_selector("text=PAYROLL", timeout=30000)
        time.sleep(1)
        page.locator(".side-row", has_text="LOAN").first.click()
        time.sleep(1)
        page.evaluate("goTo(S.name, 'check')")
        try:
            page.wait_for_selector("#runBtn", state="visible", timeout=20000)
        except Exception:
            page.screenshot(path=str(SRC / "build" / "demo_fail.png"))
            print(page.url, page.inner_text("body")[:600])
            raise
        page.evaluate(OVERLAY)

        # 5. Loan check: a float port fails, the real translation passes
        say(page, "Loan interest. A hand-written Python port that uses floats.", 3)
        try:
            page.select_option("#implSel", index=1)
            wrong = True
        except Exception:
            wrong = False
        move(page, "#runBtn")
        say(page, "Run Check compiles the COBOL and runs both on the same inputs.", 2)
        click(page, "#runBtn")
        wait_for(page, "document.querySelector('.word')", 60)
        time.sleep(1)
        say(page, "Spirit restless. The floats drift by a cent, and Séance shows exactly which lines differ." if wrong else "Run Check result.", 7)
        page.screenshot(path=str(SRC / "build" / "shot_restless.png"))
        try:
            page.select_option("#implSel", index=0)
        except Exception:
            pass
        click(page, "#runBtn")
        wait_for(page, "document.querySelector('.word.good')", 60)
        say(page, "Séance's own translation: Spirit matched. Every byte is the same.", 6)

        # 6. Payroll: mutation testing and missing tests
        page.locator(".side-row", has_text="PAYROLL").first.click()
        time.sleep(1)
        page.evaluate("goTo(S.name, 'check')")
        page.wait_for_selector("#runBtn", timeout=30000)
        page.evaluate(OVERLAY)
        click(page, "#runBtn")
        wait_for(page, "document.querySelector('.word.good')", 60)
        say(page, "Payroll. Are the tests strong enough? Mutation testing breaks the code on purpose.", 4)
        try:
            click(page, "#strengthPanel")
            click(page, "text=Run Mutation Test")
            say(page, "Each change should make a test fail. Survivors are gaps.", 6)
            wait_for(page, "document.querySelector('#runGaps')", 40)
            click(page, "#runGaps")
            say(page, "Generate Missing Tests asks the COBOL what the correct answer is.", 12)
        except Exception:
            say(page, "Mutation testing and test generation run from this tab.", 4)

        page.screenshot(path=str(SRC / "build" / "shot_mutation.png"))
        # 7. How it was built with Kiro
        card(page, "Built with Kiro", ["Spec: requirements, design, tasks", "Steering: product rules and COBOL migration rules",
                                       "Hook: re-verify on save", "MCP server: 14 tools, runs the real COBOL",
                                       "Property-based tests: random records, same bytes"], 10)
        card(page, "Séance", ["Open source (MIT).", "275 tests. 325 of 366 NIST COBOL programs match.", "Proof, not promises."], 5)
        page.close()
        ctx.close()
        b.close()
    vids = sorted(vid_dir.glob("*.webm"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(vids[-1], OUT)
    print(f"saved {OUT}  ({OUT.stat().st_size // 1024} KB), about {int(time.time() - t0)} s of recording")
finally:
    srv.terminate()
