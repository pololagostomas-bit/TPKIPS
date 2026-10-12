# Reader Production Readiness

This change applies to the barcode reader version only. The separate manual
deployment is not rebuilt or updated. Installation requires an approved and
merged pull request into `main` before Docker deployment.

## Historical BLs

A closed BL does not need an associated truck. Removing a pilot association,
or receiving an updated accounting cut, must not reopen its operational work.
A missing FR/EM may update the accounting indicator, but the master remains
`CERRADO`. The import must not populate historical received quantities just
because its accounting references are complete.

Opening a closed historical detail is read-only: it can display a previously
saved validation sample, but cannot generate one or initialize validation checks.

An explicit administrative reopening remains permission-checked, confirmed,
reasoned and audited. Existing historical reconciliation is retained for an
eligible open master; this change does not perform a bulk closure or invent
arrivals, counts, locations or timestamps.

## Pilot Trucks

Retire only an explicitly approved snapshot of pilot guides, not every guide
whose name starts with `SCAN`. Future scanner-created trucks are operational.
Archived guide identifiers remain reserved for audit and cannot be reused.
Inactive associations do not appear as live truck assignments, and a retained
arrival location does not offer navigation into an archived truck.

Physical BL work must be preserved separately from truck retirement. Receipts,
attention records, counts, accounting references and inventory are not erased.
No database, cleanup script, operational record or backup belongs in this PR.

Workbook imports no longer create automatic demo truck proposals. Test fixtures
can explicitly invoke the existing demo helper; production imports cannot.

## Read Performance

Shipment, history and attention-line indexes avoid repeated full-table scans.
Accounting attention matching is batched without changing partial-arrival rules.
Administrative closure eligibility is checked only for the visible work page;
classification and dashboard totals still cover the full authorized dataset.

Reception reports render at most 50 rows per page. Filtering precedes paging,
totals remain global, and the unpaged API is retained for older callers.
Closing the report cancels its read request; late responses cannot reopen it.
Identity and account loads are deduplicated, assignees load once per role, and
the existing camera library loads on demand instead of delaying every page.

Read requests use a non-blocking progress indicator so navigation remains usable.
Save commands retain blocking feedback and are never automatically replayed.
The existing Waitress server already has six request threads; no extra scheduler,
offline business-data cache, speculative writes or worker process is introduced.

## Arrival Versus Pending Work

Excel availability, dates, FR/EM and confirmed truck plans do not prove physical
receipt. Unreceived BLs appear in Llegada, not Zona de recepcion or pending-work
KPIs, and do not start SLA. Queue filters, detail, reports and the work summary
share a read-only evidence projection. Positive per-BL receipts or truck arrivals
activate work; initial zero-package attentions do not. Advanced legacy work is
preserved for review and already closed historical BLs remain closed.

Imports no longer mark a BL physically arrived from Excel alone. Earlier Excel
arrival marks remain stored for audit; the operational view corrects them without
rewriting the database. The reader UI offers Pendientes, Llegada and Historial;
waiting BLs lead to truck registration rather than a standalone arrival shortcut.

## Verification

Use synthetic regression tests for closed history without trucks, archival trace,
future scanner guides, paged reports, role checks and no automatic demo seeding.
Browser tests cover phone, desktop and landscape layouts, cancelling slow reads,
single account/identity loads and deferred camera loading. Benchmarks use a
private, read-only database copy, never an in-place production experiment.
Desktop browser checks do not certify physical Android camera or HID hardware.
