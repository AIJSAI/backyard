"""axe-in-browser WCAG sweep over every Backyard surface.

COMMITTED 2026-07-29 because it kept being rewritten. The receipts cite axe runs of 138 and
136 renders, but the harness that produced them lived in a scratch directory and was gone by
the next session — so the project's accessibility evidence was reproducible only in
principle. It is a script rather than a pytest case on purpose: it drives a real browser
against a RUNNING instance (local or production), which is the whole point.

    uv run --with playwright python scripts/axe_sweep.py \
        http://127.0.0.1:8000 /tmp/axe.json <admin-user> <password> \
        [elder-token] [mfa-user] [mfa-password]

Needs axe.min.js beside it (not vendored — fetch the pinned version):
    curl -sSL -o scripts/axe.min.js https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js

Two things it does that a naive sweep does not, both learned the hard way:

  * It runs a DELIBERATE HOVER PASS. A resting-only sweep reported "0 violations, 138
    renders" across two separate runs while every primary button in the product sat at
    3.92:1 in dark mode for as long as a pointer rested on it. An automated sweep never
    hovers unless you make it.
  * It NAMES WHAT IT SKIPPED. Admin surfaces need an instance-admin login; without one, a
    sweep silently covers less than it claims and 24 surfaces reads exactly like 34.

Original docstring follows.

axe-in-browser WCAG sweep over Backyard's surfaces.

Reproduces the 2026-07-26 v3.1 sweep shape (docs/receipts/2026-07-26-axe-v31-sweep-PROD.json):
every surface at desktop AND mobile, in light AND dark, against
wcag2a/wcag2aa/wcag21a/wcag21aa/wcag22aa.

Usage: axe_sweep.py <base_url> <out.json> <admin_user> <admin_pw> [elder_token]

If the login is not an instance admin the admin-only surfaces are SKIPPED and named
in the output, rather than being silently dropped — a sweep that quietly covers less
than it claims is the exact failure mode this project keeps hitting.
"""

from __future__ import annotations

import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = pathlib.Path(sys.argv[2])
USER, PW = sys.argv[3], sys.argv[4]
ELDER_TOKEN = sys.argv[5] if len(sys.argv) > 5 else ""
MFA_USER = sys.argv[6] if len(sys.argv) > 6 else ""
MFA_PW = sys.argv[7] if len(sys.argv) > 7 else ""

AXE = pathlib.Path(__file__).with_name("axe.min.js")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

# (surface, path, needs_admin). Mirrors the 35 in the v3.1 sweep; the member-reachable
# ones run everywhere, the admin ones only when the login can actually see them.
SURFACES: list[tuple[str, str, bool]] = [
    ("home", "/", False),
    ("login", "/accounts/login/", False),
    ("signup-closed", "/accounts/signup/", False),
    ("password-reset", "/accounts/password/reset/", False),
    ("password-reset-done", "/accounts/password/reset/done/", False),
    ("password-reset-key-invalid", "/accounts/password/reset/key/invalid-key/", False),
    ("error-404", "/no-such-page-here/", False),
    ("inactive", "/accounts/inactive/", False),
    ("verification-sent", "/accounts/confirm-email/", False),
    ("feed", "/feed/", False),
    ("pods", "/pods/", False),
    ("directory", "/directory/", False),
    ("profile", "/settings/profile/", False),
    ("notifications", "/settings/notifications/", False),
    ("digest-settings", "/settings/digest/", False),
    ("password-change", "/accounts/password/change/", False),
    ("email-manage", "/accounts/email/", False),
    ("reauthenticate", "/accounts/reauthenticate/", False),
    ("logout", "/accounts/logout/", False),
    ("mfa-index", "/accounts/2fa/", False),
    ("mfa-totp-activate", "/accounts/2fa/totp/activate/", False),
    ("mfa-recovery-codes", "/accounts/2fa/recovery-codes/generate/", False),
    ("mfa-webauthn-list", "/accounts/2fa/webauthn/", False),
    ("mfa-webauthn-add", "/accounts/2fa/webauthn/add/", False),
    ("members", "/members/", True),
    ("members-invites", "/members/invites/", True),
    ("invite-household", "/members/invite-household/", True),
    ("new-elder", "/members/new-elder/", True),
    ("family-sides", "/members/family-sides/", True),
    ("metrics", "/members/metrics/", True),
    ("digests", "/members/digests/", True),
    ("quarantine", "/members/quarantine/", True),
]

VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
THEMES = ("light", "dark")

results: list[dict] = []
skipped: list[str] = []


def run_axe_hover(page) -> dict:
    """Re-run axe with the primary button HOVERED, scoped to that button."""
    btn = page.locator("button[type=submit], input[type=submit], .btn").first
    if btn.count() == 0 or not btn.is_visible():
        return {"violations": []}
    btn.hover()
    page.wait_for_timeout(250)  # longer than the 120ms background-color transition
    return page.evaluate(
        """async (tags) => {
             const el = document.querySelector(
               'button[type=submit], input[type=submit], .btn');
             if (!el) return { violations: [] };
             const r = await axe.run(el, { runOnly: { type: 'tag', values: tags } });
             return { violations: r.violations.map(v => ({
                 id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
                 targets: v.nodes.slice(0, 3).map(n => n.target.join(' ')),
                 messages: v.nodes.slice(0, 3).flatMap(
                   n => (n.any || []).map(a => a.message)),
             })) };
           }""",
        TAGS,
    )


def run_axe(page) -> dict:
    # NOT add_script_tag: the app ships a baseline CSP (S-724) with no 'unsafe-inline',
    # so a real <script> element is blocked — correctly. add_init_script injects through
    # the debugger protocol before load, which CSP does not govern.
    return page.evaluate(
        """async (tags) => {
             const r = await axe.run(document, { runOnly: { type: 'tag', values: tags } });
             return {
               violations: r.violations.map(v => ({
                 id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
                 targets: v.nodes.slice(0, 3).map(n => n.target.join(' ')),
                 messages: v.nodes.slice(0, 3).flatMap(
                   n => (n.any || []).map(a => a.message)),
               })),
             };
           }""",
        TAGS,
    )


with sync_playwright() as p:
    browser = p.chromium.launch()
    is_admin = None
    for vp_name, (w, h) in VIEWPORTS.items():
        for theme in THEMES:
            ctx = browser.new_context(
                viewport={"width": w, "height": h}, color_scheme=theme, device_scale_factor=1
            )
            ctx.add_init_script(path=str(AXE))
            page = ctx.new_page()

            page.goto(f"{BASE}/accounts/login/", wait_until="networkidle")
            page.fill("input[name=login]", USER)
            page.fill("input[name=password]", PW)
            page.click("button[type=submit], input[type=submit]")
            page.wait_for_load_state("networkidle")
            if "/accounts/login" in page.url:
                sys.exit(f"LOGIN FAILED as {USER}")

            if is_admin is None:
                r = page.goto(f"{BASE}/members/", wait_until="networkidle")
                is_admin = bool(r and r.status == 200)
                print(f"  admin surfaces reachable as {USER}: {is_admin}")

            for name, path, needs_admin in SURFACES:
                if needs_admin and not is_admin:
                    tag = f"{name} ({vp_name}/{theme})"
                    skipped.append(tag)
                    continue
                resp = page.goto(BASE + path, wait_until="networkidle")
                page.mouse.move(0, 0)  # resting means resting
                page.evaluate("() => document.fonts.ready")
                page.wait_for_timeout(400)
                out = run_axe(page)
                hov = run_axe_hover(page)
                for v in hov["violations"]:
                    v["state"] = "hover"
                out["violations"] = out["violations"] + hov["violations"]
                sc = [v for v in out["violations"] if v["impact"] in ("serious", "critical")]
                results.append(
                    {
                        "surface": name,
                        "viewport": vp_name,
                        "theme": theme,
                        "status": resp.status if resp else 0,
                        "serious_critical": len(sc),
                        "all_violations": len(out["violations"]),
                        "detail": out["violations"],
                    }
                )
                if out["violations"]:
                    print(f"  !! {name} {vp_name}/{theme}: {out['violations']}")

            # mfa-authenticate exists only DURING a challenge, so it cannot be a plain
            # GET: sign a TOTP-protected user in and stop at the second factor.
            if MFA_USER:
                page.goto(f"{BASE}/accounts/logout/", wait_until="networkidle")
                try:
                    page.click("button[type=submit], input[type=submit]")
                    page.wait_for_load_state("networkidle")
                except Exception as exc:  # noqa: BLE001
                    # A logout page with no submit button is fine; anything else is worth
                    # seeing rather than swallowing, since a failed logout would make the
                    # next login look like a rate-limit problem.
                    print(f"  (logout step skipped: {type(exc).__name__})")
                page.goto(f"{BASE}/accounts/login/", wait_until="networkidle")
                page.fill("input[name=login]", MFA_USER)
                page.fill("input[name=password]", MFA_PW)
                page.click("button[type=submit], input[type=submit]")
                page.wait_for_load_state("networkidle")
                if "2fa/authenticate" in page.url:
                    page.evaluate("() => document.fonts.ready")
                    out = run_axe(page)
                    sc = [v for v in out["violations"] if v["impact"] in ("serious", "critical")]
                    results.append(
                        {
                            "surface": "mfa-authenticate",
                            "viewport": vp_name,
                            "theme": theme,
                            "status": 200,
                            "serious_critical": len(sc),
                            "all_violations": len(out["violations"]),
                            "detail": out["violations"],
                        }
                    )
                    if out["violations"]:
                        print(f"  !! mfa-authenticate {vp_name}/{theme}: {out['violations']}")
                else:
                    skipped.append(f"mfa-authenticate ({vp_name}/{theme}) url={page.url}")

            # The elder surface is standalone and session-based: exchange the token.
            if ELDER_TOKEN:
                page.goto(f"{BASE}/t/{ELDER_TOKEN}/", wait_until="networkidle")
                resp = page.goto(f"{BASE}/e/", wait_until="networkidle")
                out = run_axe(page)
                sc = [v for v in out["violations"] if v["impact"] in ("serious", "critical")]
                results.append(
                    {
                        "surface": "elder-feed",
                        "viewport": vp_name,
                        "theme": theme,
                        "status": resp.status if resp else 0,
                        "serious_critical": len(sc),
                        "all_violations": len(out["violations"]),
                        "detail": out["violations"],
                    }
                )
                if out["violations"]:
                    print(f"  !! elder-feed {vp_name}/{theme}: {out['violations']}")
            ctx.close()
    browser.close()

OUT.write_text(json.dumps(results, indent=1))
total_v = sum(r["all_violations"] for r in results)
total_sc = sum(r["serious_critical"] for r in results)
print(f"\n{len(results)} renders, {len({r['surface'] for r in results})} surfaces")
print(f"violations (any severity): {total_v}   serious/critical: {total_sc}")
if skipped:
    print(f"SKIPPED (not reachable as {USER}): {len(skipped)} renders")
    print("  " + ", ".join(sorted({s.split(" ")[0] for s in skipped})))
print("report ->", OUT)
