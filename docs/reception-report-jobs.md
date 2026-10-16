# Reception Reports: Background Generation

Applies to the maintained reader application. Does not deploy a release, change
BL states or modify the frozen manual application.

## Screen Contract

Administrators filter BLs and download the complete reception audit workbook.
The report is a dated cut, not an editable copy of the operational database.
State transitions and corrections still belong to the BL's existing authorized,
reasoned, audited workflow. The BL button opens that record.

State filters include all, open, closed and each reception stage. Arrival,
transport, SLA, date range and BL/truck search can be combined. Sorting and filters
apply to the complete cut before 50-row pagination; base-wide KPI totals remain
separate from the filtered result count. Dates refer to physical start, falling
back to scheduled date, not to the closure date.

One comparative table is used on mobile and desktop. It intentionally does not
use the generic `.tablewrap` record-card adapter. Headers and BL identifiers stay
horizontal, the header/BL column remain sticky, and only the grid scrolls sideways.
Column width and visibility are configurable; BL remains visible. These are view
settings, not business edits. Extra filters and column controls are collapsible.

Excel download locks immediately, including across filter redraws, and displays
queue/copy/generation states. Other work remains available. Closing the view
cancels its read/polling, not the server's reusable generation. A failed read
removes stale rows/actions; an unsuccessful download enables explicit retry.

## Server Execution

The following authenticated administrator endpoints may now return HTTP 202 JSON
instead of holding a request thread until a report is generated:

- `GET /api/receptions/report` (the BL register).
- `GET /api/receptions/history/report` (audit preview).
- `GET /api/receptions/history/export` (complete audit Excel).

202 contains `id`, `status_url`, `result_url`, `status` and `phase`. Poll the status
URL, then fetch the result URL after READY. FAILED returns 503 with a generic
message, without private exception details. An already cached result returns 200
directly. JSON/Excel content types are preserved. Result/status endpoints check
the current administrator permission again. A job ID is not a public download
token. The Excel artifact also has an `X-WMS-Report-Job` response header.

The API writes small descriptors to a separate `jobs.sqlite3`, then starts an
on-demand Python subprocess. No AI, email, OAuth login or scheduler is involved.
A cross-process OS lock allows only one generator per operational DB. Equal kinds
share a queued/running job; completed results are reusable for 120 seconds. New
cuts are built after that window. At most four distinct pending jobs are allowed.

The child makes a consistent SQLite online backup using a read-only source
connection, including committed WAL data. Small backup page batches release source
read locks between steps. This still uses disk I/O: it is not a zero-cost replica.
After backup, all calculations and workbook generation run on the read-only
snapshot, never on the operational connection or web request thread. Snapshot and
partial files are removed after success/failure. A hard-killed process's leftovers
are removed by the next lock holder; interrupted RUNNING jobs become FAILED rather
than being silently replayed.

Storage is under `.report-jobs-<source-hash>/` beside the configured operational
database, normally in the existing persistent data volume. No new Docker service,
production schema migration or journal-mode change is required. The directory is
private (0700 and files0600 on POSIX), ignored by Git, and never exposed as static
files. The temporary snapshot is a FULL database copy: protect this data volume
and its backups as carefully as production, since it can contain identity data.
Only the specific report result is downloadable. Artifacts expire after 30 minutes;
physical cleanup is lazy at the next worker start, not a separate cleanup daemon.

Linux workers have lower CPU scheduling priority, a 768MiB address-space ceiling,
and a 10-minute job alarm. Backup itself has a 120-second deadline. Windows uses
the same isolated single process, backup/SQL deadlines and final checks, but does
not claim the POSIX memory ceiling or hard alarm. Artifacts over64MiB fail instead
of being served. Low disk space fails before copying (two source sizes plus128MiB
reserve). These limits may require a separately reviewed period-scoped export for
an unusually large history; no silent truncation is applied.

The audit workbook calculates history once rather than twice and uses openpyxl
write-only cells, with literal text (not executable spreadsheet formulas). The
200-event preview cap does not truncate the Excel. This change does not move
unrelated dispatch exports or the small single-BL system workbook into this queue.

## Verification

### Arrival Priorities Without Physical Movements

Trabajo en curso separates En proceso, Pendiente de camion, Por llegar and
Historial. Without physical arrival, any nonblank FR in the master or accounting
references, OR a scheduled Triton date strictly before today in Lima, puts the BL
in Pendiente de camion. It shows the reason and planned date, never worker SLA
elapsed time. The existing scheduled_date is the confirmed Triton date when
available, otherwise the estimated Triton date from the importation source.
Today/future dates without FR, missing dates and invalid dates stay Por llegar;
invalid text is never treated as overdue. No date or FR implies actual arrival.

This is a read-only projection recalculated after refresh/synchronization or
the next local day. It does not write app_status, create an attention/truck,
change quantities, start SLA or reopen closed history. Existing active work and
closed records stay in their own views. Only administrator-confirmed historical
reconciliation can close an unreceived, documentary-complete historical BL.

The API keeps view=arrival and summary.pending_arrival as the combined unreceived
backlog for compatibility; new view=truck/upcoming and summary.pending_truck /
upcoming_arrival partition it. summary.total still counts BL physically in
progress (labelled BL en proceso in the UI), not the arrival backlog. Permissions,
search before pagination and unfiltered role-scoped KPIs remain unchanged.
Existing active/unarchived pending trucks open their own guide rather than
offering to create a duplicate; cancelled/archived/inactive plans are not links.

### Retired Pilot Attentions And Historical Closure

Annulled attentions are retained in the audit but excluded from the normal BL
list, detail count and work/history task projection. Explicitly requesting an
annulled attention ID still permits inspection. Display positions of subsequent
real arrivals count only real attentions; stored IDs and sequence numbers do not
change. A closed historical master with no real attention appears as one BL,
not one task per retired test and not a fabricated new attention.

Documentary closure remains an explicit administrator action with confirmation,
reason and fresh backend validation. FR/EM must cover every expected IP. A closed
annulled attention alone is insufficient: its zero-package receipts must all link
to cancelled trucks explicitly archived as tests. Active manifests, positive
receipts/arrivals, registered units, inventory lots, unknown test provenance,
pending real attentions or incomplete documents block the historical shortcut.
Only the retired-test path clears its synthetic arrival dates, with audit events.
It never rewrites quantities, deletes history or creates a receipt/attention.

Controlled maintenance can request the same reconciliation with
`return_detail=False` to avoid rendering hundreds of complete BL details while
holding a write lock. This changes only the return payload, not permissions,
validation or audit. A one-time owner-confirmed historical correction must not
become a permanent rule that automatically closes future arrivals whenever an
Excel gains an EM. Code approval and an authorized operational data correction
are separate actions.

Use disposable databases only:

```text
python -m unittest tests.test_report_jobs tests.test_reception_report -q
python -u tests/support_mobile_server.py 50675
node tests/reception_report_jobs_browser.cjs http://127.0.0.1:50675
node tests/reader_performance_browser.cjs http://127.0.0.1:50675
node tests/reader_ui_browser.cjs http://127.0.0.1:50675
```

Tests cover duplicate users/clicks, current permissions on status/artifacts,
read-only WAL snapshots, complete601-event exports, formula-safe cells, cache,
expiry/backpressure, failure cleanup, mobile horizontal headers, column controls,
200% text, stale/error/retry and late-result cancellation. Run the worker tests
also on Linux with adequate scratch space, without mounting production volumes.
