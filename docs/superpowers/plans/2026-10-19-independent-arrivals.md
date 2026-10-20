# Independent Arrivals And Audited Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Work separate BL arrivals independently and correct physical package reads without losing audit evidence.

**Architecture:** Keep Python reception state machines and HTML/JavaScript. Resolve operations by explicit attention and its receipt, not the shipment's latest truck pointer. Administrative package correction is separate from NP count; no synthetic receipt or unapproved production cleanup.

**Tech Stack:** Python, SQLite, classic JavaScript, unittest, Playwright.

**Spec:** User request for concurrent partial arrivals, correct truck return, orphan-attention administration and visible pending/scanned work. Existing frontend contract: design-system/triton-wms/MASTER.md.

## Global Constraints

- Reader only; manual deployment frozen. No merge, deploy, live writes or real mail.
- Preserve distinct OV/IP rows, immutable count plans and documentary source updates.
- Admin correction requires exact context, confirmation, reason and before/after history.
- Closed/downstream work must be explicitly reopened; no automatic inventory reversal.
- Worker must not receive expected package identifiers; admin tools stay separate.

## Review Focus

- Invalid/foreign/annulled attention must never fall back to another task.
- Starting a second arrival cannot change the first attention's quantities or stage.
- Cross-truck correction must not annul another receipt or partially write a batch.
- Unread/default quantities are not physical scan evidence.
- Stale correction forms must fail without losing newer reads or modifying other OV rows.

## Tasks

### 1. Isolate partial-arrival selection

Files: backend/services/reception.py; tests/test_reception_independent_arrivals.py.

- [x] Reproduce require_location cross-arrival block and start-count wrong response in disposable SQLite.
- [x] Validate explicit attention identity and remove cross-arrival stage gate.
- [x] Expose selected attention truck metadata, return exact task on count start, and scope reversal guards to that receipt.
- [x] Keep same unconfirmed BL assignment protected, allow subsequent arrivals only after previous physical arrival saved.
- [x] Verify independent states, retries, zero receipts and invalid attention no-write behavior.

### 2. Audited physical-package correction and pending overview

Files: backend/services/reception_package_corrections.py; backend/app.py (own routes only); frontend/static/reception-attentions.js; frontend/templates/reception.html; new focused tests.

- [x] Add failing tests for admin package replace/remove, orphan receipt quantity, stale token, worker denial and downstream protection.
- [x] Implement guarded correction retaining original scans, location and receipt before/after evidence; no NP modification.
- [x] Make attention selection explicit and show actual received/read/pending package counts without exposing expected codes to workers.
- [x] Preserve other attention counts and clear only selected task's stale controls.
- [x] Add mobile/desktop and error/retry browser tests.

### 3. Navigation and release verification

Files: frontend/static/truck-navigation.js; targeted navigation tests; docs/reader-independent-arrivals.md.

- [x] Delegate bounded navigation fix/tests with disjoint write set.
- [x] Run focused backend and frontend regressions, full suite from clean selected-file candidate and independent review.
- [x] Check selected diff for secrets/private data; retain existing PR workflow only.
- [x] Prepare private release evidence and leave operational writes separate from publication.

### 4. Owner-directed historical cutoff

Files: backend/services/reception_historical_cutoff.py; focused tests and docs;
admin routes and frontend/static/reception-historical-cutoff.js.

- [x] Add dated, admin-only preview and confirmed audited cutoff through 2026-07-31.
- [x] Preserve FR/EM, SAP and quantities; exclude active physical work and unknown dates.
- [x] Test stale previews, no navigation writes, concurrency and import/startup non-reopening.
- [x] Keep live closure separate from code publication; require exact approval and eligible scope before changing records.

## Verification Outcome

The clean selected-file candidate passed 819 unittest cases (two planned skips),
18 navigation tests, real-backend browser flows at 320/393/873/1366 pixels and
28px text checks. Independent review findings were reproduced and resolved.
No production record was corrected or closed during implementation.
