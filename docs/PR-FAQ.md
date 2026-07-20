# PR-FAQ (working backwards)

Status: internal working-backwards artifact, written 2026-07-20 at the start of Phase 0. The press release below describes a FUTURE launch and is not a real announcement. It exists to force positioning and scope decisions before code.

---

## Press release (draft, dated for the future v1.0 launch)

**Backyard 1.0: a social network the size of your family**

Backyard 1.0 is out today: a free, open-source, self-hosted social network built for one specific community, your extended family, and deliberately nothing bigger.

Backyard replaces the group text nobody can find anything in and the platform feed nobody trusts. Every household is a pod. Each side of a family is a yard with its own shared backyard feed. Post a link at 1am and nobody's phone buzzes; everyone catches up whenever they want. The feed is chronological and it ends.

The relative without a smartphone is a first-class user. Grandparents get a tap-to-open link with no account, no password, and no app store, and they can reply by email or from a photo frame display. In published research, a 21-week in-home trial of a one-way "just show grandma the photos" display failed until its redesign let grandma post back (receipts in [docs/research](research/2026-07-19-research-brief.md)). Backyard is two-way everywhere.

There are no ads, no tracking, no algorithm, and no engagement mechanics. That is structural, not policy: your family runs Backyard on its own server, so there is no company in the room. Deployment is one command; if it takes more, that is a bug. Everything exports. The AGPL license keeps the code open: anyone who runs a modified Backyard as a service has to share their source, and the version your family runs stays free forever.

Backyard is available today on GitHub, TrueNAS SCALE, Umbrel, and Unraid, with a live demo at backyard.family.

---

## External FAQ (what real people will ask)

**Why not just a group chat?**
Group chats are interruptions with amnesia. Every message pings everyone now, and anything older than a day is buried where nobody will scroll. Backyard is the opposite: nothing interrupts, everything keeps, and you catch up on your own schedule.

**Why not a private Facebook group or Instagram close friends?**
You don't control the room. The algorithm decides what your family sees, the platform monetizes the attention, and the account your memories live in can be locked, sunset, or enshittified at any time. Backyard is your server, your rules, your archive.

**Why not FamilyAlbum or Tinybeans?**
Those are parent-to-grandparent baby-photo pipes, and they are good at that. Backyard is for the whole graph: teens, uncles, both grandmothers, cousins, across multiple households, with links and updates as well as photos. And it is free software; no subscription holds your memories hostage.

**My family is on both sides of a divorce / my in-laws should not see everything. Does everyone get thrown together?**
No. Separateness is a feature. Yards keep whole branches of a family apart (they never see each other), pods scope every post, and each post can be aimed precisely. Nothing forces togetherness that doesn't exist in real life.

**What about the relative with no smartphone?**
They tap a link, or they get an email digest, or a photo frame on the shelf shows the week's posts. They can reply by email.

**Who moderates it? What are the content rules?**
There are none in the software, on purpose. A 40-person family doesn't need a trust-and-safety department; it needs rooms. Pod owners can write one human sentence of house rules. Individuals can mute or leave quietly. Admins can remove people. That is the whole system, and it is the same one Thanksgiving dinner runs on.

**What does it cost?**
The software is free (AGPL-3.0). Hosting a family costs roughly $5 a month on a small VPS, or nothing on hardware you already own.

**What happens when the maintainer gets bored / hit by a bus?**
Your instance keeps running; it never depended on us. Your data exports completely at any time. The code is AGPL, so anyone can continue it. Compare that to any startup's shutdown notice.

**Is my family's data encrypted?**
In transit, yes. At rest, it lives on a server your family controls, which is the actual privacy model: the risk Backyard exists to remove is the platform. End-to-end encryption is an explicit non-goal for v1. It would break the email digests, token links, and frame display that make low-tech relatives first-class. It becomes a real roadmap question after that.

## Internal FAQ (the hard questions)

**Togethera had roughly 65,000 users who loved it and still died. Why does Backyard live?**
Togethera died of a business model: revenue had to cover a company. Backyard has no company to feed. The founder is the first user with a permanent personal need, the marginal cost of the software existing is one hobby server, and OSS distribution (directories, NAS stores) is free. Survival requires discipline, not revenue. That is also honestly the risk: single-maintainer decay killed most OSS predecessors. The definition of done answers it with boring operations, migrations that never break archives, and public kill criteria instead of silent rot.

**Why build instead of forking zusam or cousins-matter?**
The gap is the combination no fork contains: pods-and-yards privacy, the no-login elder path, and grandparent-grade onboarding in one product. None of the projects in the [OSS landscape sweep](research/2026-07-19-github-oss-landscape.md) has all three, and no fork removes that core work; forking buys the parts that were never hard.

**Why is there no native iOS/Android app in v1?**
App stores are a gatekeeper tax on exactly the users we serve (mixed devices, low-tech relatives). An installable PWA (push opt-in, quiet by default) is our bet for the median user, and adoption data tests it; token links and email cover the edge. Native apps are a post-v1 question that adoption data gets to answer.

**Why AGPL and not MIT?**
The product's identity is "this cannot be enclosed." AGPL makes that a legal property, not a promise. Full reasoning in ADR-000.

**What kills this project?**
Public kill criteria live in the assumption map: if the founding household misses the adoption KPI after two design iterations across two measurement cycles, feature work stops for adoption discovery. If it still fails, the project archives honestly with a written post-mortem.
