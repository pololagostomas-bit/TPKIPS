# Import IP Line Identity Implementation Plan

> Execute inline with existing WMS memory, systematic-debugging and TDD.

**Goal:** A demonstrably unique IP correction updates the same reception line,
preserving its frozen count plan instead of inserting a duplicate NP.

**Architecture:** Extend the existing complete-snapshot matcher: reserve exact
source keys, then existing stable-IP/OV/NP OC revisions, then unique stable
sheet/BL/NP/OV/OC IP revisions. Use persistent line ID, never Excel row position.
No NP-only/IP-family matching or quantity-based guessing. Audit old/new IP.

**Boundaries:** Reader only. No production database edit, workbook mutation,
deployment, service restart, real mail or manual change. Distinct simultaneous
orders remain distinct. Already duplicated scanned rows require explicit audited
reconciliation, not silent deletion or summation by a background import.

## Steps
- [x] RED: IP correction, reserved matches, multiple OC/OV/IP, ambiguity before
  writes, row reorder, absent anchors, and preserved attention/reads/quantities.
- [x] GREEN: Unique third-pass IP matcher and audit; leave counting ownership
  and document synchronization in existing modules.
- [x] Verify targeted/full clean-candidate suites, existing scanner/count flows,
  scoped review, secrets/diff checks and create PR for approval.

## Evidence
Real case inspected read-only: IP changed with same source location and order
anchors; both old/new rows already contain reads. Different OC orders also exist
and must not be merged. Operational evidence remains private outside Git.

## Verification
Final clean staged candidate931unittest OK/2planned skips116.976s;40focused
identity/snapshot tests OK plus selected-attention detail regression. Crossed
and inverse anchors, source reorders, ambiguous snapshots and whitespace audit
covered. In-memory5000-row matcher55.6ms,5000distinct IDs (not an end-to-end SLA).
Antigravity bounded public/synthetic review; findings evaluated and reproduced
before focused fixes. Gitleaks/diff clean. No physical scanner certification,
new browser layout, production change, automatic historical merge or deployment.
