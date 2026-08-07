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
Wipe:  `manage.py wipe_demo_data --dry-run`, then `--yes`. NOT from this file.

Everything created here is stamped `seeded_by="demo"`, which is what makes the wipe
possible to scope. `BACKYARD_DEMO_WIPE=1` used to live in this script and ran
`Pod.objects.all().delete()` — every pod on the instance, and by cascade every post,
comment, photograph, reaction, invite and membership. Measured against a database holding
one real family and one fixture family: pods 2->0, members 4->0, posts 2->0, comments 2->0.
The real family did not survive, and neither did the real elder.

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

from core import demo_data, elder_tokens, media, supervised
from core.demo_data import SEED_MARKER as SEEDED_BY
from core.models import Comment, Member, Pod, PodMembership, Post, Reaction, Yard

U = get_user_model()
# Generated, never stored in the repository. Printed at the end of a successful run, which
# is the only place it exists — re-run the seed if you lose it.
PW = os.environ.get("BACKYARD_DEMO_PASSWORD") or secrets.token_urlsafe(12)

if os.environ.get("BACKYARD_DEMO_WIPE") == "1":
    raise SystemExit(
        "BACKYARD_DEMO_WIPE has been removed. It ran `Pod.objects.all().delete()` — every "
        "pod on the instance, not just the demo ones.\n\n"
        "Use:  manage.py wipe_demo_data --dry-run     (read the counts)\n"
        "then: manage.py wipe_demo_data --yes\n\n"
        "That only touches rows stamped seeded_by='demo'. If this instance was seeded "
        "before the marker existed, its rows are unmarked and the command will say so "
        "rather than guessing."
    )

# Clear the PREVIOUS run of this seed. Scoped by the marker, so re-seeding a live instance
# is not a way to destroy the family it is meant to sit beside. This is the same code path
# the wipe command uses, so there is one implementation and no second one to drift.
demo_data.wipe(SEEDED_BY)

moms = Yard.objects.create(name="Mom's side", slug="moms-side", seeded_by=SEEDED_BY)
dads = Yard.objects.create(name="Dad's side", slug="dads-side", seeded_by=SEEDED_BY)


def pod(name, yards):
    p = Pod.objects.create(name=name, seeded_by=SEEDED_BY)
    p.yards.set(yards)
    return p


# the bridging household belongs to BOTH sides
ours = pod("Our house", [moms, dads])
nanas = pod("Nana's house", [moms])
cous = pod("The Cousins", [moms])
dadsfam = pod("The Ferraras", [dads])


def member(name, pod_, *, login=None, kin="", role=Member.MEMBER):
    u = U.objects.create_user(username=login, password=PW) if login else None
    m = Member.objects.create(
        display_name=name, user=u, kinship_name=kin, role=role, seeded_by=SEEDED_BY
    )
    PodMembership.objects.create(member=m, pod=pod_)
    return m


# The OPERATOR's own account — whoever runs this instance. Deliberately NOT stamped
# `seeded_by`: the wipe must leave it and its pod membership alone, or clearing the demo
# family locks them out of the product — a member in no pod resolves nobody, including
# themselves, and `/setup/` is closed for good once a superuser exists. Re-running the seed
# re-attaches them to the bridging household.
#
# Selected by `is_superuser`, never by username. Keying this to the literal "james" had two
# edges on anybody else's instance, and they are the same two the old wipe had when it
# deleted auth accounts called "sam" and "dave":
#
#   * no such user -> the seed CREATED one, gave it INSTANCE_ADMIN, left it unmarked so no
#     wipe would ever remove it, and printed its password. A permanent admin account with a
#     published credential, on a stranger's family instance.
#   * such a user exists but is an ordinary relative who happens to be called James -> the
#     seed promotes THEM to instance admin. A name is not an identity.
#
# The trailing "your own account keeps the password it already had" was false in the first
# case, which is the one where it mattered.
_u = U.objects.filter(is_superuser=True).order_by("pk").first()
_minted_operator = _u is None
if _u is None:
    # No superuser at all: a bare database — a test, or a drill box — where the first-run
    # wizard has not run. Creating one here is the only way the seed can produce a coherent
    # instance, so it is done loudly rather than silently, and never on a populated box.
    if U.objects.exists():
        raise SystemExit(
            "Refusing to seed: this database has user accounts but no superuser, so there "
            "is no operator to attach the demo family to. Run `manage.py createsuperuser` "
            "(or open /setup/) first — the seed will not mint an admin account on an "
            "instance that already belongs to somebody."
        )
    _u = U.objects.create_superuser(
        username=os.environ.get("BACKYARD_SEED_OPERATOR", "operator"), password=PW
    )
operator_name = os.environ.get("BACKYARD_SEED_OPERATOR_NAME") or _u.username
james, _ = Member.objects.get_or_create(
    user=_u, defaults={"display_name": operator_name, "role": Member.INSTANCE_ADMIN}
)
# `defaults` only apply on CREATE, so re-running the seed against an existing Member left
# whatever role that row already had. QA depends on the founder being an instance admin —
# half these steps are admin-only — so it is asserted every run rather than assumed.
if james.role != Member.INSTANCE_ADMIN:
    Member.objects.filter(pk=james.pk).update(role=Member.INSTANCE_ADMIN)
    james.refresh_from_db()

# A household of his own, OUTSIDE the fixture data, if he does not already have one.
#
# Everything above belongs to the demo family and disappears with it. If the founder's only
# pod were one of those, clearing the demo would leave him in no pod — and a member in no
# pod belongs to no yard and resolves nobody, including themselves. `demo_data.wipe` now
# refuses rather than doing that to anyone, so without this the wipe would simply never run.
#
# On a real instance the first-run wizard already made this and `get_or_create` finds it;
# on a bare database (a test, a fresh drill box) this stands in for it. Unmarked, so it
# survives every wipe.
if not PodMembership.objects.filter(member=james).exists():
    own_yard, _ = Yard.objects.get_or_create(slug="home", defaults={"name": "Home"})
    own_pod = Pod.objects.create(name="James's house")
    own_pod.yards.set([own_yard])
    PodMembership.objects.create(member=james, pod=own_pod)

# ...and into the bridging household as well, which is what makes QA meaningful: it is the
# pod that holds the photographs and spans both sides.
PodMembership.objects.get_or_create(member=james, pod=ours)
priya = member("Priya Whitfield", ours, login="priya")
nana = member("Rose Whitfield", nanas, kin="Nana")  # elder, no login
sam = member("Sam Whitfield", cous, login="sam")  # mom's side only
dave = member("Dave Ferrara", dadsfam, login="dave")  # dad's side only
kid = supervised.create_supervised_member(parent=priya, display_name="Ollie", pod=ours)
# The supervised path builds the Member itself, so the marker goes on afterwards. Without
# this the child is unmarked and survives the wipe as an orphan whose parent is gone — and
# a supervised member has `user = NULL`, so nothing else identifies them either.
Member.objects.filter(pk=kid.pk).update(seeded_by=SEEDED_BY)
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
# Authored by a SEEDED member, not by the founder. The founder is deliberately unmarked
# (the wipe must leave him standing), so a post of his inside a marked pod is real content
# in fixture territory — and `demo_data` now refuses the whole wipe rather than deleting
# somebody's photographs on a guess. Keeping the seed self-consistently wipeable means its
# posts belong to its own people. Anything the founder writes during QA is his, and the
# wipe will say so.
p2 = post(
    priya,
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
    priya,
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
for m in (nana, sam, priya):
    Reaction.objects.get_or_create(post=p1, member=m, kind=Reaction.HEART)
Reaction.objects.get_or_create(post=p2, member=nana, kind=Reaction.HEART)

print(f"ELDER_TOKEN={elder_tokens.mint(nana)}")
print(
    f"SEEDED members={Member.objects.count()} "
    f"pods={Pod.objects.count()} posts={Post.objects.count()}"
)
# Last line, and the only copy. Every seeded login shares it.
#
# Your own account keeps the password it already had — unless this run had no superuser to
# attach to and minted one, which is said plainly rather than left to be inferred from a
# comment that was written when the founder's account always existed.
if _minted_operator:
    print(
        f"CREATED SUPERUSER {_u.username!r} — no superuser existed on this database. "
        "It shares the demo password below and is NOT removed by `wipe_demo_data`. "
        "Change it before this instance is used by anyone."
    )
print(f"DEMO_PASSWORD={PW}")
