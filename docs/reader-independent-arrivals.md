# Independent Partial Arrivals And Package Audit

Reader WMS only. Publication does not install a release or authorize operating
data changes. The separate manual deployment remains frozen.

## Arrival Identity

Each positive physical receipt owns an attention. Its stage and quantities are
independent of the BL's other attentions. Starting count from a truck returns
that receipt's attention, not the oldest open task. Explicit invalid attention
IDs fail rather than silently selecting another arrival.

A saved positive arrival can remain in temporary reception while another truck
receives more of the same BL. An unsaved intake assignment still blocks
reassignment. A physical package identifier cannot be received twice.

The BL's latest truck pointer stays for compatibility. Navigation and admin truck
controls resolve the selected attention's receipt instead. Orphan and retired
truck attentions retain BL administration and return to the BL list. Reversing
an untouched arrival checks that task, not another arrival's count state; all
BLs in a truck are validated before the first scan is annulled. Reopening count
recalculates its contribution without changing another attention's quantities.

## Physical Progress

The detail shows each arrival's received package count and unique-read count.
The BL summary separates received physical packages, documented expected total
and pending arrival. Legacy packages without saved unique identifiers remain
receipts, not fabricated scans. Unknown expected totals remain unknown.
Workers see counts, never the expected unique package-code list.

## Administrative Package Correction

Administrators can open Regularizar bultos from a BL attention or the scanner's
administrative controls. They can replace a wrong unique identifier or annul
one recorded package, with confirmation, reason and a current-state token.
Replacement passes the same exact DHL ownership validation as normal intake;
it does not change physical quantity. Original scans are retained as ANULADO,
with administrator, time, reason and before/after evidence.

Removing a saved package changes only that receipt and its arrival total. The
temporary location distribution is captured in audit then cleared so its new
quantity can be distributed again. Other BLs and arrivals remain unchanged.
Removing its last package annuls that attention; it does not delete the BL or
source rows. If no positive receipt remains, the BL returns to pending arrival
and its former first-arrival timestamp no longer starts the SLA. Orphan/manual
receipts with no unique reads can have their actual
quantity corrected without inventing package identifiers.

An attention already in count or a later stage must be explicitly reopened to
Zona de recepcion first. Count evidence or inventory lots block the shortcut.
The operation does not edit NP orders, SAP, FR/EM or stock. Confirmed scanner
arrival totals that disagree with unique-read counts require reconciliation,
not silent recalculation. A BL ledger gap also blocks quantity regularization.

HTTP writes run under BEGIN IMMEDIATE. A stale correction form fails. An old
scanner retry for a package administratively annulled in that same truck is
rejected, including canonical barcode aliases, instead of silently restoring
the removed read. A later real arrival is a different truck context.

## Historical Cutoff

The separately documented owner-directed historical cutoff is an assumption,
not proof of physical receipt or accounting completion. See
[reader-historical-cutoff.md](reader-historical-cutoff.md). It must not close a
current partial arrival merely because an Excel date is old.
