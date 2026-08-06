"""Deterministic demo seed for the Backyard design-capture pass.

Local-only. Builds two family sides, a bridging household, ~17 members spanning every
role, and posts that exercise every visual state the design system has to survive:
long/short bodies, link previews with and without a re-hosted image, photo counts 1/3/5,
portrait + panorama aspect ratios, a pending and a failed video, a long comment thread,
email-arrived replies, an edited post, a moderator takedown, reactions, upcoming dates,
the unread boundary, invites in every lifecycle state, digests in every delivery state,
quarantined inbound mail, six weeks of metrics, and two elder tokens.

Writes /data/seed_manifest.json with the credentials and URLs the capture harness needs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import random
import secrets

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from core.models import (
    Comment,
    DigestDelivery,
    DigestIssue,
    DigestSubscription,
    DigestToken,
    ElderToken,
    InboundQuarantine,
    Invite,
    InviteRedemption,
    LinkPreview,
    MediaAsset,
    Member,
    MemberWeekPresence,
    NotificationPreference,
    Pod,
    PodMembership,
    PodWeekMetrics,
    Post,
    Reaction,
    Yard,
    YardWeekMetrics,
)

random.seed(20260725)
User = get_user_model()
NOW = timezone.now()
# Local demo fixtures only. The old default was a literal, justified by "never runs against a
# real deployment" - a promise, not a guard, and its twin in scripts/demo_seed.py turned out to
# be live on the internet. What this harness reproduces is the RENDERING, and no screenshot
# depends on the password, so it is generated and written to the manifest like everything else.
PW = os.environ.get("BACKYARD_DEMO_PASSWORD") or secrets.token_urlsafe(12)


def sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def ago(days: float = 0, hours: float = 0) -> dt.datetime:
    return NOW - dt.timedelta(days=days, hours=hours)


# --------------------------------------------------------------------------- images
def photo(w: int, h: int, palette: str) -> bytes:
    """A soft, photographic-ish placeholder: sky gradient, horizon band, simple
    silhouettes, blur and grain. Deliberately abstract - these stand in for family
    photos so layout, aspect ratio and card treatment can be judged honestly."""
    schemes = {
        "dusk": ((58, 74, 110), (198, 154, 128), (44, 52, 46)),
        "garden": ((150, 186, 205), (222, 226, 196), (72, 94, 62)),
        "kitchen": ((208, 194, 172), (232, 220, 200), (120, 92, 68)),
        "beach": ((176, 205, 222), (238, 228, 206), (196, 178, 146)),
        "porch": ((120, 140, 150), (206, 200, 184), (86, 76, 66)),
        "cake": ((226, 216, 208), (240, 232, 224), (176, 122, 110)),
    }
    top, mid, ground = schemes[palette]
    img = Image.new("RGB", (w, h), mid)
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.62)
    for y in range(horizon):
        t = y / max(horizon, 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (mid[i] - top[i]) * t) for i in range(3)))
    for y in range(horizon, h):
        t = (y - horizon) / max(h - horizon, 1)
        d.line(
            [(0, y), (w, y)],
            fill=tuple(int(ground[i] + (mid[i] - ground[i]) * (1 - t) * 0.35) for i in range(3)),
        )
    for _ in range(6):
        cx = random.randint(0, w)
        rr = random.randint(int(h * 0.08), int(h * 0.3))
        d.ellipse(
            [cx - rr, horizon - rr, cx + rr, horizon + int(rr * 0.4)],
            fill=tuple(max(0, c - 18) for c in ground),
        )
    img = img.filter(ImageFilter.GaussianBlur(radius=max(2, w // 220)))
    px = img.load()
    for _ in range(w * h // 90):
        x, y = random.randrange(w), random.randrange(h)
        r, g, b = px[x, y]
        n = random.randint(-9, 9)
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=86)
    return buf.getvalue()


def attach_photo(post: Post, w: int, h: int, palette: str, alt: str) -> MediaAsset:
    full = photo(w, h, palette)
    tw = 640
    th = max(1, int(h * (tw / w)))
    thumb = photo(tw, th, palette)
    a = MediaAsset(post=post, media_kind=MediaAsset.PHOTO, content_type="image/jpeg", alt_text=alt)
    a.image.save(f"p{post.pk}-{palette}-{w}x{h}.jpg", ContentFile(full), save=False)
    a.thumbnail.save(f"t{post.pk}-{palette}-{w}x{h}.jpg", ContentFile(thumb), save=False)
    a.save()
    return a


# Its own marker, distinct from `scripts/demo_seed.py`'s "demo": the two seeds build
# different families, and either must be removable without disturbing the other. Remove this
# one with `manage.py wipe_demo_data --marker design --dry-run`, then `--yes`.
#
# Before the marker existed nothing tied these rows to this file, and the QA seed's wipe
# reached for `Pod.objects.all().delete()` partly because of it: it could not name what it
# wanted to delete, so it deleted everything.
SEEDED_BY = "design"

# --------------------------------------------------------------------------- yards + pods
yard_a, _ = Yard.objects.get_or_create(
    slug="whitfield-side", defaults={"name": "Whitfield side", "seeded_by": SEEDED_BY}
)
yard_b, _ = Yard.objects.get_or_create(
    slug="ferreira-nakamura-side",
    defaults={"name": "Ferreira-Nakamura side", "seeded_by": SEEDED_BY},
)

pods: dict[str, Pod] = {}
POD_SPEC = [
    ("bridge", "The Whitfields", [yard_a, yard_b], Pod.HOUSEHOLD, ""),
    ("grans", "Gran's house", [yard_a], Pod.HOUSEHOLD, ""),
    ("osei", "The Whitfield-Osei household", [yard_a], Pod.HOUSEHOLD, ""),
    ("rob", "Uncle Rob's place", [yard_a], Pod.HOUSEHOLD, ""),
    ("fn", "The Ferreira-Nakamuras", [yard_b], Pod.HOUSEHOLD, ""),
    ("vovo", "Vovó's house", [yard_b], Pod.HOUSEHOLD, ""),
    ("kai", "Kai & Marguerite", [yard_b], Pod.HOUSEHOLD, ""),
    (
        "camp",
        "Cousins' camp trip 2026",
        [yard_a],
        Pod.ADHOC,
        "What happens at camp stays at camp - but the photos come home.",
    ),
]
for key, name, yards, kind, rule in POD_SPEC:
    p, _ = Pod.objects.get_or_create(
        name=name, defaults={"kind": kind, "house_rule": rule, "seeded_by": SEEDED_BY}
    )
    p.kind = kind
    p.house_rule = rule
    p.save()
    p.yards.set(yards)
    pods[key] = p

# --------------------------------------------------------------------------- members
MEMBER_SPEC = [
    # key, display, kinship, pod, role, username, supervised, birthday(m,d), anniversary
    ("james", "James Whitfield", "Dad", "bridge", Member.INSTANCE_ADMIN, "james", False, (3, 14), (9, 2)),
    ("nora", "Nora Ferreira-Whitfield", "Mum", "bridge", Member.MEMBER, "nora", False, (7, 29), (9, 2)),
    ("teddy", "Teddy Whitfield", "Ted", "bridge", Member.SUPERVISED, None, True, (8, 3), None),
    ("gran", "Margaret Whitfield", "Gran", "grans", Member.MEMBER, None, False, (11, 12), None),
    ("rob", "Rob Whitfield", "Uncle Rob", "rob", Member.YARD_ADMIN, "rob", False, (1, 22), None),
    ("priya", "Priya Whitfield", None, "rob", Member.MEMBER, "priya", False, (5, 6), (6, 18)),
    ("ada", "Adaeze Whitfield-Osei", "Aunt Ada", "osei", Member.MEMBER, "ada", False, (4, 9), (4, 30)),
    ("emmanuel", "Emmanuel Whitfield-Osei", None, "osei", Member.MEMBER, "emmanuel", False, (2, 17), (4, 30)),
    ("marina", "Marina Ferreira-Nakamura", "Mãe", "fn", Member.YARD_ADMIN, "marina", False, (10, 1), None),
    ("kenji", "Kenji Ferreira-Nakamura", None, "fn", Member.MEMBER, "kenji", False, (12, 8), None),
    ("sofia", "Sofia Ferreira-Nakamura", "Sofi", "fn", Member.SUPERVISED, None, True, (7, 30), None),
    ("lucia", "Lucía Ferreira-Nakamura", None, "fn", Member.INSTANCE_ADMIN, "lucia", False, (6, 25), None),
    ("beatriz", "Beatriz Ferreira", "Vovó", "vovo", Member.MEMBER, None, False, (9, 19), None),
    ("tomas", "Tomás Ferreira", None, "vovo", Member.MEMBER, "tomas", False, (3, 31), None),
    ("kai", "Kai Nakamura", None, "kai", Member.MEMBER, "kai", False, (8, 11), (8, 1)),
    ("marguerite", "Marguerite Nakamura", None, "kai", Member.MEMBER, "marguerite", False, (2, 2), (8, 1)),
    ("wilhelmina", "Wilhelmina Constance Whitfield-Okonkwo", "Aunt Willa", "grans", Member.MEMBER, "willa", False, (5, 21), None),
]

members: dict[str, Member] = {}
for key, name, kin, podkey, role, username, sup, bday, anniv in MEMBER_SPEC:
    user = None
    if username:
        user, created = User.objects.get_or_create(username=username)
        user.set_password(PW)
        user.email = f"{username}@example.test"
        user.save()
    m, _ = Member.objects.get_or_create(display_name=name, defaults={"seeded_by": SEEDED_BY})
    m.user = user
    m.kinship_name = kin or ""
    m.role = role
    m.is_supervised = sup
    if bday:
        m.birthday_month, m.birthday_day = bday
        m.birthday_visibility = Member.POD if sup else Member.YARD
    if anniv:
        m.anniversary_month, m.anniversary_day = anniv
    m.contact_email = f"{key}@example.test"
    m.contact_email_visibility = Member.YARD if key in {"james", "marina", "rob"} else Member.HIDDEN
    m.phone = "+1 (402) 555-01%02d" % (len(members) + 10)
    m.phone_visibility = Member.POD if key in {"james", "gran", "marina"} else Member.HIDDEN
    m.address = "1412 Sycamore Lane, Omaha, NE 68132" if key in {"james", "gran"} else ""
    m.address_visibility = Member.POD if key in {"james", "gran"} else Member.HIDDEN
    m.save()
    PodMembership.objects.get_or_create(member=m, pod=pods[podkey])
    members[key] = m

members["teddy"].managing_parent = members["james"]
members["teddy"].save()
members["sofia"].managing_parent = members["marina"]
members["sofia"].save()

# Ad-hoc camp pod: owner plus a handful of cousins across households.
pods["camp"].owner = members["priya"]
pods["camp"].save()
for k in ("priya", "ada", "emmanuel", "teddy", "james"):
    PodMembership.objects.get_or_create(member=members[k], pod=pods["camp"])

for k in ("james", "nora", "rob", "marina", "ada"):
    NotificationPreference.objects.get_or_create(
        member=members[k], defaults={"notify_on_reply": k in {"james", "marina"}}
    )

# --------------------------------------------------------------------------- posts
def mkpost(author: str, podkey: str, body: str, yards, days: float, hours: float = 0) -> Post:
    p = Post.objects.create(author=members[author], pod=pods[podkey], body=body)
    if yards:
        p.audience_yards.set(yards)
    Post.objects.filter(pk=p.pk).update(created_at=ago(days, hours))
    p.refresh_from_db()
    return p


BOTH = [yard_a, yard_b]
A = [yard_a]
B = [yard_b]

p_long = mkpost(
    "james",
    "bridge",
    "We finally got the back fence finished this weekend. Rob came over Saturday with "
    "the good post-hole digger and we had the whole east run done before lunch.\n\n"
    "Teddy did every single one of the cap rails himself. He measured twice on all of "
    "them, which is more than I can say for his father.\n\n"
    "Gran, the gate is wide enough for the walker now - come and inspect it whenever "
    "you like. Sunday lunch is at ours this week either way.",
    A,
    1.2,
)
attach_photo(p_long, 2016, 1512, "garden", "The finished back fence, looking east toward the alley.")

p_link_img = mkpost(
    "nora",
    "bridge",
    "This is the bread recipe I have been going on about. It is genuinely foolproof.",
    BOTH,
    2.4,
)
lp_asset = MediaAsset(
    post=p_link_img, media_kind=MediaAsset.LINK_PREVIEW, content_type="image/jpeg", alt_text=""
)
lp_asset.image.save("lp-bread.jpg", ContentFile(photo(1200, 630, "kitchen")), save=False)
lp_asset.thumbnail.save("lpt-bread.jpg", ContentFile(photo(640, 336, "kitchen")), save=False)
lp_asset.save()
LinkPreview.objects.create(
    post=p_link_img,
    url="https://www.kingarthurbaking.com/recipes/no-knead-crusty-white-bread-recipe",
    title="No-Knead Crusty White Bread",
    description=(
        "A crusty, chewy, deeply flavoured loaf that needs no kneading and very little "
        "attention - just time. Makes two loaves; the dough keeps a week in the fridge."
    ),
    image_url="https://www.kingarthurbaking.com/og/no-knead.jpg",
    image_asset=lp_asset,
)

p_link_bare = mkpost(
    "rob",
    "rob",
    "Council posted the road-closure notice for the parade route. Worth a look before Saturday.",
    A,
    3.1,
)
LinkPreview.objects.create(
    post=p_link_bare,
    url="https://www.cityofomaha.example.gov/notices/2026/parade-route-closures-july",
    title="",
    description="",
)

p_gallery3 = mkpost(
    "ada", "osei", "Three from the allotment this morning. The tomatoes have gone berserk.", A, 4.0
)
for w, h, pal, alt in [
    (1800, 1350, "garden", "Tomato vines heavy with fruit against the shed."),
    (1350, 1800, "garden", "Emmanuel holding up the biggest tomato of the morning."),
    (1800, 1200, "porch", "Two full trugs on the allotment path."),
]:
    attach_photo(p_gallery3, w, h, pal, alt)

p_gallery5 = mkpost(
    "priya", "camp", "Camp dump, finally. Sorry it took a fortnight.", None, 6.5
)
for w, h, pal, alt in [
    (2048, 1365, "beach", "The whole group on the lakeshore at sunset."),
    (1365, 2048, "dusk", "Teddy on the end of the jetty."),
    (2048, 1365, "garden", "Breakfast at the long table under the trees."),
    (1600, 1600, "cake", "Somebody's birthday cake, sparklers and all."),
    (2560, 1097, "dusk", "Panorama across the water on the last night."),
]:
    attach_photo(p_gallery5, w, h, pal, alt)

p_portrait = mkpost(
    "marina", "fn", "Sofia's recital. She did not miss a note.", B, 2.0
)
attach_photo(p_portrait, 1365, 2048, "dusk", "Sofia at the piano under the stage light.")

p_video_pending = mkpost(
    "kenji", "fn", "Thirty seconds of the fireworks from the roof - uploading now.", B, 0.2
)
MediaAsset.objects.create(
    post=p_video_pending,
    media_kind=MediaAsset.VIDEO,
    content_type="video/mp4",
    transcode_status=MediaAsset.PENDING,
    alt_text="Fireworks from the roof.",
)

p_video_failed = mkpost(
    "tomas", "vovo", "Tried to put up the old wedding tape. It did not take.", B, 5.0
)
MediaAsset.objects.create(
    post=p_video_failed,
    media_kind=MediaAsset.VIDEO,
    content_type="video/mp4",
    transcode_status=MediaAsset.FAILED,
    alt_text="",
)

p_short = mkpost("gran", "grans", "Home safe. Thank you for the lift, Rob.", A, 0.6)
p_thread = mkpost(
    "marguerite",
    "kai",
    "Who is bringing what on Sunday? I have the pudding and absolutely nothing else.",
    B,
    1.6,
)
p_edited = mkpost(
    "emmanuel",
    "osei",
    "Moved kickoff to 4pm - the pitch was double booked. Same place, bring a jumper.",
    A,
    2.9,
)
Post.objects.filter(pk=p_edited.pk).update(edited_at=ago(2.7))

p_pod_only = mkpost(
    "james",
    "bridge",
    "Just us: Gran's birthday is the 12th. Thinking a lunch at ours rather than a party. "
    "Say if that is wrong.",
    None,
    3.4,
)
p_camp_only = mkpost(
    "teddy", "camp", "Can we do the same lake next year. Please.", None, 5.5
)
p_yardwide = mkpost(
    "lucia",
    "fn",
    "Both sides: we have set the date for the christening - 4 October, 11am, at St Mary's. "
    "Everyone is invited and there is no gift list.",
    BOTH,
    8.0,
)
p_takedown = mkpost(
    "kai", "kai", "Reposting the thing from the group chat - probably should not have.", B, 9.0
)
Post.objects.filter(pk=p_takedown.pk).update(
    deleted_at=ago(8.8), moderated_by=members["marina"].pk
)

p_quiet = mkpost("beatriz", "vovo", "Saudades de todos. Ligo no domingo.", B, 12.0)

# comments: a long thread, an email arrival, a moderated one
THREAD = [
    ("kai", "Pudding is covered then. I will do the potatoes.", 1.5, False),
    ("marina", "I can bring a salad and the good bread.", 1.4, False),
    ("kenji", "Chairs? We only have six.", 1.3, False),
    ("lucia", "We have four folding ones in the garage, I will bring them.", 1.2, False),
    ("beatriz", "Levo o arroz doce. Sempre levo o arroz doce.", 1.1, True),
    ("tomas", "She always brings the arroz doce and we would riot without it.", 1.0, False),
    ("marguerite", "That is everything then. 12:30, ours. Do not be late, Kenji.", 0.9, False),
    ("kenji", "One time.", 0.8, False),
]
for who, body, d, via in THREAD:
    c = Comment.objects.create(
        author=members[who], post=p_thread, body=body, via_email=via
    )
    Comment.objects.filter(pk=c.pk).update(created_at=ago(d))

for who, body, d, via in [
    ("gran", "It looks wonderful. I will come and inspect on Sunday.", 1.0, True),
    ("rob", "The cap rails are square. I checked. He is better at it than you.", 0.9, False),
    ("nora", "He has not stopped talking about it.", 0.7, False),
]:
    c = Comment.objects.create(author=members[who], post=p_long, body=body, via_email=via)
    Comment.objects.filter(pk=c.pk).update(created_at=ago(d))

c_mod = Comment.objects.create(
    author=members["kai"], post=p_yardwide, body="(removed)", via_email=False
)
Comment.objects.filter(pk=c_mod.pk).update(deleted_at=ago(7.5), moderated_by=members["lucia"].pk)

# reactions - several reactors on one post, one on another, none on a third
for who, kind in [
    ("gran", Reaction.HEART),
    ("rob", Reaction.WOW),
    ("nora", Reaction.HEART),
    ("ada", Reaction.LAUGH),
    ("priya", Reaction.HUG),
]:
    Reaction.objects.get_or_create(member=members[who], post=p_long, defaults={"kind": kind})
for who, kind in [("kenji", Reaction.HEART), ("beatriz", Reaction.HEART)]:
    Reaction.objects.get_or_create(member=members[who], post=p_portrait, defaults={"kind": kind})
Reaction.objects.get_or_create(member=members["james"], post=p_yardwide, defaults={"kind": Reaction.WOW})

# the unread boundary: James last looked two days ago
Member.objects.filter(pk=members["james"].pk).update(feed_last_seen_at=ago(2.0))
Member.objects.filter(pk=members["marina"].pk).update(feed_last_seen_at=ago(1.0))

# --------------------------------------------------------------------------- invites
invite_raw: dict[str, str] = {}


def mkinvite(key: str, podkey: str, *, days: float, max_uses: int, uses: int, revoked: bool, created_by: str) -> Invite:
    raw = secrets.token_urlsafe(32)
    inv = Invite.objects.create(
        pod=pods[podkey],
        token_digest=sha(raw),
        created_by=members[created_by],
        expires_at=NOW + dt.timedelta(days=days),
        max_uses=max_uses,
        use_count=uses,
        revoked_at=ago(1) if revoked else None,
    )
    invite_raw[key] = raw
    return inv


inv_live = mkinvite("live", "kai", days=12, max_uses=8, uses=0, revoked=False, created_by="james")
inv_soon = mkinvite("soon", "vovo", days=0.4, max_uses=8, uses=2, revoked=False, created_by="marina")
inv_full = mkinvite("full", "osei", days=9, max_uses=2, uses=2, revoked=False, created_by="james")
inv_revoked = mkinvite("revoked", "rob", days=6, max_uses=8, uses=1, revoked=True, created_by="rob")
inv_expired = mkinvite("expired", "grans", days=-3, max_uses=8, uses=1, revoked=False, created_by="james")
for inv, who in [(inv_full, "ada"), (inv_full, "emmanuel"), (inv_soon, "tomas"), (inv_revoked, "priya")]:
    InviteRedemption.objects.get_or_create(invite=inv, member=members[who])

# --------------------------------------------------------------------------- digests
for who, confirmed, enabled in [
    ("james", True, True),
    ("gran", True, True),
    ("rob", True, True),
    ("marina", True, True),
    ("beatriz", True, True),
    ("ada", False, True),
    ("kai", True, False),
]:
    m = members[who]
    DigestSubscription.objects.update_or_create(
        member=m,
        defaults={
            "address": f"{who}@example.test",
            "cadence": DigestSubscription.WEEKLY,
            "enabled": enabled,
            "confirmed_at": ago(20) if confirmed else None,
            "confirm_token_digest": sha(f"confirm-{who}"),
            "unsubscribe_token_digest": sha(f"unsub-{who}"),
        },
    )

digest_raw: dict[str, str] = {}
for who, yard, status, detail in [
    ("james", yard_a, DigestDelivery.HANDED_TO_RELAY, ""),
    ("gran", yard_a, DigestDelivery.HANDED_TO_RELAY, ""),
    ("rob", yard_a, DigestDelivery.REJECTED, "550 5.1.1 recipient rejected"),
    ("marina", yard_b, DigestDelivery.DSN_QUARANTINED, "mailbox full - held for review"),
    ("beatriz", yard_b, DigestDelivery.HANDED_TO_RELAY, ""),
]:
    issue = DigestIssue.objects.create(
        member=members[who],
        yard=yard,
        window_start=ago(7),
        window_end=NOW,
    )
    DigestIssue.objects.filter(pk=issue.pk).update(created_at=ago(0.4))
    DigestDelivery.objects.create(issue=issue, status=status, detail=detail)
    raw = secrets.token_urlsafe(32)
    DigestToken.objects.create(
        issue=issue,
        member=members[who],
        token_digest=sha(raw),
        minted_generation=members[who].token_generation,
        expires_at=NOW + dt.timedelta(days=10),
        first_used_at=ago(0.2) if who in {"james", "gran"} else None,
    )
    digest_raw[who] = raw

# --------------------------------------------------------------------------- quarantine
for reason, frm, body in [
    (
        InboundQuarantine.FROM_MISMATCH,
        "not-rob@elsewhere.test",
        "Sounds good, see you Saturday.\n\nOn Tue, 21 Jul 2026, Backyard wrote:",
    ),
    (
        InboundQuarantine.NO_SEPARATOR,
        "gran@example.test",
        "lovely photos thank you dear",
    ),
    (
        InboundQuarantine.RATE_LIMITED,
        "kenji@example.test",
        "and another thing",
    ),
]:
    InboundQuarantine.objects.create(reason=reason, from_header=frm, body_excerpt=body)

# --------------------------------------------------------------------------- metrics
monday = (NOW.date() - dt.timedelta(days=NOW.weekday()))
for i in range(6):
    ws = monday - dt.timedelta(weeks=i)
    for yard, n in [(yard_a, 11), (yard_b, 9)]:
        YardWeekMetrics.objects.update_or_create(
            yard=yard,
            week_start=ws,
            defaults={
                "member_count": n,
                "wcm": max(3, n - i - random.randint(0, 2)),
                "posting_breadth": max(1, 4 - (i // 2)),
                "posts_in_week": max(2, 11 - i * 2 + random.randint(0, 3)),
                "posts_responded": max(1, 8 - i * 2),
                "catch_up_members": max(2, n - i - 2),
                "digest_opens": max(1, 7 - i),
                "email_replies": max(0, 3 - i // 2),
            },
        )
    for key in ("bridge", "grans", "osei", "fn", "vovo", "kai"):
        PodWeekMetrics.objects.update_or_create(
            pod=pods[key], week_start=ws, defaults={"post_count": max(0, 4 - i + random.randint(-1, 1))}
        )
    for key, m in members.items():
        MemberWeekPresence.objects.update_or_create(
            member=m, week_start=ws, defaults={"present": random.random() > 0.25 - (i * 0.02)}
        )

# --------------------------------------------------------------------------- elder tokens
elder_raw: dict[str, str] = {}
for who in ("gran", "beatriz"):
    raw = secrets.token_urlsafe(32)
    ElderToken.objects.update_or_create(
        member=members[who],
        defaults={
            "token_digest": sha(raw),
            "minted_generation": members[who].token_generation,
            "expires_at": None,
        },
    )
    elder_raw[who] = raw

# --------------------------------------------------------------------------- manifest
manifest = {
    "password": PW,
    "logins": {
        "instance_admin": "james",
        "second_admin": "lucia",
        "yard_admin": "rob",
        "member": "nora",
        "member_other_side": "kenji",
        "member_single_yard": "ada",
    },
    "users": sorted(u.username for u in User.objects.all()),
    "yards": {y.slug: y.name for y in Yard.objects.all()},
    "member_ids": {k: m.pk for k, m in members.items()},
    "pod_ids": {k: p.pk for k, p in pods.items()},
    "post_ids": {
        "long_with_photo": p_long.pk,
        "link_with_image": p_link_img.pk,
        "link_bare": p_link_bare.pk,
        "gallery3": p_gallery3.pk,
        "gallery5": p_gallery5.pk,
        "portrait": p_portrait.pk,
        "video_pending": p_video_pending.pk,
        "video_failed": p_video_failed.pk,
        "short": p_short.pk,
        "long_thread": p_thread.pk,
        "edited": p_edited.pk,
        "pod_only": p_pod_only.pk,
        "camp_only": p_camp_only.pk,
        "yardwide": p_yardwide.pk,
        "quiet": p_quiet.pk,
    },
    "invite_tokens": invite_raw,
    "digest_tokens": digest_raw,
    "elder_tokens": elder_raw,
    "counts": {
        "members": Member.objects.count(),
        "posts": Post.objects.filter(deleted_at__isnull=True).count(),
        "comments": Comment.objects.filter(deleted_at__isnull=True).count(),
        "media": MediaAsset.objects.count(),
        "invites": Invite.objects.count(),
    },
}
with open("/data/seed_manifest.json", "w") as fh:
    json.dump(manifest, fh, indent=2)

print("SEED OK")
print(json.dumps(manifest["counts"], indent=2))
