# Editable location and saved progress

**Goal:** In Ubicacion, assigned users can enter/change final location and save
one NP at a time. All received NP must have nonempty saved destinations before
validation. This supersedes the earlier read-only confirmation requirement.

Keep the existing location-lines endpoint and saved flags for compatibility.
Validate scope/role/stage and every supplied row before atomic writes, audit
destination changes, retain count quantities/scans, temporary receipt locations,
other arrivals and stock. Blank count stickers without stock remain possible;
the later location stage now requires an actual destination. Row-level saves
preserve other drafts, block duplicate/pending advancement and ignore late
responses from a different BL/arrival. No new worker or framework.

- [x] Reproduce location editing rejection and blank/manual advancement.
- [x] Implement per-NP saving, concurrency checks and required saved destinations.
- [x] Verify role/stage/arrival isolation, partial progress, failed-save drafts,
  edits while saving, filtered rows, mobile/desktop and existing count behavior.
- [x] Prepare the isolated change for PR review; merge/install require approval.

Validation: 1,080 Linux unittest checks passed (two skipped), with disposable
databases and workers/network disabled. Synthetic progress browser checks passed
at 320/393/1366px; the real disposable count/EM/location/label integration passed
at 1440/393/375/360px and 873px landscape. Existing no-stock count/EM labels remain
blank; final putaway now needs a saved destination. Physical devices and the live
deployment remain subject to acceptance after an approved installation. The
latest main includes PR46/47/48; location progress and late-NP inclusion browser
checks both passed after integrating that base and preserving both exit guards.

Owner follow-up: add physical-reader replacement/Enter and one-shot camera
input beside each final-location field. Camera decoding fills a pending draft
and focuses Guardar; it does not register a package or modify NP counts.
Preserve manual entry, other row drafts, stage/arrival scope and camera session
invalidation when a detail is replaced. Reuse the existing local decoder and
44px-or-larger accessible controls; no new scanning service or library.

Scan follow-up validation:47 focused Linux tests passed. The expanded progress
browser passed at320/393/1366px, including physical reader/AIM replacement,
camera draft-only input, invalid-read retry, denied permission, stale arrival and
replaced-DOM callbacks. Existing camera fallbacks passed four viewport sizes;
the real local decoder read Data Matrix, QR, Code128 and a rack Data Matrix.
