# Power BI stock every five minutes implementation plan

> Execute inline with one coordinator; use the existing bounded public-text auxiliary for review only.

**Goal:** Automatically load validated warehouse01 BI stock every300seconds.
**Architecture:** Separate API/mapping, normalization and atomic storage; compose
them in powerbi_stock, started by existing cloud startup in a bounded separate
loop so Excel timeouts cannot delay the300second cadence. Reuse the
server MSAL cache and inventory contracts; keep errors and last valid cuts local.
**Tech stack:** Existing Python/requests/MSAL/SQLite and HTML/CSS/JavaScript.
**Spec:** docs/powerbi-stock-auto.md.

## Tasks

- [x] Port the prior synthetic row normalizer and tests. Add failing tests for
  private configuration/token isolation, HTTP/API partial results and changing
  refreshes, complete-cut activation, rollback/duplicate/newer-cut guards and
 300-second scheduling independent of Excel. Implement to pass.
- [x] Integrate cloud source priority, schema/status/history and inventory
  descriptions/positive bins, preserving allocations, other sources/warehouses,
  count/putaway fields and manual fallback. Verify temporary-DB integration.
- [x] Update the existing admin state/history panel and inventory consultation;
  verify success/error/stale states and mobile/desktop behavior, no live writes.
- [ ] Run full clean Linux/targeted browser/security checks, review one bounded
  public/synthetic submission, publish/attach the PR and save project memory.

## Review focus

API200 may mean partial/error; verify all nested errors and row count. A refresh
can complete during download. An operator may load a newer manual cut. Multiple
locations/zeroes/punctuation must not inflate stock. Token expiry, BI throttling
or interrupted runs preserve stock and disclose stale state. Source polling is
not an upstream refresh and status reads must never fetch or import.

Owner clarification during verification: source article codes are authoritative,
including punctuation/internal spaces. Exact per-article storage and lookup now
preserve collisions in the old normalized key without merging physical stock,
bins, reservations or labels. Added a real temporary HTTP/operational regression
and position-evidence regression for two distinct source codes sharing a key.
