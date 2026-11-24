# Triton Tracking Implementation Plan

> For agentic workers: execute the dependent HTTP/UI integration inline; one isolated auxiliary may own the independent data projection after its interface is fixed.

**Goal:** Internal OV/OC tracking extension, same repository/backend and original synchronization, with restricted access and no per-query cloud calls.
**Architecture:** Snapshot projection from the existing reception importer; dedicated CONSULTA_TRACKING profile; /tracking surface and API through password_policy WSGI. Deployment-only restricted gateway configuration/documentation, not started here.
**Tech Stack:** Existing Python, SQLite, HTML/CSS/JavaScript and Waitress. No dependencies added.
**Spec:** docs/superpowers/specs/2026-11-23-triton-tracking-design.md (approved by owner).

## Global Constraints

No production/manual/native/tunnel changes; no operational rows or credentials in code/review/PR. No automatic account grants. No cloud/DHL/AI calls from tracking searches. Confirmed ETA is not physical arrival; OC number is not approval; preserve partials and ambiguities.

## Review Focus

- Same-number OV/OC are separate; repeated NP and split BL cannot merge unrelated purchases.
- Restricted profile cannot use original WMS routes, even with forged headers or direct WSGI adapter access.
- Expired/temporary passwords, CSRF and revoked sessions retain original policy.
- Failed/partial source sheets preserve last good snapshot and expose staleness.
- Exact search has bounded pages and SQL reads; stale HTTP/UI responses cannot replace a later search.

## Task 1: data projection

Files: backend/services/tracking.py; tests/test_tracking.py; reception.py importer hook.
Interface: ROLE='CONSULTA_TRACKING'; init_schema(db); store_workbook(db,workbook,filename,cutoff=None); search(db,kind,number,offset=0,limit=50). All writes only in init/import. search is query-only-compatible; response contains document, source, summary, lines, pagination. Fields per line: item,description,ov,oc,bl,brand,requested_qty,invoiced_qty,pending_qty,received_qty,location,dates,stage,warning. Every result uses a positive explicit link, not NP alone. Snapshot replacement transactionally atomic; unsupported sheets keep previous snapshot and mark source warning.
- [ ] Write and observe regression tests before implementation.
- [ ] Implement and verify ambiguous links/partial quantities/missing dates/empty source/no cloud calls and bounded queries.

## Task 2: HTTP, access, UI

Files: backend/tracking_portal.py; backend/password_policy.py; backend/app.py; frontend/templates/tracking.html; frontend/static/tracking.js/.css; tests/test_tracking_portal.py.
API: GET /tracking/api/me -> username/display_name/must_change_password; GET /tracking/api/search?type=OV|OC&number=...&offset=0; POST /tracking/api/login,/logout,/change-password -> existing policy with mapped routes. All mutations require X-WMS-Request=1 and same-origin protection. Unknown /tracking routes404; HEAD safe. Tracking-only role blocked from all operational routes and demo/Entra modes fail closed. Login shell contains no business data; no automatic polling. Main admin profile options include new role, with existing temporary-password provision. Prefer role over new privilege table: explicit individual assignment, smaller surface. Existing other roles do not acquire access.
- [ ] Write HTTP failing tests, reuse password_policy and test direct adapter/header bypass.
- [ ] Build responsive branded timeline, line details, no-result/error/stale/partial states, text-safe rendering and latest-request-wins.

## Task 3: verify and publish

Files: docs/triton-tracking.md; infrastructure/tracking-gateway.conf (restricted prefix proxy template); meaningful proxy whitelist checks.
- [ ] Run synthetic projection/HTTP tests and full suite; browser320/393/1366 for auth/search/partial/error/retry.
- [ ] Review complete integrated changes in bounded public/synthetic packets via Gemini; pin exact BASE/HEAD/tree.
- [ ] Push feature branch and publish PR to main in TPKIPS; verify CI. No merge/install/public tunnel activation in this task.

## Rulings

- New readonly profile implements the explicit Tracking permission via the existing role system; operational users need a personal tracking account/profile granted by admin, never a shared account.
- Snapshot extension includes pre-BL rows. Document-only rows without an item remain visible; no fictitious quantities or approval.
- Own tunnel/gateway activation is documented and tested, not executed before PR acceptance/install.
