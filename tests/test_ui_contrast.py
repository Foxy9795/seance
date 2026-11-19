"""The product steering requires WCAG AA contrast for the UI: every text colour on every surface it can appear on."""

import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")


def _vars() -> dict[str, str]:
    root = re.search(r":root\s*\{(.*?)\}", HTML, re.S).group(1)
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", root))


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


SURFACES = ["bg", "panel", "panel2", "sunk", "hover"]
TEXT = ["text", "muted", "faint", "amber-text", "good", "bad", "warn"]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("text", TEXT)
def test_text_colour_has_aa_contrast_on_every_surface(text, surface):
    v = _vars()
    assert _ratio(v[text], v[surface]) >= 4.5, f"{text} {v[text]} on {surface} {v[surface]}"


def test_primary_button_has_aa_contrast():
    v = _vars()
    assert _ratio(v["amber-ink"], v["amber"]) >= 4.5


def test_code_gutter_and_comment_colour_have_aa_contrast():
    sunk = _vars()["sunk"]
    for colour in set(re.findall(r"\.ln i \{[^}]*color:\s*(#[0-9a-fA-F]{6})", HTML) + re.findall(r"\.ln\.cm \{[^}]*color:\s*(#[0-9a-fA-F]{6})", HTML)):
        assert _ratio(colour, sunk) >= 4.5, colour
