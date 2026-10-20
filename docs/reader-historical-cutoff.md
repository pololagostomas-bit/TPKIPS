# Reader historical cutoff

This service implements an explicit owner-directed assumption for disordered
Excel history: the current `reception_shipments.scheduled_date` is on or before
2026-07-31 inclusive. It does not establish arrival, FR/EM completeness, SAP
completion, received quantities or inventory. Pending documentary accounting
remains pending after a historical closure.

The implementation is confined to `backend/services/reception_historical_cutoff.py`.
API/UI integration and any production preview or application belong to the
calling administrator workflow. Nothing schedules or automatically applies the
cutoff on Excel import, startup or the passage of time.

## Interfaces

```python
preview_historical_cutoff(connection, cutoff='2026-07-31', *, role=None)
apply_historical_cutoff(connection, data, username, role)
```

Both functions require the trusted server role `ADMINISTRADOR`; the preview's
default role is denied. Use an initialized reader SQLite connection with
`sqlite3.Row`. Apply additionally requires an identified administrator,
`confirmed is True`, a trimmed reason of 8 to 500 characters and the
current preview token. Neither function invokes a detail endpoint, network
service, notification, inventory generator or NP correction module.

The cutoff must be a real, strict `YYYY-MM-DD` string no later than 2026-07-31.
An earlier date is supported. Source dates use the existing
`backend.services.workload._timestamp` parser: ISO dates/timestamps and day-first
Excel/SAP text; offsets normalize to Lima before comparing calendar days.
Unparseable and absent source dates are excluded. No fallback to receipt,
accounting, shipment creation or import time is used. The existing Excel importer
selects confirmed Triton date before estimated date for `scheduled_date`.

Example for the future administrator handler, using its own database connection
and authenticated identity:

```python
preview = preview_historical_cutoff(connection, cutoff='2026-07-31', role=role)
# Present the complete eligible list and exclusions for explicit confirmation.
result = apply_historical_cutoff(connection, {
    'cutoff': preview['cutoff'],
    'token': preview['token'],
    'confirmed': True,
    'reason': administrator_reason,
}, username, role)
```

Preview returns `cutoff`, `date_field='scheduled_date'`,
`basis='OWNER_INSTRUCTION_ASSUMPTION'`, `fr_em_sap_verified=False`, `token`,
`eligible`, `excluded`, `eligible_ids`, `excluded_ids` and `counts`.
Each item contains `id`, `bl_awb`, raw `scheduled_date`, normalized `scheduled_day`
and the stored `accounting_status`. Excluded items also contain `reason`.
`counts` contains `total`, `eligible`, `excluded` and `by_reason` (excluded counts).
Apply returns `cutoff`, consumed `token`, `applied_ids`, `applied_count` and the
revalidated preview's `counts`. IDs are ordered by shipment ID.

The service applies the entire eligible set represented by the token. There is
no partial-ID apply mode. A caller must not display a filtered subset as though
that were the entire set being confirmed.

## Exclusions And Proof

The first applicable exclusion is reported:

| Reason | Meaning |
| --- | --- |
| `ALREADY_CLOSED` | Stored master status is already `CERRADO`; never duplicated. |
| `UNKNOWN_DATE` | Current source date is empty. |
| `INVALID_DATE` | Current source date cannot be parsed. |
| `AFTER_CUTOFF` | Current source calendar day is later than the cutoff. |
| `PHYSICAL_WORK` | Open attention, operational master stage, active/unproven scan or physical evidence without closure proof. |
| `INVENTORY` | Any linked lot, including links through a reception line or BL identity. |
| `TRANSFER_WORK` | Transfer request is neither confirmed nor revoked. |
| `TRUCK_WORK` | Linked truck is missing, unarchived or not cancelled. Even inactive/legacy manifests require proof. |

Physical evidence includes quantities, receipts (including unproven zero
receipts), truck/BL arrivals, count and scan markers, locations, validation,
transfer confirmation and non-documentary arrival timestamps. A legacy arrival
explicitly attributed to `IMPORTACION EXCEL` follows the existing projection:
it does not become physical evidence just because it contains a date.
Raw `ARRIBADO` status alone is not physical evidence and does not exclude an
otherwise documentary-only BL, even when import history is missing.
The automatically initialized sample and `validation_location_checked=1` also
do not prove work: viewing a detail can set both. A saved operator validation
audit (`VALIDACION`, `linea:<id>:muestra`) does require closure proof, even if
the operator unchecked the location control. Other physical checks still apply.

All attentions must already be `CERRADO`. If physical evidence exists, each
attention also needs a completion timestamp and the existing
`reception_closure.closure_check(..., allow_documentary=True)` must independently
accept the shipment. Its full per-IP accounting and partial-arrival checks still
apply in this exception. An annulment alone does not prove closure. Inventory,
active scans, unresolved transfers and unarchived truck work remain excluded.
The cutoff never closes or rewrites those child records to make them eligible.

## Atomicity And Audit

The preview uses a read-only savepoint for a consistent snapshot. Its SHA-256
token includes the cutoff and all eligible shipment snapshots: master rows,
lines, attentions and attention lines, receipts, scan and truck evidence,
accounting references and EM children, transfer requests and shipment history.
A new eligible ID, removed eligible ID or changed eligible snapshot invalidates
the token even if `updated_at` did not change. Changes to records that remain
excluded do not invalidate an otherwise identical eligible set.

Apply takes SQLite's writer reservation inside a savepoint before re-reading
eligibility and comparing the token. Any stale token or failure rolls back all
of the operation's closures and audit entries. It preserves an outer transaction;
the caller controls its eventual commit or rollback. With no outer transaction,
releasing the savepoint commits the complete batch. Lock/busy errors should be
handled by the normal caller error path; do not apply an obsolete preview.

Only the eligible master rows receive `app_status='CERRADO'`,
`condition_status='HISTORICO POR CORTE'` and `updated_at`. The two existing
initialization flags are set to one to prevent startup's legacy quantity
initialization from fabricating received quantities for a newly closed master.
Original flags and statuses are captured in the audit. Dates, quantities,
documentary fields and every child table are preserved by apply.

Each affected BL receives three `CIERRE HISTORICO POR CORTE` history entries:
`historical_cutoff`, `app_status` and `condition_status`. They record the
administrator, reason, owner-instruction assumption, cutoff, source date,
accounting status and preview token. `fr_em_sap_verified=False` explicitly means
the cutoff itself has not verified those external facts. Existing documentary
evidence remains available independently.

Reusing a consumed nonempty token is rejected. A fresh preview excludes the
closed IDs, and applying its empty eligible set is a no-op without duplicate
audit. A later Excel date or accounting refresh can update documentary fields
but preserves `CERRADO` and the historical condition under existing rules.

## Verification

`tests/test_reception_historical_cutoff.py` exercises real disposable SQLite
databases. It covers cutoff boundaries and strict input, permissions and
confirmation, preserved pending accounting, active work exclusions, legacy Excel
provenance, child-document/token changes, rollback of the entire batch,
idempotency, a competing SQLite writer, and import/startup regression behavior.

The focused run of the new tests plus projection, retired history, pilot
correction and reception-work tests passed 79 tests, including 23 new tests.
No production data, service or deployment was inspected or changed by this
implementation.
