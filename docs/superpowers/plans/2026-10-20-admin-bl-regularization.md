# Administrative BL Regularization Implementation Plan

> Execute related work inline with TDD and one bounded independent review.
> Do not create a new implementer/reviewer for every task.

**Goal:** Admin can see why closure is blocked, retire a nonexistent test record,
or explicitly close a BL/selected arrival administratively, preserving evidence.

**Architecture:** One guarded service with read-only preview/state token and an
atomic POST. Reuse existing accounting closure checks for ordinary closure;
administrative closure is explicitly not documentary or SAP verification. Add a
single always-discoverable admin section in the current detail, independent of
guidance preferences. Python/SQLite and classic local JavaScript; no dependencies.

**Spec:** Owner requests self-service for nonexistent pilot records, documentary
IP mismatch with work open, and partial NP deliveries. Owner previously required
audit/history preservation and a partial count that leaves the remaining NP for
another arrival. No operational mutation or deployment authorized by this PR.

## Scope And Contract

- Reader only, manual frozen. No real SQL, mail, merge, installation or restart.
- GET /api/receptions/{id}/admin-closure?attention_id=... returns preview;
  POST same path accepts action, token, confirmed:true, bl_confirmation, reason,
  attention_id when applicable, acknowledge_unverified:true for exceptional closes.
- Actions: reconcile (ordinary existing validated closure), retire_test (no source
  lines, accounting or physical work), close_bl (administrative exception), and
  close_attention (only selected arrival; other arrivals and BL stay open).
- Preview always names blockers. Exceptional closures carry distinct condition
  CIERRE ADMINISTRATIVO, not COMPLETADO, and never claim SAP transfer/FR-EM verified.
  Retired phantom uses REGISTRO DE PRUEBA RETIRADO, not fulfilled.
- Preserve NP quantities, scan evidence, packages/receipts, FR/EM/IP, stock/lots;
  no fuzzy documentary alias and no automatic duplicate cleanup. User must correct
  quantities in Inicio de conteo before closing the wrong partial delivery.
- Role ADMINISTRADOR, typed exact BL, reason8..500, fresh state token, explicit
  attention match and BEGIN IMMEDIATE protect every write. Reject workers,
  tampering, stale state, active unfinished truck intake and invalid action.
- Pending transfer links for a closed scope must be revoked without claiming SAP.
  Repeated confirmed request is idempotent and must not duplicate audit.
- Preview can display unverified/default counts as warnings; quantity defaults
  are not scans. Closing a single attention never closes the whole BL or discards
  other arrival work, even when it was the last open attention.

## Screen Contract

Admin, BL detail, task regularize a record. Existing primary warehouse work stays
unchanged. One administrative section with Review closure button opens a dialog:
current BL/attention, blockers, action select, reason, typed BL and acknowledgment.
Save disabled while pending, retained inputs on503/malformed response, captured
context checked before applying response. Cancel/Escape,44px targets, responsive
320/393/873/1366 and200% text. Worker sees neither section nor API details.

## Tasks

- [x] Backend TDD: preview, roles, closure distinctions, preserve all evidence,
  explicit partial arrival, phantom safeguards, stale token/idempotent retry,
  transfer revoke and import/init persistence. Service and focused tests.
- [x] Integrate GET/POST/asset routes without publishing unrelated dirty app work;
  HTTP tests for JSON errors, trusted role and transactions.
- [x] UI TDD: preview/current blockers, confirmation, context/error/double click,
  all four actions, guidance-independent admin-only controls, mobile/desktop.
- [ ] Clean-candidate full tests, browser screenshots, independent review, secret
  scan; publish a new PR on approved main. Do not install or alter operating BL.
- [ ] Update focused project memory, report pending installation separately.

## Review Decisions

- Ordinary receipt writes must reserve the writer before reading closure state,
  and reject administrative/retired closures until an explicit admin reopening.
  This closes the stale-tab reopening reported by the independent reviewer.
- A successful UI response must identify exact BL, attention, action, closed
  state and the expected condition. Empty or ambiguous200 responses are not success.
- Queue rows describe individual arrivals. The browser test checks master state
  through the read-only no-attention preview instead of mistaking a closed queue
  row for the whole BL. Physical quantities and documentary evidence stay unchanged.
