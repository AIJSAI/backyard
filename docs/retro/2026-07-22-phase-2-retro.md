# Backyard Phase 2 — full-angle retrospective + Phase 3 work map

Date: 2026-07-22. Phase 2 ("v1 built wave by wave, every wave proven live") closed at
**34/34 v1 stories tested**. This retro was produced by a 9-agent, evidence-grounded
workflow (6 lenses → completeness critic + devil's advocate → reconciled planner), every
claim checked against the repo, receipts, git history, and threat model.

---

## 0. The honest headline (read this first)

**Phase 2 delivered the LEGIT half of "LEGIT + ALIVE." The ALIVE half is 0% started.**

- 34/34 v1 stories are `tested`; **zero are `passing`** — and `passing` (the goal's own
  criterion) requires receipts against a *persistent* live instance. Every wave's
  live-repro ran on a throwaway `docker compose up … down -v` stack destroyed the moment
  the receipt was written. **The app has never run longer than one scripted session.**
- The project's own founding research is blunt: predecessors died of **adoption, scope,
  mobile, and distribution — "not engineering"** (`docs/research/…`), and A-HABIT (will
  the founding household form a weekly habit) is the *sole Highest-ranked* assumption —
  sitting at **0% tested because there are zero real users.** Engineering does not appear
  in the risk table at all.
- So "34/34 tested, every wave proven live" is honest for what it says, but it is **not**
  "the rollout can be executed" and **not** "the project is de-risked." The two literal
  first moves of the seed-ally rollout have no UI (below), and the one risk that can
  actually kill the project has had zero investment.

**The engineering is genuinely excellent. It is also, so far, a rigorous answer to the
axis the research says is not where these projects die.** The correct next unit of work
is not more hardening — it is wiring the rollout and standing up one real, persistent
instance in front of the family.

---

## 1. What went well (durable strengths, verified)

- **One honestly single-sourced audience query.** Reads reduce to `scoping.visible_posts`;
  comments, reactions, and media have no audience of their own and inherit it structurally
  (`post__in=visible_posts`), so there is *provably* no second audience path to drift
  (TM-2 realized in code). This held across feed, digest, reply-by-email, and media.
- **Seam discipline paid off concretely.** The SSRF-hardened fetcher is ONE gate
  (`_fetch_once` with per-caller `accept`/`content_type_ok`/`max_bytes`); the S-301
  og:image re-host inherited the *entire* SSRF hardening for free because the fetcher was
  refactored to share, not copied. `handover.py` is shared by the elder and invite flows.
- **The write-authorization model is a small, correct, separate layer** (`permissions.py`):
  the T-AUTH-G2 yard-subset rule, a *non-vacuous* empty-set guard, no privilege inversion,
  and the analysis-loop finding that pod owners must NOT issue invites — all in code and
  tested.
- **The digest is confined by structure, not vigilance:** a closed typed-block union with a
  build-time validator PLUS a CI drift-guard that bans any data-access token in `digest.py`
  and self-tests each banned pattern.
- **The send saga is sophisticated and correct** for an irreversible external effect:
  per-recipient isolation, per-(member,yard) window anchoring, savepoint-wrapped token
  rotation so a refused send never orphans a live credential.
- **Threat-model-before-code, made binding.** Every TM-/TS- row names the story acceptance
  test that proves it, which turned the per-increment security reviews into an enforceable
  checklist.

## 2. What the rigor caught (why the process earned its keep)

The unifying failure mode across Phase 2 was **FALSE-GREEN** — a gate/test/claim that
passed on a fixture too small or synthetic to be representative. Each was caught only by an
*independent non-vacuity check*, never by the author's own tests:

| False-green | Caught by |
|---|---|
| `RLIMIT_AS=2GB` passed every 320×240 clip, would have failed **every real 1080p** transcode | the `measure_transcode` harness on realistic HD input (A/B confirmed) |
| Inbound tests hand-set `envelope_recipient`, which Resend's handler **never emits** (dead trust control) | security-reviewer grepping the *installed* anymail source + a live round-trip |
| "Client-side resize" marked **built with an empty static dir** | per-acceptance-criterion close-check |
| gitleaks gate was **vacuous** (planted key on the tool's allowlist) | the gate's own planted-secret self-test, on first CI run |
| "2nd Resend team is free" (absence-of-evidence inference shipped high-confidence) | James's create-team screenshot (the buy FLOW, not the settings doc) |

**Lesson:** the independent adversarial layer (security-reviewer, close-rigor, realistic
input, hand-counting the primary source) is the *highest-yield* layer, not overhead — it is
the last thing to cut. Every drift-guard must ship its own both-sides self-test in the same
change, or it is a false-green waiting to happen.

## 3. Risks & debt carried into Phase 3 (severity-ranked, corrections applied)

- **[HIGH] The seed-ally rollout cannot be *started* in-product.** The two literal first
  moves have **no UI**: appointing a delegate (`can_assign_role` is enforced + tested but
  has **zero non-test callers**) and creating the second family side (`Yard` creation
  exists only inside the first-run wizard, `views.py:89`, unreachable post-setup). New-elder
  onboarding also serves *existing* members only. James can only do these at a Django shell.
- **[HIGH] ADR-004's deferral justification rotted silently.** RLS was deferred on four
  compensating "build-now" controls; **items 2 (denormalized `yard_id` + composite-FK) and
  4 (registry-generated isolation matrix that fails the build on a new unfixtured model)
  never shipped**, item 3 shipped digest-scoped only, and the "scoped default managers" the
  ADR names as the committed read control **never materialized at all** (reads are scoped by
  explicit `scoping.py` functions on the default manager). Three wave retros audited only the
  *reopening triggers*, never whether the compensating controls landed — and one retro angle
  even *assumed* item 4 exists. The residual is larger than the ADR's own text states.
- **[MEDIUM] The TM-7 restore forced-security-replay is not implemented** — yet S-802 is
  marked `tested`. The receipt's "security replay" actually describes the *unrelated*
  tar-path-escape guard. So a restore of an older backup can still **resurrect an expelled
  ex-partner's account or a revoked token** — Backyard's core adversary. Evidence-language
  overloaded a threat-model term for a different control.
- **[MEDIUM] No Content-Security-Policy anywhere.** XSS defense on member-authored content
  rests entirely on Django autoescape with no second net — deferral-by-omission (the
  "ships with the first interactive template" trigger never fired).
- **[MEDIUM] The cross-browser e2e job is advisory, not required.** It is the *sole*
  automated proof of S-101's "verified on iOS Safari and Android Chrome," runs on every PR,
  but is **absent from branch protection** (live required checks = `gates`, `secrets`,
  `code`). Enforced by discipline, not the platform. (The branch-protection receipt is also
  stale on both the added `code` check and the omitted `e2e`.)
- **[MEDIUM] TS-CO-4 SSRF fetch never moved to the worker,** and a stale in-code comment
  (`feed_views.py:212`) claims it "moves to the worker in wave 3" — worse than silence,
  because it tells a future reviewer the SSRF egress is somewhere it is not.
- **[MEDIUM/gap] No dependency-CVE scanning and no SAST in CI** (only gitleaks/secrets), on
  a security-first OSS project heading to a public launch that anticipates drive-by PRs.
- **[LOW] The RLIMIT_AS fix moved the DoS blast radius** from per-process to the *shared
  worker container* (a crafted max-size clip can OOM-kill it, degrading all transcode+digest
  work); no adversarial-media resource test proves the container bound holds.
- **[LOW] The live-repro harness is undocumented tribal knowledge** (bash-not-zsh scripts,
  fresh-volume-for-initdb, standalone-postgres-because-compose-doesn't-publish-5432, the
  docker-exec secret-sourcing trick, cloudflared-unreliable → use a real public URL for
  SSRF repros, browser-vs-curl CSRF asymmetry). It should be a `docs/runbooks/live-repro.md`.

## 4. The strategic reframe (the dissent, taken seriously)

The single most important output of this retro is not a bug — it is a **calibration
correction**:

1. **Match rigor to where the project actually dies.** The four-review-layer + isolated
   security-reviewer + committed live-repro *for every merge, even a 3-line redirect* is the
   right posture for Ratify (real users, regulatory liability) and **mis-calibrated for a
   zero-user family app whose scarce resource is founder attention, not defect rate.** Do
   NOT port "never cut a review layer for cost" from Ratify to Backyard. A single reviewer
   plus the non-vacuous CI guards is plenty for pre-adoption. Keep the mandatory
   security-reviewer on the *auth/token/media/email* surfaces (that is where it caught real
   HIGHs); relax it elsewhere.
2. **Some hardening exceeds the stated threat model.** §1 disclaims nation-states/targeted
   attackers; the deployment class is a $5 VPS / home NAS for 25–60 relatives. The NAT64/6to4
   SSRF tier and the SECURITY-DEFINER pg_proc probe defend adversaries the named in-scope
   ones (nosy relative, forwarded link, curious teen) cannot mount. Downgrade them to
   documented defense-in-depth; stop letting that finding class gate a wave.
3. **"Proven live" is destroyed-after-demo.** Stand up ONE persistent instance and stop
   tearing down — that is the real experiment, and the `tested → passing` loop is coupled to
   it (you cannot reach `passing` on throwaway stacks).
4. **The portfolio thesis is being answered on the wrong axis.** The most feature-complete
   OSS family network has 2★. If portfolio value is real, the PM case study + a live demo +
   distribution motions are the deliverables — and they are 100% within the founder's control
   and 0% built.

---

## 5. Phase 3 work map ("the proper work ahead")

### 5a. Backlog reconciliation (analysis-loop stories vs what S-201/301/101 shipped)

| Story | After v1 | Note |
|---|---|---|
| **S-210** mint-household-invite | **DONE** | S-201 (#57) `invite_household` mints pod + link + QR in one atomic flow; closed the "mint_invite has no caller" CRITICAL |
| **S-211** `can_issue_invite` capability | **DONE** | Shipped + the judge's pod-owner cross-scope hole closed + empty-set vacuity closed |
| **S-212** onboarding-roster/resend | **PARTIAL** | Ledger (who-joined-when) + revoke shipped; **resend/re-mint + share-sheet/QR/copy hand-over UX remain** |
| **S-707** appoint-delegate | **OPEN** | Rollout move #1; `can_assign_role` enforced but zero UI callers |
| **S-708** create-yard | **OPEN** | Rollout move #2; yard creation only in first-run wizard |
| **S-213** create-new-elder | **OPEN** | Delegate can't onboard a net-new grandparent onto the no-login path |
| **S-712** reversible-suspend | **OPEN → defer** | New credential-suspension class; not on the seed path |
| **S-713** post/comment-takedown | **OPEN → v1 (scoped)** | Only lever today is the nuclear `remove_member` |
| **S-714** bridging "ask instance admin" msg | **OPEN → small** | UX copy on a T-AUTH-G2 refusal (must not reveal the other yard) |
| S-215/716/717/718 | post-v1 | house-rule / parent-takedown-request / member-visible mod-notice / succession |

### 5b. Founder decisions to ratify (gate the build on these)

1. **Activate `pod_owner`?** → **No.** Keep it the ad-hoc-pod-local label it is; re-activating
   its invite power re-opens the exact cross-scope leak S-201 closed. Seed-ally needs
   yard_admins, not pod owners.
2. **New-elder path in v1?** → **Yes (S-213).** Four grandparents with assisted onboarding are
   a first-class rollout persona; without it a delegate can't onboard an elder without a shell.
3. **Second instance_admin / succession?** → **Yes, minimally** — grant a 2nd instance_admin
   through the same appoint-delegate surface (`can_assign_role` already permits it; bus-factor).
   Defer full succession automation.
4. **Moderation semantics?** → **Split:** ship single-item **takedown (S-713) in v1, scoped to
   content the moderator can see;** **defer reversible member-suspend;** document the
   person-level lever as remove-only. (S-713 must respect the reach-vs-visibility tension — a
   yard_admin cannot take down a pod-private post the guard won't return; route those to the
   parent/pod, post-v1.)
5. **Member-visible moderation notice?** → **Defer (post-v1).** Whether opacity causes distrust
   is exactly what the instrumented seed pod should answer before you build an audit surface.

### 5c. Recommended sequence

0. **GATE on founder ratification** of §5b (the judge's two pre-build code fixes are already
   shipped in #57).
1. **Rollout-enabler slice (one unit):** S-707 appoint-delegate (+ minimal 2nd instance_admin)
   **+** S-708 create-yard. Unblocks the seed-ally starting position. Security-reviewer + live-repro.
2. **Elder + hand-over:** S-213 create-new-elder → S-212 hand-over UX + resend. Extend the S-101
   cross-browser mobile e2e from *redeem* to *mint+hand-over* (curl alone can't prove the form path).
3. **Onboarding UX pass** (S-720: elder rail, one-action-per-screen). Draft the OSS delegate guide
   only once these flows are real.
4. **Cheap durable hardening, batched (NOT a wave):** S-722 arm `e2e` as a required check + refresh
   the branch-protection receipt; S-723 build the ADR-004 item-4 isolation-fixture guard (before any
   new read surface / real family data); S-724 baseline CSP. Deliberately do **not** open a broad
   hardening wave.
5. **Stand up ONE persistent seed instance (S-728)** on the self-host box; **stop tearing down.**
   Instrument A-HABIT (weekly-active, aggregates only); confirm the health email + the real-provider
   delivery/bounce matrix on a real elder subscription.
6. **Seed-ally dress-rehearsal (S-721):** James does founder-only steps, then a **non-technical
   stand-in** delegate creates the other side and onboards a household AND a grandparent — zero shell,
   zero founder help. This is the proof the 34/34 tally never gave.
7. **Run the `tested → passing` loop** against the persistent instance (each story earns a receipt vs
   the live app).
8. **Then accumulate the A-HABIT signal** (4/6 weekly-active, 3 of 4 weeks) and treat the kill path as
   live. Post-seed / pre-launch: S-712 suspend, S-716/717 member-facing moderation, S-725 SSRF
   relocation, S-726 dep-scan/SAST (before OSS launch), S-727 TM-7 replay, S-714.

### 5d. Definition of done (Phase 3)

Phase 3 is done when: (1) every v1 story is `passing` with a receipt against a **persistent** live
instance; (2) the seed-ally dress-rehearsal passes (non-technical delegate, zero shell, zero founder
help); (3) `e2e` is armed as a required check and the branch-protection receipt is refreshed;
(4) appoint-delegate / create-yard / create-new-elder are wired to a clickable surface, not shell;
(5) one persistent seed instance is live and instrumented for A-HABIT. Phase 3 is the
LEGIT→passing + rollout-executable milestone; it feeds — but is distinct from — Phase 4's ALIVE
criterion (4/6 weekly-active for 3 of 4 weeks, MEASURED).

### 5e. Non-build prerequisites (founder)

- Ratify §5b; confirm the seed-host (rog-node on **Linux** — it may still be on Windows/Stage-0 — or
  another self-host box; self-host is the thesis, no Supabase).
- Name the two per-side delegates and recruit a genuinely **non-technical stand-in** for the
  dress-rehearsal (the founder must not role-play the delegate).
- Accept the A-HABIT kill criterion (archive if 4/6-weekly fails after two design iterations,
  regardless of how green CI is).
- Confirm the T-EMAIL-6 delivery/bounce matrix is re-measured against the first real elder
  subscription, and the T-MON-1 health email actually sends on the deployed box.
