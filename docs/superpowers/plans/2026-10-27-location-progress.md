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

Validation: 1,045 Linux unittest checks passed (two skipped), with disposable
databases and workers/network disabled. Synthetic progress browser checks passed
at 320/393/1366px; the real disposable count/EM/location/label integration passed
at 1440/393/375/360px and 873px landscape. Existing no-stock count/EM labels remain
blank; final putaway now needs a saved destination. Physical devices and the live
deployment remain subject to acceptance after an approved installation.
