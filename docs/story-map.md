# Story map

Status: Phase 0 artifact, 2026-07-20. The backbone is user activities; the v1 line is a walking skeleton through every activity, cut to the minimum that can pass the alpha KPI. The canonical machine-readable version is [stories/stories.yaml](../stories/stories.yaml); this file explains the shape and the cut.

## Backbone (what people actually do)

1. **Get in.** Invite link to joined-and-in-your-pod in under two minutes; elders get a token link instead of an account.
2. **Share.** A link, photos, or a short update; pick the audience (your pod, a yard, or several).
3. **Catch up.** A chronological feed that ends, per yard, quiet by default.
4. **Respond.** Reactions and comments; elders respond by one tap or email reply. Reciprocity is the product working.
5. **Run the family.** Invites create structure automatically; roles, removal, supervised kids' accounts, full export.
6. **Keep it alive.** One-command deploy, backups, migrations that never eat an archive.
7. **Know the family.** Profiles that double as the family directory: kinship names, birthdays and anniversaries surfaced calmly, contact info with member-controlled visibility. (Added 2026-07-20 by founder ask; see the founder capture addendum.)

## The v1 line

v1 includes exactly the stories flagged `v1: true` in stories.yaml: 33 stories that make the seven activities work end to end for the founding household and the first yards. Four stories are built into the map but flagged post-v1 (`v1: false`): the ambient frame display (S-603), email-photo-to-pod posting (S-503), vCard directory export (S-904), and new-member intro cards (S-905). All are strong candidates for v1.1; none is required to pass the alpha KPI.

## Explicit non-goals (not in the map at all)

Chat and DMs (group texts already exist; we replace their *broadcast* misuse, not messaging) · events and calendars (the organizer wave has that covered; birthdays and anniversaries are people-dates in the directory, not a calendar product) · full genealogy trees (bonsai and family-book exist) · medical or emergency-info vaults · native app-store apps · federation/ActivityPub · end-to-end encryption (see PR-FAQ; the v1 threat model is platform-elimination, and E2EE would break the elder surfaces) · any AI feature · anything with a count on it.

## Candidates on deck (not yet stories)

Kinship-name display everywhere it disambiguates (partially covered by S-901) · remembrance dates for relatives who have passed (valuable, sensitive; design deliberately, later) · Tinybeans/FamilyAlbum importers (the VoC sweep found trapped users looking for the exit).

## How stories flow

`spec -> built -> tested -> passing`, evidence required at `passing`, enforced by CI. Stories are the spec: acceptance criteria become the e2e tests in Phase 3's story loop. New ideas (including everything the VoC sweep and family feedback surface) enter as `spec` stories mapped to an activity, or they do not enter at all.
