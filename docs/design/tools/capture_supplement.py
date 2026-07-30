"""The remaining flows the main harness could not reach with a plain GET:
the hand-over artifact page, the two digest token surfaces, and break-glass recovery."""

from __future__ import annotations

import json
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
# Was hardcoded to one machine's per-session scratch dir; same override as capture.py.
ROOT = pathlib.Path(os.environ.get("BACKYARD_CAPTURE_DIR", "/tmp/backyard-capture"))
SHOTS = ROOT / "shots"
STATE = ROOT / "state"
VIEWPORTS = {"mobile": (390, 844, 2), "desktop": (1440, 900, 1)}
THEMES = ("light", "dark")

ok, bad = [], []
bg_url = (ROOT / "break_glass_url.txt").read_text().strip() if (ROOT / "break_glass_url.txt").exists() else ""


def shot(pg, slug, vp, theme):
    try:
        pg.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    pg.screenshot(path=str(SHOTS / f"{slug}__{vp}__{theme}.png"), full_page=True)
    ok.append(f"{slug}__{vp}__{theme}")


def guard(slug, fn):
    try:
        fn()
    except Exception as exc:
        bad.append((slug, repr(exc)))


with sync_playwright() as p:
    browser = p.chromium.launch()
    n = 0
    for vp, (w, h, dpr) in VIEWPORTS.items():
        for theme in THEMES:
            kw = {"viewport": {"width": w, "height": h}, "device_scale_factor": dpr, "color_scheme": theme}

            ctx = browser.new_context(**kw, storage_state=str(STATE / "james.json"))
            pg = ctx.new_page()
            # The hand-over page: what a delegate actually gives a grandparent (link + QR).
            n += 1
            guard("handover-link", lambda: (
                pg.goto(f"{BASE}/members/new-elder/", wait_until="domcontentloaded"),
                pg.fill("#elder_name", f"Rosalind Whitfield {n}"),
                pg.fill("#kinship_name", "Great-Gran"),
                pg.fill("#household_name", f"Rosalind's house {n}"),
                pg.click("button[type=submit]"),
                pg.wait_for_load_state("networkidle"),
                shot(pg, "handover-link", vp, theme),
            ))
            # Removing a member: the most consequential destructive confirm in the app.
            guard("member-remove-confirm", lambda: (
                pg.goto(f"{BASE}/members/", wait_until="domcontentloaded"),
                shot(pg, "admin-members-actions", vp, theme),
            ))
            pg.close()
            ctx.close()

            anon = browser.new_context(**kw)
            ap = anon.new_page()
            guard("digest-confirm", lambda: (
                ap.goto(f"{BASE}/digest/confirm/confirm-james/", wait_until="domcontentloaded"),
                shot(ap, "digest-confirm", vp, theme),
            ))
            guard("digest-unsubscribe", lambda: (
                ap.goto(f"{BASE}/digest/unsubscribe/unsub-james/", wait_until="domcontentloaded"),
                shot(ap, "digest-unsubscribe", vp, theme),
            ))
            if bg_url:
                guard("break-glass", lambda: (
                    ap.goto(bg_url, wait_until="domcontentloaded"),
                    shot(ap, "break-glass", vp, theme),
                ))
            ap.close()
            anon.close()
    browser.close()

print(f"supplement captured {len(ok)}")
if bad:
    print("FAILED:", json.dumps(bad, indent=1))
    sys.exit(0)
