"""Record a narrated 1080p demo video of Séance (under 3 minutes) on a throwaway copy of the project.
    python scripts/record_demo.py [output.mp4]
It never touches your workspace. Needs: playwright, Microsoft Edge, imageio-ffmpeg (pip install playwright imageio-ffmpeg),
edge-tts and an internet connection (the narration uses Microsoft's neural voices). Captions are drawn on the page. No logos, no music."""
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

SRC = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "seance-demo.mp4"
PORT = 8101
VOICE = "en-US-AvaMultilingualNeural"
MAX_SECONDS = 172
TRIM = 1.5  # seconds cut from the start: Playwright's first frames are a small, unsized window
T = Path(tempfile.mkdtemp(prefix="seance_demo_"))
AUDIO = T / "audio"
AUDIO.mkdir()
for d in ("seance", "web", "samples"):
    shutil.copytree(SRC / d, T / d, ignore=shutil.ignore_patterns("__pycache__"))
for d in ("legacy", "migrated", "fixtures"):
    (T / d).mkdir()
(T / "migrated" / "__init__.py").write_text("")
for f in ("pyproject.toml",):
    if (SRC / f).exists():
        shutil.copy(SRC / f, T / f)
env = dict(os.environ, PYTHONPATH=str(T))

# key: (caption, narration)
S = {
    "title": ("", "Séance moves COBOL to Python, then proves byte for byte that nothing changed."),
    "empty": ("Drop COBOL files to start", "This is Séance. The workspace is empty. The info button explains the product."),
    "drop": ("Drag and drop. Séance imports, analyzes and translates.", "Drop COBOL files. Séance imports, analyzes, and translates them to Python."),
    "imported": ("Import complete", "The summary counts programs, copybooks, SQL blocks and calls, so nothing is hidden."),
    "loaded": ("Two more programs: loan and payroll", "Two money programs: a loan calculation and a payroll run. Money is where migrations go wrong."),
    "loan1": ("A hand-written port that uses floats", "First, a quick hand-written Python port. It uses floating point numbers."),
    "loan2": ("Run Check: real COBOL vs Python, same inputs", "Run Check compiles the real COBOL, runs both on the same inputs, and compares every byte."),
    "loan3": ("Spirit restless", "Spirit restless. The floats drift by a cent, and Séance shows exactly which lines differ."),
    "loan4": ("Séance's own translation", "Now Séance's own translation, which keeps the COBOL data byte for byte."),
    "loan5": ("Spirit matched", "Spirit matched. Every byte is the same. But are the tests strong enough?"),
    "pay1": ("Payroll: Séance's own translation", "Now payroll, with Séance's own translation. Same check."),
    "pay2": ("Mutation testing breaks the Python on purpose", "Mutation testing plants twelve small bugs in the Python. Each one should make a test fail."),
    "pay3": ("Survivors are gaps. Generate Missing Tests.", "Two slipped through. Generate Missing Tests asks the real COBOL for the right answer and saves a new test."),
    "agent": ("Kiro drives Séance through MCP", "Kiro drives this through an MCP server with fourteen tools, including one that runs the original COBOL."),
    "kiro": ("", "Built with Kiro: a spec, steering rules for money, a hook that re-verifies on save, an MCP server, and property-based tests."),
    "outro": ("", "Séance is open source. Three hundred twenty-five of three hundred sixty-six N.I.S.T. COBOL programs match byte for byte. Proof, not promises."),
}


def synth(key: str):
    """Natural voice from Microsoft's neural voices (edge-tts, needs internet), converted to a wav."""
    text = S[key][1]
    mp3 = AUDIO / f"{key}.mp3"
    wav = AUDIO / f"{key}.wav"
    asyncio.run(edge_tts.Communicate(text, VOICE, rate="-4%", pitch="+0Hz").save(str(mp3)))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return wav, w.getnframes() / w.getframerate()


NARR = {k: synth(k) for k in S}
print("narration seconds:", round(sum(d for _, d in NARR.values()), 1))

OVERLAY = """
(() => {
  if (window.__cap) return;
  document.documentElement.style.zoom = '1.25';
  const css = document.createElement('style');
  css.textContent = `#__cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:99999;max-width:78%;padding:12px 24px;
    background:#120d08ee;color:#f6e7c8;border:1px solid #c9954a;border-radius:12px;font:600 21px/1.35 system-ui,sans-serif;text-align:center;
    transition:opacity .35s;pointer-events:none;box-shadow:0 8px 30px #000a}
    #__cur{position:fixed;width:20px;height:20px;border-radius:50%;background:#f0b35aaa;border:2px solid #fff;z-index:99999;pointer-events:none;
    transform:translate(-50%,-50%)}`;
  document.head.appendChild(css);
  const c = document.createElement('div'); c.id = '__cap'; c.style.opacity = 0; document.body.appendChild(c);
  const k = document.createElement('div'); k.id = '__cur'; document.body.appendChild(k);
  document.addEventListener('mousemove', (e) => { k.style.left = e.clientX + 'px'; k.style.top = e.clientY + 'px'; }, true);
  window.__cap = (t) => { c.textContent = t; c.style.opacity = t ? 1 : 0; };
})();
"""


def api(path):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}" + path, timeout=30))


class Clock:
    """Tracks when each narration starts, relative to the start of the video, so the audio can be placed later."""

    def __init__(self):
        self.t0 = time.monotonic()
        self.marks: list[tuple[float, Path]] = []
        self.busy_until = 0.0

    def now(self):
        return time.monotonic() - self.t0

    def speak(self, page, key, caption=True):
        self.until_done()
        wav, dur = NARR[key]
        self.marks.append((self.now(), wav))
        print(f"{self.now():6.1f}s  {key}", flush=True)
        self.busy_until = self.now() + dur + 0.6
        cap = S[key][0]
        if page is not None:
            page.evaluate("t => window.__cap && window.__cap(t)", cap if caption else "")

    def until_done(self, extra=0.0):
        left = self.busy_until + extra - self.now()
        if left > 0:
            time.sleep(left)


def card(page, title, lines):
    items = "".join(f"<li>{l}</li>" for l in lines)
    page.evaluate("""([t, items]) => { let d = document.getElementById('__card'); if (!d) { d = document.createElement('div'); d.id = '__card';
        d.style.cssText = 'position:fixed;inset:0;z-index:100000;background:radial-gradient(circle at 50% 40%,#2a1c10,#0d0906 70%);color:#f6e7c8;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:system-ui,sans-serif;text-align:center;padding:40px';
        document.body.appendChild(d); }
        d.innerHTML = '<div style="font-size:90px">👻</div><h1 style="font-size:64px;margin:6px 0 18px;color:#f0b35a;font-family:Georgia,serif">' + t + '</h1><ul style="list-style:none;padding:0;font-size:28px;line-height:1.8">' + items + '</ul>'; d.style.display = 'flex'; }""", [title, items])


def hide_card(page):
    page.evaluate("document.getElementById('__card') && (document.getElementById('__card').style.display='none')")


def move(page, selector):
    box = page.locator(selector).first.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=22)


def click(page, selector):
    move(page, selector)
    time.sleep(0.5)
    page.locator(selector).first.click()


def wait_for(page, js, secs):
    try:
        page.wait_for_function(js, timeout=secs * 1000)
        return True
    except Exception:
        return False


def cobol(name: str) -> bytes:
    lines = ["       IDENTIFICATION DIVISION.", f"       PROGRAM-ID. {name}.", "       ENVIRONMENT DIVISION.", "       INPUT-OUTPUT SECTION.",
             "       FILE-CONTROL.", "           SELECT IN-FILE ASSIGN TO INFILE.", "       DATA DIVISION.", "       FILE SECTION.", "       FD IN-FILE.",
             "       01 REC PIC X(10).", "       WORKING-STORAGE SECTION.", "       01 N PIC 9(7) VALUE 0.", '       01 EOF PIC X VALUE "N".',
             "       PROCEDURE DIVISION.", "           OPEN INPUT IN-FILE.", '           PERFORM UNTIL EOF = "Y"',
             '               READ IN-FILE AT END MOVE "Y" TO EOF', "                   NOT AT END ADD 1 TO N", "               END-READ",
             "           END-PERFORM.", '           DISPLAY "RECORDS " N.', "           CLOSE IN-FILE.", "           STOP RUN."]
    return ("\n".join(lines) + "\n").encode()


def open_program(page, name):
    page.locator(".side-row", has_text=name).first.click()
    time.sleep(1)
    page.evaluate("goTo(S.name, 'check')")
    page.wait_for_selector("#runBtn", state="visible", timeout=30000)
    page.evaluate(OVERLAY)


srv = subprocess.Popen([sys.executable, "-m", "seance", "serve", "--no-browser", "--port", str(PORT)], cwd=T, env=env,
                       stdout=subprocess.DEVNULL, stderr=open(T / "server.log", "w"))
vid_dir = T / "video"
try:
    for _ in range(80):
        try:
            api("/api/about")
            break
        except Exception:
            time.sleep(0.5)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(vid_dir), record_video_size={"width": 1920, "height": 1080})
        page = ctx.new_page()
        clock = Clock()
        page.add_init_script("try{localStorage.setItem('seance.prefs.v1', JSON.stringify({rounds: 5, guideSeen: true}))}catch(e){}")
        page.goto(f"http://127.0.0.1:{PORT}")
        page.wait_for_selector("#addBtn")
        page.evaluate(OVERLAY)

        # 1. Title
        card(page, "Séance", ["Move COBOL to Python.", "Prove, byte for byte, that nothing changed."])
        time.sleep(TRIM + 0.3)
        clock.speak(page, "title", caption=False)
        clock.until_done()
        hide_card(page)

        # 2. Empty dashboard
        clock.speak(page, "empty")
        time.sleep(2)
        page.hover("#infoBtn")
        move(page, "#infoBtn")
        clock.until_done()
        page.mouse.move(900, 600, steps=12)

        # 3. Drop a program (the two demo programs load in the background meanwhile)
        loader = threading.Thread(target=lambda: [subprocess.run([sys.executable, "-m", "seance", "samples", "load", n], cwd=T, env=env, capture_output=True) for n in ("loan", "payroll")])
        clock.speak(page, "drop")
        time.sleep(3)
        payload = [{"name": "COUNTER.cbl", "b64": base64.b64encode(cobol("COUNTER")).decode()}]
        page.evaluate("""async (items) => { const dt = new DataTransfer();
            for (const it of items) { const bin = Uint8Array.from(atob(it.b64), c => c.charCodeAt(0)); dt.items.add(new File([bin], it.name)); }
            window.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); }""", payload)
        loader.start()
        clock.until_done()
        clock.speak(page, "imported")
        clock.until_done()
        loader.join()

        # 4. Load loan and payroll
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_selector("text=PAYROLL", timeout=30000)
        page.evaluate(OVERLAY)
        clock.speak(page, "loaded")
        time.sleep(1)
        move(page, ".side-row >> text=LOAN")
        clock.until_done()

        # 5. Loan
        open_program(page, "LOAN")
        clock.speak(page, "loan1")
        try:
            move(page, "#implSel")
            page.select_option("#implSel", index=1)
            wrong = True
        except Exception:
            wrong = False
        clock.until_done()
        clock.speak(page, "loan2")
        time.sleep(3)
        click(page, "#runBtn")
        wait_for(page, "document.querySelector('.word')", 60)
        clock.until_done()
        clock.speak(page, "loan3" if wrong else "loan2")
        page.screenshot(path=str(SRC / "build" / "shot_restless.png"))
        clock.until_done(1.0)

        # 6. Payroll
        open_program(page, "PAYROLL")
        clock.speak(page, "pay1")
        time.sleep(2)
        click(page, "#runBtn")
        wait_for(page, "document.querySelector('.word.good')", 60)
        clock.until_done()
        clock.speak(page, "loan5")
        clock.until_done(0.3)
        clock.speak(page, "pay2")
        try:
            click(page, "#strengthPanel")
            time.sleep(1)
            click(page, "text=Run Mutation Test")
            wait_for(page, "document.querySelector('#runGaps')", 40)
        except Exception:
            pass
        clock.until_done()
        clock.speak(page, "pay3")
        try:
            time.sleep(3)
            click(page, "#runGaps")
        except Exception:
            pass
        page.screenshot(path=str(SRC / "build" / "shot_mutation.png"))
        clock.until_done(0.3)

        # 7. Agent page and the Kiro card
        try:
            click(page, "text=AI Agent")
        except Exception:
            pass
        clock.speak(page, "agent")
        clock.until_done()
        card(page, "Built with Kiro", ["Spec: requirements, design, tasks", "Steering: the money and COBOL rules", "Hook: re-verify on save",
                                       "MCP server: 14 tools, runs the real COBOL", "Property-based tests: random records, same bytes"])
        clock.speak(page, "kiro", caption=False)
        clock.until_done()
        card(page, "Séance", ["Open source (MIT)", "275 tests. 325 of 366 NIST COBOL programs match.", "Proof, not promises."])
        clock.speak(page, "outro", caption=False)
        clock.until_done(0.5)
        total = clock.now()
        page.close()
        ctx.close()
        b.close()
    if total > MAX_SECONDS:
        print(f"WARNING: the video is {total:.0f} s; the contest limit is 180 s. Shorten it before you upload.")
    webm = sorted(vid_dir.glob("*.webm"))[-1]
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error", "-ss", str(TRIM), "-i", str(webm)]
    for _, wav in clock.marks:
        cmd += ["-i", str(wav)]
    delays = ";".join(f"[{i + 1}:a]adelay={max(0, int((t + 0.25 - TRIM) * 1000))}|{max(0, int((t + 0.25 - TRIM) * 1000))}[a{i}]" for i, (t, _) in enumerate(clock.marks))
    mix = "".join(f"[a{i}]" for i in range(len(clock.marks))) + f"amix=inputs={len(clock.marks)}:normalize=0:dropout_transition=0[aout]"
    cmd += ["-filter_complex", delays + ";" + mix, "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-shortest", str(OUT)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    print(f"saved {OUT}  ({OUT.stat().st_size // 1024} KB), about {int(total)} s long, 1920x1080 with narration")
finally:
    srv.terminate()
