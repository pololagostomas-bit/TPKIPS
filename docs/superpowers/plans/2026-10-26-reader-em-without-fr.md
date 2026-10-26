# Reception Without FR Implementation Plan

> Execute inline with executing-plans; one coordinator, no additional agents.

**Goal:** Completed full/partial counts can enter EM and prepare labels while FR
is pending. Keep documentary debt visible and measurable, without fictitious FR/EM.

**Architecture:** Reuse existing state/permission/location/count validation and
explicit continuation with available NP. Track FR wait intervals as audited
DOCUMENTACION history events in existing SQLite, not another worker/database.
Resolve on real documentary refresh; reports read interval summaries in one batch.
Reuse the configured transfer mail and its existing authorization/outbox.

**Stack:** Existing Python/SQLite and HTML/CSS/JavaScript. Reader only.

**Spec:** Owner's completed-count/no-FR request and prior authorization to continue
physical work, report documentary delay and flag FR in the validation email.

## Constraints And Review Focus

- Missing FR permits physical preparation; actual EM registration still needs FR.
- IP conflicts, roles/assignment, sequential stages, count/location checks remain.
- Partial counts retain deferred zero quantities and later-arrival balance.
- One observed waiting interval per BL; calendar hours, independent of SLA.
  No backdating unknown old intervals; overlap/retries must not double-count.
- GET/report reads cannot mutate. Source/manual FR updates resolve the same wait.
- New mail warning uses existing destination, sender and enqueue point only.
- Never restart/deploy, touch production rows/manual, or send real test mail.

## Task 1: Count To EM And UI

- [ ] Update FR gate/partial/HTTP expectations and reproduce RED.
- [ ] Remove only missing-FR gates; retain conflict/positive SKU/count/location.
- [ ] Keep pending FR warning, enable assigned worker label preparation, and
      explicit physical continuation without a fictitious EM.
- [ ] Browser full/partial/no-stock/roles/error/retry on a disposable fixture.

## Task 2: Durable Wait And Reporting

- [ ] RED tests for start/resolution/repeated episodes/read-only/admin visibility.
- [ ] Add reception_fr_wait.py history intervals; hook status/manual/source writes.
- [ ] Include current/accumulated hours and note in admin detail/filtered Excel.
- [ ] Red FR warning in existing validation email; no new mail trigger/recipient.
- [ ] Verify scoped suites/full suite, browser/mobile, XLSX and payload-only mail.
- [ ] Review selected diff, scan secrets, publish PR, update focused memory.
