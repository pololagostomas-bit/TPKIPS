# Purchase Request Dates And Severity Implementation Plan

> Execute inline with executing-plans; reuse the existing isolated reader checkout.

**Goal:** Include the source IMP/OV request date in purchase reports and present
grave quotation issues separately before preliminary/factory-order issues.

**Architecture:** Existing Python reader, openpyxl, private alert SQLite and
vanilla JS. Retain request dates per source row in the existing JSON payload;
no new database or scheduler. Preserve independent rules, episode identities,
delivery deduplication, editable speech, recipients and schedule.

**Scope:** The owner's 2026-10-22 request. One source column, Fecha de solicitud
de IMP/OV, not two inferred creation dates. Missing/unreadable dates display
Sin fecha; do not substitute detection, ETA or synchronization timestamps.

## Steps
- [x] RED: Synthetic workbook tests for date aliases, native/text/serial dates,
  blank/invalid/formula values, duplicate source dates and unchanged identities.
- [x] GREEN: Parse optional dates without weakening required OC/IP/OV checks;
  preserve all source dates in private history and expose safe display text.
- [x] RED/GREEN: Daily/initial/incremental mail sections prioritize GRAVE/COT,
  retain new/old distinctions inside each level and include dates everywhere.
- [x] RED/GREEN: CSV dates, legacy compatibility, gravity-first ordering and
  existing download/error/filter/mobile browser contracts.
- [x] Verify focused/full suite, responsive synthetic screenshots, diff and
  credential checks; publish only selected code/tests/docs as a PR for approval.

## Review Focus
Date edits must not create a new case or reset elapsed time. Grouped rows may
have multiple dates, including missing values; never silently select the first.
Optional invalid dates must not hide an alert. A row can still have two distinct
rule episodes. Existing snapshots/history without dates must render. No source
Excel, real mail, deployment, service restart or frozen manual change.

## Ledger
- Baseline: 39 purchase alert/history tests pass in .tools/wms-qa Python.
- Existing unrelated resilience changes preserved and excluded from publication.
- Clean staged candidate926unittest OK/2planned skips,124.184s;48focused tests OK.
- History/mail browser checks at320/393/1366px: filters, single-flight export,
  failure recovery, dates and responsive layout. Final review found no P1/P2;
  strengthened exact incremental subgroup coverage for new/old in both levels.
- Gitleaks and diff/syntax clean. Real Outlook not certified. No real delivery,
  production/Excel edits, install, merge, service restart or manual changes.
