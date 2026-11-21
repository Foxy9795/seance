"""Scripted UI audit: walks every screen and dialog in Edge and reports problems.  python scripts/audit_ui.py  (python -m seance serve first)

Checks, on each screen: script and console errors, native dropdowns (every list must be the page's own), controls without a name,
interactive targets smaller than 24 px, text below WCAG AA contrast, duplicate ids, sideways overflow, dialogs without a name, and
floating surfaces (menus, lists, the header, toasts, dialogs) that are not fully opaque.
Loads three samples for the run and removes them at the end. Exit code 1 when anything is found.
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8000"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

PROBE = r"""
() => {
  const out = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden]'); };
  const path = (el) => { const p = []; while (el && el.nodeType === 1 && p.length < 4) { p.unshift(el.tagName.toLowerCase() + (el.id ? '#' + el.id : el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : '')); el = el.parentElement; } return p.join(' > '); };
  const scope = document.querySelector('dialog[open]') || document;
  const inScope = (el) => scope === document ? !el.closest('dialog:not([open])') : scope.contains(el);
  // accessible names
  const nameOf = (el) => (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'))?.textContent || el.innerText || el.value || el.getAttribute('title') || (el.labels && el.labels[0]?.textContent) || el.getAttribute('placeholder') || '').trim();
  scope.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=menuitem]').forEach((el) => {
    if (!vis(el) && el.type !== 'file') return; if (!inScope(el)) return;
    if (!nameOf(el)) out.push(['no-name', path(el)]);
    const r = el.getBoundingClientRect();
    if (vis(el) && el.type !== 'checkbox' && el.type !== 'radio' && !(el.tagName === 'A' && el.closest('td, p, li, .note, .sample-card, .md')) && (r.height < 24 || r.width < 24)) out.push(['small-target', path(el) + ` ${Math.round(r.width)}x${Math.round(r.height)}`]);
  });
  // native selects must not exist as the thing a person sees open: nothing to check statically, but selects must be styled
  scope.querySelectorAll('select').forEach((el) => { if (vis(el) && getComputedStyle(el).appearance === 'auto') out.push(['native-select-look', path(el)]); });
  // contrast
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const [r, g, b, a = 1] = m[1].split(',').map((x) => parseFloat(x)); return [r, g, b, a]; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => { let layers = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } } let base = [14, 12, 16]; for (const c of layers.reverse()) base = base.map((v, i) => i < 3 ? c[i] * c[3] + v * (1 - c[3]) : 1); return base; };
  const seen = new Set();
  const walker = document.createTreeWalker(scope === document ? document.body : scope, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent.trim(); if (!t) continue; const el = n.parentElement; if (!el || !vis(el) || !inScope(el)) continue;
    if (['SCRIPT', 'STYLE', 'OPTION'].includes(el.tagName) || el.closest('.sr, #tour .spot, #toasts')) continue;
    const cs = getComputedStyle(el); const fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el); const a = fg[3]; const mixed = [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
    const [hi, lo] = [lum(mixed), lum(bg)].sort((x, y) => y - x); const ratio = (hi + 0.05) / (lo + 0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700; const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
    if (ratio < need && !el.closest('[disabled], [aria-disabled=true]') && cs.opacity === '1') { const k = path(el) + t.slice(0, 20); if (!seen.has(k)) { seen.add(k); out.push(['low-contrast', `${ratio.toFixed(1)}:1 ${path(el)} "${t.slice(0, 40)}"`]); } }
  }
  // floating surfaces must be opaque, so no text behind them shows through
  document.querySelectorAll('.menu, .dd, .toast, header.top, .pbar, dialog[open], .tcard').forEach((el) => {
    if (!vis(el)) return; const bgc = getComputedStyle(el).backgroundColor; const c = parse(bgc);
    if (!c || c[3] < 1) out.push(['see-through', `${path(el)} ${bgc}`]);
  });
  // ids, overflow
  const ids = {}; document.querySelectorAll('[id]').forEach((e) => { ids[e.id] = (ids[e.id] || 0) + 1; }); Object.entries(ids).forEach(([k, v]) => { if (v > 1) out.push(['duplicate-id', k]); });
  if (document.documentElement.scrollWidth > innerWidth + 1) out.push(['sideways-scroll', `${document.documentElement.scrollWidth} > ${innerWidth}`]);
  document.querySelectorAll('dialog[open]').forEach((d) => { if (!d.getAttribute('aria-labelledby') && !d.getAttribute('aria-label')) out.push(['dialog-no-name', path(d)]); });
  // text that spills out of its box
  scope.querySelectorAll('button, .badge, .chipbtn, .pill, .tab, [role=tab]').forEach((el) => { if (vis(el) && el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow === 'visible' && el.clientWidth > 0 && getComputedStyle(el).whiteSpace === 'nowrap' && el.scrollWidth - el.clientWidth > 4) out.push(['clipped', path(el)]); });
  return out;
}
"""


def cli(*args: str) -> None:
    subprocess.run([PY, "-m", "seance", *args], cwd=ROOT, check=True, capture_output=True)


def main() -> int:
    cli("samples", "remove")
    for n in ("payroll", "customer_master", "nightly_batch", "customer_inquiry"):
        cli("samples", "load", n)
    findings: dict[str, list] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")

        def run(label: str, page) -> None:
            for kind, detail in page.evaluate(PROBE):
                findings.setdefault(label, []).append((kind, detail))

        for vw, vh, tag in ((1360, 900, "wide"), (400, 800, "narrow")):
            ctx = browser.new_context(viewport={"width": vw, "height": vh})
            ctx.add_init_script("localStorage.setItem('seance.prefs.v1', JSON.stringify({guideSeen: true}))")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)

            def view(label, url, wait):
                page.goto(URL + url)
                page.wait_for_selector(wait, timeout=60000)
                page.wait_for_timeout(350)
                run(f"{tag} {label}", page)

            view("workspace", "/#/", "#vWork .stats")
            view("overview", "/#/p/payroll/overview", "#pOverview .panel")
            view("code", "/#/p/payroll/code", "#pyPane .ln")
            view("analysis", "/#/p/payroll/analysis", "#pAnalysis .mcard")
            view("job analysis", "/#/p/nightly_batch/analysis", "#pAnalysis .mcard")
            view("assessment", "/#/assessment", "#vPort tbody tr")
            view("check (no report)", "/#/p/customer_master/check", "#pCheck .panel")
            view("try", "/#/p/payroll/try", "#runTry")
            view("data", "/#/p/payroll/data", "#recordAgain")
            view("job", "/#/p/nightly_batch/overview", ".steps")
            view("cics try", "/#/p/customer_inquiry/try", "#runTry")
            page.goto(URL + "/#/")
            page.wait_for_selector("#vWork .stats")
            for label, opener, wait in (
                ("add dialog", "#addBtn", "#addDlg[open]"),
                ("settings", "#setBtn", "#setDlg[open]"),
                ("palette", None, "#palDlg[open]"),
                ("shortcuts", None, "#keysDlg[open]"),
                ("guide", None, "#guideDlg[open]"),
                ("help menu", '[data-menu="helpMenu"]', "#helpMenu:not([hidden])"),
            ):
                if opener:
                    page.click(opener)
                elif label == "palette":
                    page.keyboard.press("Control+k")
                elif label == "shortcuts":
                    page.evaluate("openKeys()")
                else:
                    page.evaluate("openGuide()")
                page.wait_for_selector(wait)
                page.wait_for_timeout(350)
                run(f"{tag} {label}", page)
                page.keyboard.press("Escape")
                page.wait_for_function("!document.querySelector('dialog[open]')")
            # every dropdown must open the page's own list, never the system one
            for label, url, sel in (("sort", "/#/", "#sortSel"), ("python", "/#/p/payroll/overview", "#implSel"), ("try set", "/#/p/payroll/try", "#trySet")):
                page.goto(URL + url)
                page.wait_for_timeout(700)
                try:
                    page.wait_for_selector(sel, timeout=15000, state="attached")
                except Exception:
                    continue
                if not page.locator(sel).is_visible():
                    continue
                page.click(sel)
                ok = page.locator(".dd .dd-opt").count() >= 1
                if not ok:
                    findings.setdefault(f"{tag} dropdowns", []).append(("native-dropdown", label))
                page.keyboard.press("Escape")
            if errors:
                findings.setdefault(f"{tag} errors", []).extend(("script-error", e[:160]) for e in errors[:5])
            ctx.close()
        browser.close()
    cli("samples", "remove")
    total = 0
    for label, items in findings.items():
        uniq = list(dict.fromkeys(items))
        total += len(uniq)
        print(f"\n== {label} ({len(uniq)})")
        for kind, detail in uniq[:25]:
            print(f"  {kind:<16} {detail}")
        if len(uniq) > 25:
            print(f"  ... and {len(uniq) - 25} more")
    print(f"\n{total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
