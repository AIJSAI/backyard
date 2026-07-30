# Backyard docs

Ninety-odd files live under `docs/`, and most of them are a **working record** rather than
documentation. This page exists so you do not have to guess which is which.

Three doors:

| If you want to… | Start here |
|---|---|
| **run it** | [self-host.md](runbooks/self-host.md) → [backup-restore.md](runbooks/backup-restore.md) → [handover.md](runbooks/handover.md) |
| **understand why it is built this way** | the four pictures below, then [principles.md](principles.md), [ADRs](adr/), [threat-model.md](security/threat-model.md) |
| **see how it was actually built** | [PATH-TO-100.md](PATH-TO-100.md), [receipts/](receipts/), [audits/](audits/) |

---

## The four pictures

### 1. Pods and yards — the whole data model

This is the one idea you have to hold. Everything else follows from it.

```mermaid
graph TD
    MOMS["<b>Mom's side</b><br/>a yard"]
    DADS["<b>Dad's side</b><br/>a yard"]

    MOMS <-.->|"❌ never see each other,<br/>and cannot learn the other exists"| DADS

    MOMS --- NANA["Nana's house<br/><i>a pod</i>"]
    MOMS --- COUS["The Cousins<br/><i>a pod</i>"]
    DADS --- FERR["The Ferraras<br/><i>a pod</i>"]

    MOMS --- OURS
    DADS --- OURS
    OURS["<b>Our house</b><br/><i>one pod, in BOTH yards</i>"]

    style MOMS fill:#1d4e3a,stroke:#0d2b20,color:#ffffff
    style DADS fill:#1d4e3a,stroke:#0d2b20,color:#ffffff
    style OURS fill:#c9a227,stroke:#8a6f13,color:#1a1a1a
```

- A **pod** is a household. A **yard** is one side of the family.
- A household in both yards (yours, probably) posts to either side, or to just its own pod.
- **The sides never fuse.** A member of Dad's side cannot see Mom's side, cannot enumerate it,
  and cannot tell a "not yours" 404 from a "does not exist" 404. That is one query,
  `scoping.visible_posts`, and every surface goes through it — feed, search, digest, media,
  the elder page. One implementation, so there is no second one to drift.

### 2. How a grandparent gets in without an account

The most-questioned design decision in the project. She taps one link. There is no password,
no app store, and nothing to install.

```mermaid
sequenceDiagram
    participant N as Nana
    participant A as Backyard
    participant Admin as Whoever set it up

    Admin->>A: Members → Nana → Elder link
    A-->>Admin: one URL, shown once
    Admin->>N: hands it over in person, or prints the QR

    N->>A: taps the link (/t/<token>)
    A->>A: hash the token, check it against<br/>Nana's current generation
    A-->>N: sets an httpOnly cookie,<br/>redirects to a CLEAN url
    Note over N,A: the token is now out of the address bar,<br/>out of history, out of screenshots

    N->>A: reads the feed, taps ❤️, replies by email
    Note over N,A: no password, ever

    Admin->>A: Regenerate (lost phone, forwarded link)
    A->>A: bump Nana's generation
    Note over A: every link, session, digest deep-link<br/>and media URL she ever had dies at once
```

The honest trade-off: **a link that just works is a link that can be forwarded.** That is
argued out and accepted in [ADR-003](adr/ADR-003-token-links.md), and the counterweight is
that one click kills everything derived from it.

### 3. What happens to a photograph

Most of this exists because the photos are of children.

```mermaid
flowchart TD
    P["📱 a photo on a phone"] --> R["resized in the browser<br/><i>before it ever leaves the phone</i>"]
    R --> S["metadata stripped<br/><i>GPS discarded, never written down</i>"]
    S --> E["re-encoded<br/><i>anything that will not decode is rejected</i>"]
    E --> D["derivatives made<br/><i>thumbnail, poster frame</i>"]
    D --> ST[("the volume")]

    ST --> G{"checked on<br/><b>every single request</b>"}
    G -->|"in your audience"| OK["✅ the bytes"]
    G -->|"not in your audience"| NO["❌ 404 — identical to<br/>'no such photo'"]

    ST --> DEL["someone deletes it"]
    DEL --> HD["the original <b>and every derivative</b> go"]
    HD --> SENT["what it cannot recall:<br/><i>a copy already in a sent email.</i><br/>The delete screen says so."]

    style G fill:#1d4e3a,stroke:#0d2b20,color:#ffffff
    style SENT fill:#f4ecd8,stroke:#8a6f13,color:#1a1a1a
```

- **GPS is stripped at ingest and never written down** — a trade of archive fidelity for
  safety, made deliberately.
- Every byte, including thumbnails and poster frames, goes through **one** access-checked path.
  A static route that skipped it would be the whole hole, which is why the isolation suite
  enumerates asset types.
- Delete removes derivatives too. What it cannot recall is a copy already sitting in a sent
  email, and [the delete screen says so](security/threat-model.md) rather than implying otherwise.

### 4. One audience query, five surfaces

The structural rule that keeps the promise above true.

```mermaid
graph LR
    F["web feed"] --> Q
    DG["weekly digest<br/><i>a batch job</i>"] --> Q
    EL["elder page"] --> Q
    ME["media serving"] --> Q
    VC["vCard export"] --> Q

    Q["<b>scoping.visible_*</b><br/>the ONE audience query"]
    Q --> DB[("Postgres")]

    style Q fill:#1d4e3a,stroke:#0d2b20,color:#fff
```

A batch job that reimplemented "who may see this" would drift from the feed within a month,
and email has no recall, no access log and no 404. So the digest builder consumes the same
code path as the web feed, per recipient, evaluated at send time — deleted posts, narrowed
audiences and removed members never ship. The vCard export was the newest surface to be wired
in, and it takes an already-filtered object rather than a database row, so it *cannot* reach a
field the viewer is not scoped for.

---

## Everything else, by kind

**Runbooks — operating a real instance**
[self-host](runbooks/self-host.md) · [backup-restore](runbooks/backup-restore.md) ·
[the succession sheet](runbooks/backup-recovery-sheet.md) · [handover](runbooks/handover.md) ·
[shutdown](runbooks/shutdown.md) · [setting up your side](runbooks/setting-up-your-side.md) ·
[founder QA script](runbooks/founder-qa.md) · [live repro](runbooks/live-repro.md) ·
[transcode measurement](runbooks/measure-transcode.md)

**Decisions** — [ADR-000 … ADR-005](adr/), plus
[the permission matrix](security/permission-matrix.md) and
[the threat model](security/threat-model.md).

**Product** — [PR-FAQ](PR-FAQ.md) · [principles](principles.md) ·
[metrics](metrics.md) · [assumptions and their kill criteria](assumptions.md) ·
[story map](story-map.md) · [the family privacy note](family-privacy-note.md)

**The working record** — [PATH-TO-100](PATH-TO-100.md) (the definition of done; a box needs an
evidence link and CI enforces it) · [receipts](receipts/) · [audits](audits/) ·
[research](research/) · [design](design/) · [retro](retro/) · [wave plan](wave-plan.md)

**Internal** — [RESUME-HERE](RESUME-HERE.md) is a handoff note for whoever picks the work up
next, not documentation. It is in the open because the project is built in the open.
