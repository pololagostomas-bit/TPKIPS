# Partial NP Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Admin can mark an accidentally scanned NP absent from one arrival, retain physical read evidence and finish a partial NP count without changing DHL packages.

**Architecture:** Reuse per-attention quantity updates and the existing partial-count endpoint. Preserve the original scan marker for idempotent old scanner retries; distinguish a received NP from a read later corrected to zero. Reopening count preserves recorded quantities, not planned defaults.

**Tech Stack:** Existing Python/SQLite services and classic JavaScript, unittest and Playwright.

**Spec:** Owner confirmed a 9/10 NP receipt must leave one NP for another attention; package counts remain independent. Canonical frontend contract is design-system/triton-wms/MASTER.md. Operational data corrections require their own backup, exact scope and audit; never include real rows in Git.

## Global Constraints

- Reader only; manual frozen. No merge, deployment, restart or real mail.
- Preserve legitimate OV/IP rows and attention count plans; never fabricate scans, FR/EM, stock or transfer completion.
- Admin correction needs explicit confirmation, reason, expected previous quantity and exact attention; deny worker reactivation of admin-deferred rows.
- Original scan evidence remains immutable. Late automatic retries must not undo a zero correction.
- Closed/downstream attention requires explicit reopening before NP edits.

## Review Focus

- Zero and nondefault quantities survive count reopen; other arrival totals remain unchanged.
- 9/10 reflects received NP, not ten historical reads; absent NP remain visible separately.
- An all-resolved partial count with previously deferred NP can continue, but empty arbitrary requests cannot bypass unread orders or no-positive-read rules.
- Same NP under distinct OV stays distinct; same-view refresh and errors preserve unrelated drafts.
- Corrections never change DHL package counts or claim SAP completion.

## Tasks

### 1. Backend count preservation and guarded NP deferral

- [x] Add failing tests for reopen preserving zero, partial and excess quantities and other attention totals.
- [x] Remove planned-quantity overwrite on count reopen, retaining the earlier-arrival reset path.
- [x] Add admin-only defer_np quantity update: confirmed true, previous_received_qty, reason >=8, existing scan and selected attention; preserve scan marker and audit before/after.
- [x] Test role denial, stale quantity, idempotent old scanner retry, admin restore and worker rejection of admin-deferred rows.
- [x] Extend partial-count endpoint for empty unresolved IDs only when existing zero/deferred rows and positive received reads prove a real partial count.

### 2. Mobile and desktop NP correction controls

- [x] Frontend worker adds admin correction through the existing review panel, explicit reason/confirmation and no duplicate POST.
- [x] Progress distinguishes received versus absent; action finishes the NP count only, leaving downstream EM/location/transfer workflow intact.
- [x] Test 9/10, empty-ID continuation after a prior correction, stale response, 503 and worker visibility at mobile/desktop sizes.

### 3. Scan feedback requested by owner

- [x] Shared local WebAudio success/error tones, armed only from a scan gesture.
- [x] NP and truck sounds follow confirmed results, never detection or stale responses.
- [x] Test duplicates, rejected/malformed responses, no autoplay, blocked audio and rapid reads.
- [x] Keep visual feedback and camera/HID behavior without new dependencies.

### 4. Verification and publication

- [x] Independent review; focused and full clean-candidate tests, browser checks and secret scan.
- [ ] Publish a new PR from the merged reader baseline, excluding unrelated resilience work and all private data.
- [ ] Update focused memory, keeping applied data changes and installed code separate.

Verified before publication: 830 unittest OK (2 expected skips); 72 Node/browser
contract tests; real-backend partial corrections at 320/393/873/1366, automatic
NP at 7 viewports and fallback at 4. Final secret scan and syntax checks recorded
in private local release evidence. Physical speaker/reader acceptance remains open.
