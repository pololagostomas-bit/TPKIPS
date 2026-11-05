# Explicit EM Coverage Across Arrivals Implementation Plan

> Implement inline with one coordinator; follow executing-plans and TDD. No new agent per task.

**Goal:** Preserve one EM per physical reception by default while allowing an
audited administrator exception for one existing EM covering selected arrivals.

**Architecture:** Keep the EM's original attention unchanged. A separate active
coverage projection links that document to explicitly selected received
attentions; current FR/IP/EM and original assignment must still match. Reuse
the reference-update route, costing reconciliation and existing responsive UI.

**Tech Stack:** Python, SQLite, HTML/CSS/JavaScript. No new packages/services.

**Spec:** docs/reader-partial-costing.md and the owner's instruction: the normal
rule remains one reception/one EM, a FR can have multiple EMs, and exceptional
combined coverage must be explicit rather than inferred from one source row.

## Constraints And Review Focus

- Reader only; manual frozen. Do not deploy or mutate production for this PR.
- No guessed coverage, copied EM entries, physical quantities or SAP checks.
- ADMIN, explicit selected arrivals, confirmation, reason and audit required.
- Future or canceled arrivals and changed source FR/IP/EM cannot inherit coverage.
- Revoking coverage preserves closure history but invalidates unsupported cost proof.
- Same request is idempotent; request transaction owns commit/rollback.
- New coverage must be reflected in pending EM counts without inventing document count.

## Task 1: Coverage And Documentary Projection

- [x] Add failing synthetic tests for three arrivals/one EM, default separation,
  fourth arrival, invalid role/scope/source, revocation and idempotence.
- [x] Add reception_em_coverage.py schema/validation/selection projection/audited
  set operation. Initialize before existing startup costing reconciliation.
- [x] Integrate explicit coverage into bound-EM evidence, reference-update
  reconciliation and pending EM coverage counts; retain actual EM count.
- [x] Run focused tests and previous single-arrival/shared-IP costing regressions.

## Task 2: Admin Interaction And Delivery

- [x] Add collapsed admin form under Transferencia, explicit document selection
  and individually selected arrivals, confirmation/reason, retry-safe save/revoke.
- [x] Add JS contracts and authenticated browser checks at mobile/desktop widths.
- [x] Validate the actual case on an isolated read-only-derived database copy;
  no operating write; remove disposable full database afterward.
- [ ] Run clean Linux suite and staged secret/data checks, update PR59 and verify CI.
- [ ] Save focused project memory/checkpoint and clearly separate PR from install.
