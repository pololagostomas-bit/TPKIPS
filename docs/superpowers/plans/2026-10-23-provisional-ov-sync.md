# Provisional OV Synchronization Implementation Plan

> **For agentic workers:** Use executing-plans inline; one bounded reviewer at finish. Follow TDD for each behavior.

**Goal:** Replace a provisional OV reference on its existing receipt line when the
current source supplies a uniquely identified real OV, without losing physical work.

**Architecture:** Reserve existing exact, OC and IP matches first. Then match only
provisional-to-real OV revisions with the same sheet/BL/NP/nonempty IP/nonempty OC.
Do not match by Excel position, quantity or NP alone. Existing historical duplicates
require a separate authorized, backed-up maintenance operation, not automatic deletion.

**Tech Stack:** Existing Python/SQLite domain, JavaScript label presentation, unittest.

**Spec:** `docs/reception-import-line-identity.md` and owner's reported stale provisional OV.

## Constraints And Review Focus

- Reader only; no server restart, deployment or private data publication.
- Freeze attention quantities, scans and destinations, not documentary OV metadata.
- Keep separate real OVs, stock orders and simultaneous provisional/real source rows.
- Ambiguous/missing IP/OC anchors fail before writes; row order must not decide.
- Preserve audit and report/label association with the same original line ID.

## Task 1: In-Place Provisional OV Revision

- [x] Add `tests/test_reception_import_ov_revision.py`: unique revision/idempotency,
  moved rows, multiple candidates, empty anchors, distinct real OVs, simultaneous
  old/new source references, and frozen attention/detail/Excel export.
- [x] Run those tests RED, extend `_reception_import_line_matches`, audit OV once.
- [x] Run existing OC/IP/snapshot and new tests GREEN. Recognize COTI in the
  existing quotation print branch with its label regression.
- [x] Document boundaries; no historical cleanup in the importer.
- [x] Run clean-candidate full suite, print browser, diff/syntax and secrets scan;
  obtain one bounded public-code review.
- [ ] Publish a new PR against current main.

## Task 2: Private Existing-Data Regularization

- [ ] Prepare a private stdlib maintenance helper and synthetic safety/rollback tests.
- [ ] Rehearse against an online backup; preserve original operational line/attention
  and remove only a uniquely matched, unworked documentary duplicate, with audit.
- [ ] Apply only after explicit owner approval; recheck current source/state under
  a write lock. Never infer or change received quantities, locations or completion.
