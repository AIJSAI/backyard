"""Systematic surface capture for the Backyard design pass.

Every user-facing surface, at two viewports and both themes, in every state we can
drive: first-run, empty, populated, validation errors, confirmations, permission
denials, the elder path, the token paths, and the currently-unstyled allauth and
Django error surfaces.

Usage:
    python capture.py firstrun   # fresh DB: setup wizard + genuine day-one empty states
    python capture.py populated  # after seeding: every populated + edge state
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BACKYARD_BASE_URL", "http://localhost:8000")
# Must match whatever seed_demo.py minted, which is now generated and written to the capture
# manifest. No default here on purpose: a literal default is a committed credential wearing an
# env var's clothes. See src/core/tests/test_no_hardcoded_demo_credentials.py.
DEMO_PW = os.environ.get("BACKYARD_DEMO_PASSWORD")
if not DEMO_PW:
    raise SystemExit(
        "Set BACKYARD_DEMO_PASSWORD to the password seed_demo.py used. It writes it to "
        '/data/seed_manifest.json (the "password" field) and prints only counts, so read it '
        "from there — or set BACKYARD_DEMO_PASSWORD for both scripts and skip the lookup."
    )
# Was hardcoded to one machine's per-session scratch dir, so this committed tool could not run
# for anyone else - including a later session on the same machine.
ROOT = pathlib.Path(os.environ.get("BACKYARD_CAPTURE_DIR", "/tmp/backyard-capture"))
ROOT.mkdir(parents=True, exist_ok=True)
SHOTS = ROOT / "shots"
STATE = ROOT / "state"
SHOTS.mkdir(exist_ok=True)
STATE.mkdir(exist_ok=True)

# dpr chosen so the widest edge lands under ~1600px: Claude's vision path downscales
# above that, so anything larger is wasted bytes with no extra legibility.
VIEWPORTS = {"mobile": (390, 844, 2), "desktop": (1440, 900, 1)}
THEMES = ("light", "dark")

ok: list[str] = []
bad: list[tuple[str, str]] = []


def shot(page, slug: str, vp: str, theme: str, *, full: bool = True) -> None:
    name = f"{slug}__{vp}__{theme}.png"
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.screenshot(path=str(SHOTS / name), full_page=full)
        ok.append(name)
    except Exception as exc:  # pragma: no cover - capture harness
        bad.append((name, repr(exc)))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def guard(slug: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # pragma: no cover - capture harness
        bad.append((slug, f"{exc!r}\n{traceback.format_exc(limit=2)}"))


def login(ctx, username: str, password: str) -> None:
    """Sign in and PROVE it. A silent login failure just captures the login page under
    every authenticated filename, which looks like a clean run and is worthless - so a
    failure here is fatal, not logged."""
    pg = ctx.new_page()
    pg.goto(f"{BASE}/accounts/login/", wait_until="domcontentloaded")
    pg.fill("input[name=login]", username)
    pg.fill("input[name=password]", password)
    pg.click("button[type=submit], input[type=submit]")
    pg.wait_for_load_state("networkidle")
    pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded")
    if "/accounts/login/" in pg.url or pg.locator("textarea[name=body]").count() == 0:
        raise SystemExit(
            f"LOGIN FAILED for {username}: landed on {pg.url} with no composer. "
            f"Body: {pg.inner_text('body')[:300]!r}"
        )
    pg.close()


# --------------------------------------------------------------------------- surfaces
# (slug, path) pairs captured by a plain authenticated GET.
ADMIN_GETS = [
    ("admin-members", "/members/"),
    ("admin-invites", "/members/invites/"),
    ("admin-invite-household", "/members/invite-household/"),
    ("admin-metrics", "/members/metrics/"),
    ("admin-digests", "/members/digests/"),
    ("admin-quarantine", "/members/quarantine/"),
    ("admin-family-sides", "/members/family-sides/"),
    ("admin-new-elder", "/members/new-elder/"),
]
MEMBER_GETS = [
    ("feed", "/feed/"),
    ("directory", "/directory/"),
    ("pods", "/pods/"),
    ("settings-profile", "/settings/profile/"),
    ("settings-notifications", "/settings/notifications/"),
    ("settings-digest", "/settings/digest/"),
]
# The 30 allauth surfaces currently rendering the package's unstyled defaults.
ALLAUTH_AUTHED = [
    ("auth-logout", "/accounts/logout/"),
    ("auth-email-manage", "/accounts/email/"),
    ("auth-password-change", "/accounts/password/change/"),
    ("auth-reauthenticate", "/accounts/reauthenticate/"),
    ("auth-mfa-index", "/accounts/2fa/"),
    ("auth-mfa-totp-activate", "/accounts/2fa/totp/activate/"),
    ("auth-mfa-recovery-codes", "/accounts/2fa/recovery-codes/"),
    ("auth-mfa-recovery-generate", "/accounts/2fa/recovery-codes/generate/"),
    ("auth-mfa-webauthn-list", "/accounts/2fa/webauthn/"),
    ("auth-mfa-webauthn-add", "/accounts/2fa/webauthn/add/"),
]
ALLAUTH_ANON = [
    ("auth-login", "/accounts/login/"),
    ("auth-signup-closed", "/accounts/signup/"),
    ("auth-password-reset", "/accounts/password/reset/"),
    ("auth-password-reset-done", "/accounts/password/reset/done/"),
    ("auth-password-reset-key-invalid", "/accounts/password/reset/key/bogus-bogus/"),
    ("auth-password-reset-key-done", "/accounts/password/reset/key/done/"),
    ("auth-inactive", "/accounts/inactive/"),
    ("auth-email-verification-sent", "/accounts/confirm-email/"),
    ("auth-login-code-confirm", "/accounts/login/code/confirm/"),
    ("auth-mfa-authenticate", "/accounts/2fa/authenticate/"),
]
ERROR_ANON = [
    ("error-404", "/this-page-does-not-exist/"),
    ("error-404-denied-post", "/posts/999999/"),
]


def anon_surfaces(ctx, vp: str, theme: str) -> None:
    pg = ctx.new_page()
    for slug, path in ALLAUTH_ANON + ERROR_ANON:
        guard(slug, lambda p=path, s=slug: (pg.goto(BASE + p, wait_until="domcontentloaded"), shot(pg, s, vp, theme)))
    # A real CSRF rejection, rendered from the actual 403 response body.
    guard("error-403-csrf", lambda: (
        pg.set_content(ctx.request.post(f"{BASE}/compose/", data={"body": "x"}).text()),
        shot(pg, "error-403-csrf", vp, theme),
    ))
    pg.close()


# --------------------------------------------------------------------------- phases
def firstrun(p) -> None:
    """Fresh instance: the setup wizard and the genuine day-one empty app."""
    secret = (ROOT / "setup_secret.txt").read_text().strip()
    browser = p.chromium.launch()
    done_setup = False

    for vp, (w, h, dpr) in VIEWPORTS.items():
        for theme in THEMES:
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=dpr,
                color_scheme=theme,
            )
            pg = ctx.new_page()
            if not done_setup:
                guard("setup", lambda: (pg.goto(f"{BASE}/setup/", wait_until="domcontentloaded"), shot(pg, "setup-empty", vp, theme)))
                guard("setup-error", lambda: (
                    pg.fill("input[name=setup_secret]", "not-the-secret"),
                    pg.fill("input[name=username]", "founder"),
                    pg.fill("input[name=password]", "short"),
                    pg.fill("input[name=display_name]", "James Whitfield"),
                    pg.fill("input[name=yard_name]", "Whitfield side"),
                    pg.fill("input[name=pod_name]", "The Whitfields"),
                    pg.click("button[type=submit]"),
                    pg.wait_for_load_state("networkidle"),
                    shot(pg, "setup-error", vp, theme),
                ))
            else:
                guard("setup-closed", lambda: (pg.goto(f"{BASE}/setup/", wait_until="domcontentloaded"), shot(pg, "setup-closed-404", vp, theme)))
            pg.close()
            ctx.close()

        # Complete setup exactly once, after both themes have seen the form.
        if not done_setup:
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr)
            pg = ctx.new_page()
            pg.goto(f"{BASE}/setup/", wait_until="domcontentloaded")
            pg.fill("input[name=setup_secret]", secret)
            pg.fill("input[name=username]", "james")
            pg.fill("input[name=password]", DEMO_PW)
            pg.fill("input[name=display_name]", "James Whitfield")
            pg.fill("input[name=yard_name]", "Whitfield side")
            pg.fill("input[name=pod_name]", "The Whitfields")
            pg.click("button[type=submit]")
            pg.wait_for_load_state("networkidle")
            ctx.storage_state(path=str(STATE / "founder.json"))
            pg.close()
            ctx.close()
            done_setup = True

    # Day-one empty states, both viewports and themes.
    for vp, (w, h, dpr) in VIEWPORTS.items():
        for theme in THEMES:
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=dpr,
                color_scheme=theme,
                storage_state=str(STATE / "founder.json"),
            )
            pg = ctx.new_page()
            for slug, path in MEMBER_GETS + ADMIN_GETS:
                guard(slug, lambda p_=path, s=slug: (pg.goto(BASE + p_, wait_until="domcontentloaded"), shot(pg, f"empty-{s}", vp, theme)))
            for slug, path in ALLAUTH_AUTHED:
                guard(slug, lambda p_=path, s=slug: (pg.goto(BASE + p_, wait_until="domcontentloaded"), shot(pg, s, vp, theme)))
            pg.close()
            ctx.close()

            anon = browser.new_context(
                viewport={"width": w, "height": h}, device_scale_factor=dpr, color_scheme=theme
            )
            ap = anon.new_page()
            guard("home-logged-out", lambda: (ap.goto(f"{BASE}/", wait_until="domcontentloaded"), shot(ap, "home-logged-out", vp, theme)))
            ap.close()
            anon_surfaces(anon, vp, theme)
            anon.close()

    browser.close()


def populated(p) -> None:
    """Seeded instance: every populated surface, thread, gallery and edge state."""
    man = json.loads((ROOT / "seed_manifest.json").read_text())
    pw = man["password"]
    posts = man["post_ids"]
    mids = man["member_ids"]
    pids = man["pod_ids"]
    browser = p.chromium.launch()

    # One login per role, reused across every viewport/theme combination.
    for role, user in [("james", "james"), ("rob", "rob"), ("nora", "nora"), ("kenji", "kenji")]:
        st = STATE / f"{role}.json"
        if not st.exists():
            ctx = browser.new_context()
            login(ctx, user, pw)
            ctx.storage_state(path=str(st))
            ctx.close()

    member_gets = MEMBER_GETS + [
        ("post-long-photo", f"/posts/{posts['long_with_photo']}/"),
        ("post-link-image", f"/posts/{posts['link_with_image']}/"),
        ("post-link-bare", f"/posts/{posts['link_bare']}/"),
        ("post-gallery3", f"/posts/{posts['gallery3']}/"),
        ("post-gallery5", f"/posts/{posts['gallery5']}/"),
        ("post-portrait", f"/posts/{posts['portrait']}/"),
        ("post-video-pending", f"/posts/{posts['video_pending']}/"),
        ("post-video-failed", f"/posts/{posts['video_failed']}/"),
        ("post-long-thread", f"/posts/{posts['long_thread']}/"),
        ("post-edited", f"/posts/{posts['edited']}/"),
        ("post-yardwide", f"/posts/{posts['yardwide']}/"),
        ("post-edit-form", f"/posts/{posts['short']}/edit/"),
        ("member-profile", f"/directory/{mids['gran']}/"),
        ("member-profile-long-name", f"/directory/{mids['wilhelmina']}/"),
        ("member-profile-supervised", f"/directory/{mids['teddy']}/"),
    ]
    admin_gets = ADMIN_GETS + [
        ("admin-elder-link", f"/members/{mids['gran']}/elder-link/"),
        ("admin-supervised", "/members/supervised/"),
    ]

    for vp, (w, h, dpr) in VIEWPORTS.items():
        for theme in THEMES:
            base_kw = {
                "viewport": {"width": w, "height": h},
                "device_scale_factor": dpr,
                "color_scheme": theme,
            }

            # --- instance admin, bridging household: sees both family sides
            ctx = browser.new_context(**base_kw, storage_state=str(STATE / "james.json"))
            pg = ctx.new_page()
            for slug, path in member_gets + admin_gets:
                guard(slug, lambda p_=path, s=slug: (pg.goto(BASE + p_, wait_until="domcontentloaded"), shot(pg, s, vp, theme)))
            # Composer validation. The browser's own `required` blocks submission, so
            # drop it to reach the SERVER-rendered error - the state a member actually
            # sees when validation fails for a reason HTML5 cannot catch.
            guard("composer-error", lambda: (
                pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"),
                pg.evaluate("document.querySelector('textarea[name=body]').removeAttribute('required')"),
                pg.click(".composer button[type=submit]"),
                pg.wait_for_load_state("networkidle"),
                shot(pg, "composer-error", vp, theme),
            ))
            # confirm-on-widen: sharing to a whole family side asks first (TM-3).
            # Assert the confirm page actually rendered - if the checkbox silently
            # misses, the post goes through pod-only and quietly pollutes the seed.
            guard("compose-confirm", lambda: (
                pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"),
                pg.fill("textarea[name=body]", "Shall we all go in on a marquee for the christening?"),
                # Must post from a HOUSEHOLD pod: an ad-hoc pod never widens to a yard
                # (S-204), so the confirm step would correctly not fire.
                pg.select_option("select[name=pod_id]", label="The Whitfields"),
                pg.locator("input[name=audience_yards]").first.check(),
                pg.click(".composer button[type=submit]"),
                pg.wait_for_load_state("networkidle"),
                _assert(pg.locator("input[name=confirm_wide]").count() == 1,
                        f"compose-confirm did not render the confirm page (url={pg.url})"),
                shot(pg, "compose-confirm", vp, theme),
            ))
            guard("delete-confirm", lambda: (
                pg.goto(f"{BASE}/posts/{posts['short']}/delete/", wait_until="domcontentloaded"),
                shot(pg, "delete-confirm", vp, theme),
            ))
            guard("pod-detail", lambda: (
                pg.goto(f"{BASE}/pods/", wait_until="domcontentloaded"),
                shot(pg, "pods-populated", vp, theme),
            ))
            # accessibility evidence on the primary surface
            guard("feed-zoom200", lambda: (
                pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"),
                pg.evaluate("document.documentElement.style.fontSize='200%'"),
                shot(pg, "feed-text-zoom-200", vp, theme),
                pg.evaluate("document.documentElement.style.fontSize=''"),
            ))
            pg.close()
            ctx.close()

            # --- ordinary member on the other family side: proves isolation visually
            ctx = browser.new_context(**base_kw, storage_state=str(STATE / "kenji.json"))
            pg = ctx.new_page()
            guard("feed-other-side", lambda: (pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"), shot(pg, "feed-other-side", vp, theme)))
            guard("directory-other-side", lambda: (pg.goto(f"{BASE}/directory/", wait_until="domcontentloaded"), shot(pg, "directory-other-side", vp, theme)))
            guard("members-denied", lambda: (pg.goto(f"{BASE}/members/", wait_until="domcontentloaded"), shot(pg, "members-denied-404", vp, theme)))
            pg.close()
            ctx.close()

            # --- yard admin: the delegate view of the admin surfaces
            ctx = browser.new_context(**base_kw, storage_state=str(STATE / "rob.json"))
            pg = ctx.new_page()
            guard("feed-yard-admin", lambda: (pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"), shot(pg, "feed-yard-admin", vp, theme)))
            guard("admin-members-yard-admin", lambda: (pg.goto(f"{BASE}/members/", wait_until="domcontentloaded"), shot(pg, "admin-members-yard-admin", vp, theme)))
            pg.close()
            ctx.close()

            # --- token surfaces, no login at all
            anon = browser.new_context(**base_kw)
            ap = anon.new_page()
            guard("join", lambda: (ap.goto(f"{BASE}/join/{man['invite_tokens']['live']}/", wait_until="domcontentloaded"), shot(ap, "join-valid", vp, theme)))
            guard("join-expired", lambda: (ap.goto(f"{BASE}/join/{man['invite_tokens']['expired']}/", wait_until="domcontentloaded"), shot(ap, "join-expired", vp, theme)))
            guard("join-revoked", lambda: (ap.goto(f"{BASE}/join/{man['invite_tokens']['revoked']}/", wait_until="domcontentloaded"), shot(ap, "join-revoked", vp, theme)))
            guard("join-full", lambda: (ap.goto(f"{BASE}/join/{man['invite_tokens']['full']}/", wait_until="domcontentloaded"), shot(ap, "join-full", vp, theme)))
            guard("digest-web", lambda: (ap.goto(f"{BASE}/d/{man['digest_tokens']['james']}/", wait_until="domcontentloaded"), shot(ap, "digest-web", vp, theme)))
            guard("digest-web-post", lambda: (
                ap.goto(f"{BASE}/d/{man['digest_tokens']['james']}/posts/{posts['long_with_photo']}/", wait_until="domcontentloaded"),
                shot(ap, "digest-web-post", vp, theme),
            ))
            guard("digest-link-expired", lambda: (ap.goto(f"{BASE}/d/not-a-real-token-at-all/", wait_until="domcontentloaded"), shot(ap, "digest-link-expired", vp, theme)))
            ap.close()
            anon_surfaces(anon, vp, theme)
            anon.close()

            # --- the elder path: its own standalone, deliberately light surface
            eld = browser.new_context(**base_kw)
            ep = eld.new_page()
            guard("elder", lambda: (
                ep.goto(f"{BASE}/t/{man['elder_tokens']['gran']}/", wait_until="domcontentloaded"),
                shot(ep, "elder-feed", vp, theme),
            ))
            guard("elder-big", lambda: (
                ep.goto(f"{BASE}/e/", wait_until="domcontentloaded"),
                ep.click("form[action='/e/text/'] button"),
                ep.wait_for_load_state("networkidle"),
                shot(ep, "elder-feed-big-text", vp, theme),
            ))
            ep.close()
            eld.close()

    # forced-colors (Windows High Contrast) on the two surfaces that matter most
    for slug, path, state in [("feed", "/feed/", "james.json"), ("login", "/accounts/login/", None)]:
        kw = {"viewport": {"width": 1440, "height": 900}, "forced_colors": "active"}
        if state:
            kw["storage_state"] = str(STATE / state)
        ctx = browser.new_context(**kw)
        pg = ctx.new_page()
        guard(f"forced-colors-{slug}", lambda p_=path, s=slug: (pg.goto(BASE + p_, wait_until="domcontentloaded"), shot(pg, f"forced-colors-{s}", "desktop", "light")))
        pg.close()
        ctx.close()

    # 320px reflow, the WCAG minimum width
    ctx = browser.new_context(viewport={"width": 320, "height": 700}, device_scale_factor=2, storage_state=str(STATE / "james.json"))
    pg = ctx.new_page()
    guard("reflow-320", lambda: (pg.goto(f"{BASE}/feed/", wait_until="domcontentloaded"), shot(pg, "feed-reflow-320", "narrow", "light")))
    pg.close()
    ctx.close()

    browser.close()


def failed_login_shots(p) -> None:
    """Run LAST, always: a wrong password burns the per-IP `login_failed` budget
    (5/5m/ip), which would lock every later real sign-in out of the harness."""
    browser = p.chromium.launch()
    for vp, (w, h, dpr) in VIEWPORTS.items():
        for theme in THEMES:
            ctx = browser.new_context(
                viewport={"width": w, "height": h}, device_scale_factor=dpr, color_scheme=theme
            )
            pg = ctx.new_page()
            guard("auth-login-error", lambda: (
                pg.goto(f"{BASE}/accounts/login/", wait_until="domcontentloaded"),
                pg.fill("input[name=login]", "nora"),
                pg.fill("input[name=password]", "definitely-not-the-password"),
                pg.click("button[type=submit], input[type=submit]"),
                pg.wait_for_load_state("networkidle"),
                shot(pg, "auth-login-error", vp, theme),
            ))
            pg.close()
            ctx.close()
    browser.close()


if __name__ == "__main__":
    phase = sys.argv[1]
    with sync_playwright() as p:
        {"firstrun": firstrun, "populated": populated}[phase](p)
        failed_login_shots(p)
    print(f"captured {len(ok)} shots")
    if bad:
        print(f"FAILED {len(bad)}:")
        for name, err in bad:
            print(f"  - {name}: {err.splitlines()[0]}")
    (ROOT / f"capture_{phase}_report.json").write_text(json.dumps({"ok": ok, "bad": bad}, indent=2))
