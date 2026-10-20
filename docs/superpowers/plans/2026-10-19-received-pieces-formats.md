# Received Pieces And Label Formats Implementation Plan

> **For agentic workers:** Use executing-plans for the implementation and an independent review before publication.

**Goal:** Show physical receipts separately from DHL shipment totals, accept exact supported label wrappers, and diagnose accounting references without inventing receipt or closure.

**Architecture:** Retain Python and HTML/CSS/JavaScript. DHL cache remains documentary evidence; active physical scans and receipts remain authoritative. Normalize only complete recognized formats before exact cache/BL lookup; preserve the original reading in audit.

**Spec:** Existing docs/reader-scanner-fallback.md and design-system/triton-wms/MASTER.md; owner requests received-only normal list, AI(00) labels, SAP-star wrappers, and review of accounting status.

## Constraints

- Reader only; manual deployment frozen. No production data repair or forced rollout.
- No new DHL calls per piece, fuzzy matches, integer conversions or arbitrary leading-zero removal.
- Workers cannot fetch expected codes; admin fallback retains its separate permission check.
- No public credentials, actual guides, package IDs, Excel rows, databases or screenshots.
- Preserve unrelated local resilience changes; publish only selected reviewed files.

## Review Focus

- Bare18digit identifiers beginning00 must retain all18digits.
- Different18digit identifiers must never collapse to one piece.
- Wrong-BL/unknown/expired new pieces still fail; retry aliases remain idempotent.
- A3piece documentary shipment with1physical read must show1received and2pending, not3received.
- Accounting corrections must preserve suffixes and reject unsupported ambiguous identity, not force a completed status.

## Tasks

- [ ] Add failing normalization/intake/status/UI regressions using synthetic IDs.
- [ ] Recognize paired-star DHL JD and fixed GS1 AI00 +18digit field, including supported AIM carrier prefix; retain existing JJD/JD compatibility.
- [ ] Return explicit physical receipt count and admin-only received codes; show received-only normal detail and label the total as shipment total.
- [ ] Inspect accounting diagnosis separately, add regression and smallest safe fix if proven.
- [ ] Run focused and full tests on a clean selected-file candidate, mobile/desktop browser QA and secret/diff checks.
- [ ] Publish new reviewed PR; do not merge/deploy. Record exact verified delivery state privately.
