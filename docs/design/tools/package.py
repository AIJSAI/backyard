"""Turn the full-page capture masters into an upload package Claude Design can actually read.

Why tiling: Claude's vision path downscales an image so its long edge fits the cap. A
1440x6712 full-page feed capture arrives at ~336px wide, rendering 16px body text at ~4px -
visually useless. Slicing the same master into 1440x1400 tiles keeps every tile at 1:1.

Rules applied: one surface per image (no montages), viewport-sized tiles, PNG, no edge over
2000px, at most 20 images per batch, and a text label emitted immediately before each image.
"""

from __future__ import annotations

import json
import math
import pathlib
import shutil

from PIL import Image

ROOT = pathlib.Path("/private/tmp/claude-501/-Users-james/9368f9e0-d430-4f66-94e6-87051c456148/scratchpad")
SHOTS = ROOT / "shots"
PKG = ROOT / "package"

# Master capture geometry. Desktop is 1x so 1 image px == 1 CSS px; mobile is 2x.
GEO = {"desktop": (1440, 1, 1400), "mobile": (390, 2, 780), "narrow": (320, 2, 780)}
# Two tiles is enough to judge a surface: the chrome plus the first screenful of real content.
# The feed and the long thread earn a third because their rhythm only shows over distance.
MAX_TILES = 2
DEEP = {"feed", "post-long-thread", "post-gallery5"}
PER_MESSAGE = 20  # hard cap: above 20 images a request a stricter per-image size limit applies

BATCHES: list[tuple[str, str, list[tuple[str, str, str, str]]]] = [
    (
        "batch-1-core-desktop",
        "The twelve surfaces that carry the product, at desktop. Read these before proposing anything.",
        [
            ("auth-login", "desktop", "light", "SIGN IN - renders django-allauth's raw package default: zero CSS, a literal 'Menu:' bulleted list, and a live 'Sign Up' link on an invite-only site. First and most-repeated surface in the product."),
            ("error-404", "desktop", "light", "NOT FOUND - Django's unbranded default. Authorization denials are 404s by design, so members hit this in ordinary use."),
            ("home-logged-out", "desktop", "light", "FRONT DOOR for an invited relative. Currently reads 'Backyard is running / Your family's private instance is up' - a health check, not a welcome."),
            ("join-valid", "desktop", "light", "INVITE ACCEPTANCE - the second screen a new family member ever sees."),
            ("feed", "desktop", "light", "THE FEED, populated, instance admin who bridges both family sides. Note the ~600px column in a 1440px viewport and the red 'Take down' pill on every post."),
            ("post-long-thread", "desktop", "light", "POST DETAIL with an eight-reply thread, including replies that arrived by email."),
            ("post-gallery5", "desktop", "light", "POST with five photos at five different aspect ratios (4:3, 3:4 portrait, 1:1, 21:9 panorama). No grid, no crop policy."),
            ("post-edit-form", "desktop", "light", "EDIT POST - representative form surface."),
            ("directory", "desktop", "light", "FAMILY DIRECTORY."),
            ("member-profile", "desktop", "light", "MEMBER PROFILE with kinship name, dates and per-field visibility."),
            ("admin-members", "desktop", "light", "ADMIN MEMBERS - role pills, supervised flags, destructive actions. Representative of the admin long tail."),
            ("elder-feed", "desktop", "light", "ELDER READER - a standalone template with its own stylesheet, pinned at ~17:1 contrast and >=48px targets. Deliberately light-only, single column."),
        ],
    ),
    (
        "batch-2-core-mobile",
        "The identical twelve surfaces at mobile. Same handles.",
        [
            ("auth-login", "mobile", "light", "SIGN IN, mobile."),
            ("error-404", "mobile", "light", "NOT FOUND, mobile."),
            ("home-logged-out", "mobile", "light", "FRONT DOOR, mobile."),
            ("join-valid", "mobile", "light", "INVITE ACCEPTANCE, mobile."),
            ("feed", "mobile", "light", "THE FEED, mobile - the primary real-world surface for most of this family."),
            ("post-long-thread", "mobile", "light", "POST DETAIL with thread, mobile."),
            ("post-gallery5", "mobile", "light", "FIVE-PHOTO POST, mobile."),
            ("post-edit-form", "mobile", "light", "EDIT POST, mobile."),
            ("directory", "mobile", "light", "DIRECTORY, mobile."),
            ("member-profile", "mobile", "light", "MEMBER PROFILE, mobile."),
            ("admin-members", "mobile", "light", "ADMIN MEMBERS, mobile - a table on a 390px screen."),
            ("elder-feed", "mobile", "light", "ELDER READER, mobile - how a 79-year-old actually holds it."),
        ],
    ),
    (
        "batch-3-states-and-modes",
        "States, dark theme, and accessibility modes. These are where a design system is actually tested.",
        [
            ("feed", "desktop", "dark", "THE FEED in dark theme. Currently a near-black IDE ground, not a designed dusk."),
            ("post-long-photo", "desktop", "dark", "POST with photo and five named reactors, dark theme."),
            ("empty-feed", "desktop", "light", "DAY-ONE EMPTY FEED - what the founder's family sees the hour they are invited."),
            ("composer-error", "desktop", "light", "COMPOSER VALIDATION ERROR, server-rendered."),
            ("compose-confirm", "desktop", "light", "CONFIRM-ON-WIDEN - sharing beyond your own household asks first, by name and headcount."),
            ("delete-confirm", "desktop", "light", "DESTRUCTIVE CONFIRM."),
            ("post-video-pending", "desktop", "light", "VIDEO STILL TRANSCODING - a server-rendered pending state. There is no JavaScript spinner and there cannot be one."),
            ("post-portrait", "mobile", "light", "PORTRAIT PHOTO on mobile."),
            ("member-profile-long-name", "desktop", "light", "OVERFLOW - a 38-character display name with a kinship name."),
            ("feed-text-zoom-200", "desktop", "light", "200% TEXT ZOOM (WCAG SC 1.4.4)."),
            ("feed-reflow-320", "narrow", "light", "320px REFLOW (WCAG SC 1.4.10)."),
            ("forced-colors-feed", "desktop", "light", "FORCED-COLORS / Windows High Contrast. The repo has zero forced-colors handling today: card elevation is shadow-only, so boundaries disappear."),
            ("forced-colors-login", "desktop", "light", "FORCED-COLORS on the raw allauth sign-in."),
            ("admin-metrics", "desktop", "light", "CONNECTION HEALTH TABLE - unstyled table, headers wrapping mid-word, no numeric alignment."),
            ("admin-quarantine", "desktop", "light", "QUARANTINED INBOUND MAIL - admin review queue."),
            ("admin-invites", "desktop", "light", "OUTSTANDING INVITES - live, expiring, revoked, fully used."),
            ("handover-link", "desktop", "light", "HAND-OVER PAGE - the link and QR code a delegate physically hands a grandparent."),
            ("digest-web", "desktop", "light", "DIGEST WEB VIEW - what a digest deep link opens, with no login at all."),
            ("email-digest", "desktop", "light", "THE WEEKLY DIGEST EMAIL. Currently the best-looking surface in the product; the app does not live up to it."),
            ("pwa-favicon-16px-proof", "asset", "-", "THE APP ICON DOWNSAMPLED TO 16px and magnified. This is the favicon test the mark fails today."),
        ],
    ),
    (
        "batch-4-unstyled-auth-and-errors",
        "The thirty surfaces with no design at all. All of these inherit from just three allauth layout templates plus three Django error templates.",
        [
            ("auth-login-error", "desktop", "light", "SIGN IN with a wrong password."),
            ("auth-signup-closed", "desktop", "light", "SIGNUP CLOSED - reachable today from the live link on the sign-in page."),
            ("auth-password-reset", "desktop", "light", "PASSWORD RESET request."),
            ("auth-password-reset-done", "desktop", "light", "PASSWORD RESET sent."),
            ("auth-password-reset-key-invalid", "desktop", "light", "PASSWORD RESET link invalid."),
            ("auth-password-change", "desktop", "light", "CHANGE PASSWORD (signed in) - a 'manage' layout surface."),
            ("auth-email-manage", "desktop", "light", "EMAIL ADDRESSES (signed in)."),
            ("auth-mfa-index", "desktop", "light", "TWO-FACTOR OVERVIEW."),
            ("auth-mfa-authenticate", "desktop", "light", "TWO-FACTOR CHALLENGE at sign-in."),
            ("auth-mfa-totp-activate", "desktop", "light", "AUTHENTICATOR SETUP - a QR code and a secret a 79-year-old is expected to transcribe."),
            ("auth-mfa-recovery-codes", "desktop", "light", "RECOVERY CODES."),
            ("auth-mfa-webauthn-add", "desktop", "light", "ADD A PASSKEY."),
            ("auth-reauthenticate", "desktop", "light", "CONFIRM IT IS YOU."),
            ("auth-logout", "desktop", "light", "SIGN OUT confirmation."),
            ("auth-inactive", "desktop", "light", "ACCOUNT INACTIVE."),
            ("error-500", "desktop", "light", "SERVER ERROR - Django's default, 145 bytes."),
            ("error-403-csrf", "desktop", "light", "CSRF FAILURE - what a member gets from a stale tab or a back-button resubmit."),
            ("error-404-denied-post", "desktop", "light", "PERMISSION DENIED, rendered as a 404 by design (the isolation model never confirms that other content exists)."),
            ("setup-empty", "mobile", "light", "FIRST-RUN SETUP - the founder's very first screen, captured at mobile."),
            ("setup-error", "mobile", "light", "FIRST-RUN SETUP with a wrong secret."),
        ],
    ),
]


def tile(src: pathlib.Path, dest_dir: pathlib.Path, handle: str, vp: str, cap: int) -> list[tuple[str, int, int]]:
    """Slice a full-page master into 1:1 tiles. Returns (filename, index, total)."""
    im = Image.open(src)
    w, h = im.size
    if vp == "asset":
        out = dest_dir / f"{handle}.png"
        shutil.copy(src, out)
        return [(out.name, 1, 1)]
    _css_w, dpr, tile_css_h = GEO[vp]
    tile_px_h = tile_css_h * dpr
    total = min(cap, max(1, math.ceil(h / tile_px_h)))
    made = []
    for i in range(total):
        top = i * tile_px_h
        box = (0, top, w, min(h, top + tile_px_h))
        name = f"{handle}.png" if total == 1 else f"{handle}-{i+1}of{total}.png"
        im.crop(box).save(dest_dir / name)
        made.append((name, i + 1, total))
    return made


CSS_LABEL = {
    "desktop": "1440x900 CSS @1x",
    "mobile": "390x844 CSS @2x",
    "narrow": "320x700 CSS @2x",
    "asset": "raw asset",
}


def main() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    stage = PKG / ".stage"
    stage.mkdir(parents=True)

    entries: list[dict] = []
    truncated: list[str] = []
    missing: list[str] = []
    n = 0
    for batch_title, blurb, items in BATCHES:
        for handle, vp, theme, note in items:
            n += 1
            by = f"BY-{n:02d}"
            src = SHOTS / (f"{handle}.png" if vp == "asset" else f"{handle}__{vp}__{theme}.png")
            if not src.exists():
                missing.append(src.name)
                continue
            cap = 3 if handle in DEEP else MAX_TILES
            full_h = Image.open(src).size[1]
            made = tile(src, stage, f"{by}-{handle}-{vp}", vp, cap)
            if vp != "asset" and full_h > GEO[vp][2] * GEO[vp][1] * cap:
                shown = GEO[vp][2] * cap
                truncated.append(
                    f"{by} {handle} ({vp}): the page is {full_h // GEO[vp][1]} CSS px tall; "
                    f"the top {shown} CSS px are included, the rest is not"
                )
            for name, i, tot in made:
                entries.append(
                    {
                        "batch": batch_title,
                        "blurb": blurb,
                        "src_name": name,
                        "handle": f"{by}{'' if tot == 1 else f'-{i}of{tot}'}",
                        "label": (
                            f"{by}{'' if tot == 1 else f'-{i}of{tot}'} · {handle} · "
                            f"{CSS_LABEL[vp]} · {theme} · {note}"
                            f"{'' if tot == 1 else f' — tile {i} of {tot}, scrolled down'}"
                        ),
                    }
                )

    # Chunk into upload messages. A batch may span messages; never mix batches in one
    # message, so each message stays a coherent thing to talk about.
    messages: list[list[dict]] = []
    for batch_title, _blurb, _items in BATCHES:
        rows = [e for e in entries if e["batch"] == batch_title]
        for i in range(0, len(rows), PER_MESSAGE):
            messages.append(rows[i : i + PER_MESSAGE])

    doc = [
        "# Screenshot upload plan\n\n",
        "Claude Design receives no filenames and no image metadata, so the label line is the\n",
        "only handle it has on a surface. **Paste each label line immediately before its image.**\n",
        "Put all the images of a message first and any instruction text last.\n\n",
        "Each folder below is ONE message. Do not exceed 20 images in a message, and do not\n",
        "merge folders — every image here is already sized so it is never downscaled.\n\n",
    ]
    manifest: dict[str, list[dict]] = {}
    for mi, rows in enumerate(messages, 1):
        folder = f"message-{mi:02d}"
        d = PKG / folder
        d.mkdir()
        doc.append(f"\n---\n\n## {folder} — {rows[0]['batch']} ({len(rows)} images)\n\n{rows[0]['blurb']}\n\n")
        out_rows = []
        for j, e in enumerate(rows, 1):
            fname = f"{j:02d}-{e['src_name']}"
            shutil.move(str(stage / e["src_name"]), str(d / fname))
            doc.append(f"**{j:02d}.** `{e['label']}`\n\n")
            out_rows.append({"file": fname, "label": e["label"]})
        manifest[folder] = out_rows

    if truncated:
        doc.append("\n---\n\n## Coverage note — what is deliberately not shown\n\n")
        doc.append("These pages are longer than the tiles included. Nothing is hidden; the tail is\n")
        doc.append("simply more of the same rhythm, and the surfaces below carry it:\n\n")
        for t in truncated:
            doc.append(f"- {t}\n")
    if missing:
        doc.append("\n## MISSING capture masters\n\n" + "".join(f"- {m}\n" for m in missing))

    shutil.rmtree(stage)
    (PKG / "UPLOAD-PLAN.md").write_text("".join(doc))
    (PKG / "manifest.json").write_text(json.dumps(manifest, indent=1))
    total = sum(len(v) for v in manifest.values())
    print(f"package built: {total} images across {len(messages)} upload messages")
    for k, v in manifest.items():
        print(f"  {k}: {len(v)}")
    if truncated:
        print(f"coverage notes logged: {len(truncated)}")
    if missing:
        print("MISSING:", missing)


if __name__ == "__main__":
    main()
