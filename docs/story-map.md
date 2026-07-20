# Story map

Status: Phase 0 artifact, 2026-07-20. The backbone is user activities; the v1 line is a walking skeleton through every activity, cut to the minimum that can pass the alpha KPI. The canonical machine-readable version is [stories/stories.yaml](../stories/stories.yaml); this file explains the shape and the cut.

## Backbone (what people actually do)

1. **Get in.** Invite link to joined-and-in-your-pod in under two minutes; elders get a token link instead of an account.
2. **Share.** A link, photos, or a short update; pick the audience (your pod, a yard, or several).
3. **Catch up.** A chronological feed that ends, per yard, quiet by default.
4. **Respond.** Reactions and comments; elders respond by one tap or email reply. Reciprocity is the product working.
5. **Run the family.** Invites create structure automatically; roles, removal, supervised kids' accounts, full export.
6. **Keep it alive.** One-command deploy, backups, migrations that never eat an archive.

## The v1 line

v1 includes exactly the stories flagged `v1: true` in stories.yaml: 26 stories that make the six activities work end to end for the founding household and the first yards. Two stories are built into the map but flagged post-v1 (`v1: false`): the ambient frame display (S-603) and email-photo-to-pod posting (S-503). Both are strong candidates for v1.1; neither is required to pass the alpha KPI because the token link and digest already cover the elder path both ways.

## Explicit non-goals (not in the map at all)

Chat and DMs (group texts already exist; we replace their *broadcast* misuse, not messaging) · events and calendars (the organizer wave has that covered) · native app-store apps · federation/ActivityPub · end-to-end encryption (see PR-FAQ; the v1 threat model is platform-elimination, and E2EE would break the elder surfaces) · any AI feature · anything with a count on it.

## How stories flow

`spec -> built -> tested -> passing`, evidence required at `passing`, enforced by CI. Stories are the spec: acceptance criteria become the e2e tests in Phase 3's story loop. New ideas (including everything the VoC sweep and family feedback surface) enter as `spec` stories mapped to an activity, or they do not enter at all.
