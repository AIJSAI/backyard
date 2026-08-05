"""Seed (or wipe) a small demo family, for founder QA only.

NOT part of the application and never imported by it. This exists because QA against
the real instance was giving FALSE NEGATIVES: every elder token belonged to a member
whose pods held no photos, so "can Nana see a photograph?" answered no for a data
reason, not a code reason — and both admin logins sat on the same side of the family,
so the yard-isolation boundary could not be crossed to test it.

The shape is deliberate, not decorative:
  * two yards, so S-202 isolation is exercisable at all;
  * a household that BRIDGES both, the case where isolation gets interesting;
  * an elder in the same pod as the photos, so the elder path is honestly testable;
  * a supervised child, for the parent-managed profile path;
  * replies and reactions, so threads are not empty.

Run:   docker compose exec -T web sh -c 'DJANGO_SECRET_KEY=$(cat /data/secret_key) \
         python manage.py shell' < scripts/demo_seed.py
Wipe:  same, with BACKYARD_DEMO_WIPE=1 in the environment.

EVERY account below is disposable and shares one password, **minted fresh on each run and
printed once at the end**. Set BACKYARD_DEMO_PASSWORD to choose your own.

This used to be a hardcoded literal, and the comment beside it said "wiped before any
share" — a promise about the future guarding a credential that worked, that minute, on the
live internet-reachable instance. Anyone reading the public repository could sign in as a
demo member. The comment was doing the security work, and a comment is not a guard: gitleaks
scanned 287 commits and found nothing, because a human-chosen password assigned to `PW` does
not look like a provider key. `test_no_hardcoded_demo_credentials.py` is the actual guard now.

Wipe before the instance is shared with anyone real, regardless.
"""

import datetime
import io
import os
import secrets

from django.contrib.auth import get_user_model
from django.utils import timezone
from PIL import Image, ImageDraw

from core import elder_tokens, media, supervised
from core.models import Comment, Member, Pod, PodMembership, Post, Reaction, Yard

U = get_user_model()
# Generated, never stored in the repository. Printed at the end of a successful run, which
# is the only place it exists — re-run the seed if you lose it.
PW = os.environ.get("BACKYARD_DEMO_PASSWORD") or secrets.token_urlsafe(12)

if os.environ.get("BACKYARD_DEMO_WIPE") == "1":
    Yard.objects.filter(slug__in=["moms-side", "dads-side"]).delete()
    Pod.objects.all().delete()
    Member.objects.exclude(user__username="james").delete()
    U.objects.filter(username__in=["priya", "sam", "dave"]).delete()
    print("DEMO DATA WIPED")
    raise SystemExit(0)

# wipe prior seed
Yard.objects.filter(slug__in=["moms-side", "dads-side"]).delete()
Pod.objects.all().delete()
Member.objects.all().delete()
U.objects.filter(username__in=["priya", "sam", "dave", "auntmay", "uncledave"]).delete()

moms = Yard.objects.create(name="Mom's side", slug="moms-side")
dads = Yard.objects.create(name="Dad's side", slug="dads-side")


def pod(name, yards):
    p = Pod.objects.create(name=name)
    p.yards.set(yards)
    return p


# the bridging household belongs to BOTH sides
ours = pod("Our house", [moms, dads])
nanas = pod("Nana's house", [moms])
cous = pod("The Cousins", [moms])
dadsfam = pod("The Ferraras", [dads])


def member(name, pod_, *, login=None, kin="", role=Member.MEMBER):
    u = U.objects.create_user(username=login, password=PW) if login else None
    m = Member.objects.create(display_name=name, user=u, kinship_name=kin, role=role)
    PodMembership.objects.create(member=m, pod=pod_)
    return m


# Your real account is preserved — password unchanged. Only the family AROUND it is seeded.
_u = U.objects.filter(username="james").first() or U.objects.create_user(
    username="james", password=PW
)
james = Member.objects.create(display_name="James Shehan", user=_u, role=Member.INSTANCE_ADMIN)
PodMembership.objects.create(member=james, pod=ours)
priya = member("Priya Whitfield", ours, login="priya")
nana = member("Rose Whitfield", nanas, kin="Nana")  # elder, no login
sam = member("Sam Whitfield", cous, login="sam")  # mom's side only
dave = member("Dave Ferrara", dadsfam, login="dave")  # dad's side only
kid = supervised.create_supervised_member(parent=priya, display_name="Ollie", pod=ours)
PodMembership.objects.get_or_create(member=nana, pod=ours)  # Nana sees the family photos


def photo(w=1200, h=800, seed=0):
    img = Image.new("RGB", (w, h), (34 + seed * 17 % 90, 92, 70))
    d = ImageDraw.Draw(img)
    for i in range(6):
        d.ellipse([80 * i, 60 * i, 80 * i + 320, 60 * i + 240], outline=(240, 240, 230), width=6)
    b = io.BytesIO()
    img.save(b, "JPEG", quality=88)
    return b.getvalue()


def post(author, pod_, body, *, yards=None, photos=0, days_ago=0):
    p = Post.objects.create(author=author, pod=pod_, body=body)
    if yards:
        p.audience_yards.set(yards)
    for i in range(photos):
        media.ingest_photo(post=p, raw=photo(seed=i))
    if days_ago:
        Post.objects.filter(pk=p.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=days_ago)
        )
    return p


p1 = post(
    priya,
    ours,
    "Camp dump, finally. She caught the biggest fish of the week.",
    yards=[moms, dads],
    photos=3,
    days_ago=1,
)
p2 = post(
    james,
    ours,
    "Ollie lost his first tooth. He is extremely pleased about the economics.",
    yards=[moms],
    photos=1,
    days_ago=2,
)
p3 = post(
    sam, cous, "Cousins brunch Sunday — our place, 11ish. Bring nothing, I mean it.", days_ago=3
)
p4 = post(
    dave, dadsfam, "The Ferrara side reunion is booked for August 16th.", yards=[dads], days_ago=4
)
p5 = post(
    nana,
    nanas,
    "Thank you all for the birthday calls. My phone has never been so busy.",
    days_ago=5,
)
p6 = post(
    james,
    ours,
    "Found this and thought of Dad: https://example.com/vintage-tractors",
    yards=[dads],
    days_ago=6,
)
p7 = post(priya, ours, "Ollie's school concert is Thursday at 6.", days_ago=7)

Comment.objects.create(
    post=p1, author=nana, body="What a catch! She looks so pleased with herself."
)
Comment.objects.create(post=p1, author=sam, body="That is a proper fish. Well done Rose.")
Comment.objects.create(
    post=p2, author=nana, body="Tell him the tooth fairy is inflation-adjusted these days."
)
for m in (nana, sam, james):
    Reaction.objects.get_or_create(post=p1, member=m, kind=Reaction.HEART)
Reaction.objects.get_or_create(post=p2, member=nana, kind=Reaction.HEART)

print(f"ELDER_TOKEN={elder_tokens.mint(nana)}")
print(
    f"SEEDED members={Member.objects.count()} "
    f"pods={Pod.objects.count()} posts={Post.objects.count()}"
)
# Last line, and the only copy. Every seeded login shares it; your own account keeps the
# password it already had.
print(f"DEMO_PASSWORD={PW}")
