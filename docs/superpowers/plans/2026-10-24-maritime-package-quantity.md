# Maritime Package Quantity Implementation Plan

> For agentic workers: use executing-plans inline, one coordinator and at most one bounded reviewer. No production writes or deployment.

**Goal:** Receive a known maritime BL by physical package quantity when no individual labels exist, then use normal location and NP workflows.

**Architecture:** Keep package methods separate per truck/BL: existing unique scans, or explicit maritime quantity. Persist quantity in the existing manifest plan with an explicit method/version; never fabricate scan rows or external verification. Arrival/location/attention remain existing state machines.

**Tech Stack:** Existing Python/SQLite and vanilla JS/CSS.

**Spec:** Owner states maritime suppliers provide only BL and package count. Installed code inspected at the start lacked a quantity path; this plan adds it to the maintained reader only. docs/reader-maritime-intake.md records the resulting contract.

## Global Constraints

- Only MARITIMO source BLs, active existing scanner truck/manifest, administrator or reception assistant.
- No DHL bypass, no new BL/SKU/code generation, no automatic receipt of NP.
- Quantity is this BL on this truck, integer >=0, explicit save, not inferred expected total. Zero clears a pending quantity, not a receipt.
- A truck/BL cannot mix manual quantity and active unique scans. Preserve existing code-based historical maritime work.
- Versioned updates reject stale conflicting saves; identical retry does not add counts/history. Finalization atomic, derived from saved records.
- Admin reversal/cancellation audits and resets quantity so stale counts cannot reappear. No changes to another BL/truck/attention.
- Responsive existing UI, saved-vs-draft states, context guards, no destructive updates from background refresh.

## Review Focus

- Lost response/double tap: same total, one audit; stale different total rejected.
- Forged courier/DHL/manual request or active scans: rejected without mutation.
- New BL selected while saving/draft: preserve context and prevent finalizing unsaved totals.
- Mixed truck and partial maritime deliveries: exact per-BL count/location, no invented expected shipment total.
- Cancel/admin rollback/retry: audit retained, pending manual count reset and prior attention untouched.

## Task 1: Audited Maritime Counter And Arrival Integration

Files: backend/services/maritime_intake.py; backend/services/reception.py; scoped route in backend/app.py; tests/test_maritime_quantity.py.
Interface: set_package_count(connection, truck_guide, shipment_id, quantity, expected_version, username, role) returns count/version/duplicate. Existing summary adds registered count/method/version; scan count stays literal.

- [x] RED tests: 8 bultos with no scans/API; zero/invalid values; idempotency/stale versions; roles/transport/closed/mixing; finalization/locations; cancellation/reversal/partial arrival; rollback on history failure.
- [x] Implement additive manifest method/version schema, service and validated route. Reuse existing counts for scan mode; only saved quantity for quantity mode.
- [x] Run focused service/route regressions, including DHL scanner and reversals. Preserve active code verification rules.

## Task 2: Mobile Quantity Form And Reception Readiness Review

Files: frontend/static/reception-scan.js/.css; frontend/templates/reception.html; tests/maritime_quantity_browser.cjs; docs/reader-maritime-intake.md; docs/reception-readiness.md.
Interface: Por BL detects maritime with no active scans, offers quantity instead of unique-code field, persists to new route, and uses normal finalize/location/continue actions.

- [x] Browser test the real API with synthetic fixtures at320/393/1366/horizontal873, quantity save/retry/draft/context, mixed DHL, finalization and NP handoff. Test auth/CSRF rejection.
- [x] Implement form/context locks/drafts and accurate registered counters; no invented total when unknown.
- [x] Run full clean-candidate unittest suite, browser screenshots/layout checks and selected-diff secret scan. Assess operational readiness from verified tests and live read-only runtime, not a percentage guess.
- [x] Publish scoped new PR41 for approval and attach it; do not merge/install/restart. Preserve unrelated dirty resilience work. Update focused memory/evidence.

Verification: 966 unittest OK, two existing skips, 130.105s; quantity browser
four viewports and maritime regression five viewports. Fixtures only; physical
Android/thermal printer and corporate integration acceptance remain separate.
