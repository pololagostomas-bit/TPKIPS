# Reader: package progress, manufacturers and transfer mail

## Package Progress

Each BL shows physical packages received / total expected. A valid retained DHL
total takes precedence for display; otherwise the documented WMS total is used.
Unknown totals appear as a dash, never an invented expected quantity. This does
not rewrite the importation source, WMS expected quantities or receipt rules.

For partial arrivals, the BL numerator is previous receipts plus the current
truck's scans (or its recorded arrival, not both). A separate caption identifies
previous receipts. The truck header compares only this truck's packages with the
remaining expected for its attached BLs; any unknown denominator stays unknown.
It cannot predict BLs not yet attached to the truck. Overages remain visible.
Duplicate reads never increment counts. Partial arrival finalization remains
allowed; the counter does not replace arrival validation or close the BL.

All progress reads use the local tracking cache. Scans return updated metadata
with their existing response; rendering, reviewing and navigating do not fetch
DHL directly or spend another external call per package.

Manufacturer names are deduplicated from BL lines, with the shipment's brand
summary as fallback. Regional variants of known brands share the manufacturer
name. Multiple names remain visible in the scanner, location review, BL header
and work list. This is display-only; source brand fields and private logos stay
unchanged.

## Truck Controls

The reader keeps one compact back-to-trucks arrow and one cancellation action.
The generic scan-stage back and duplicate discard button are removed. Unsaved
readings still block finalization and navigation asks before discarding drafts.
Administrators get explicit Reopen arrival / Reopen location actions after a
saved stage, with confirmation, a reason, server role checks and history. Reopen
location preserves quantities; reopening arrival retains the existing protection
against erasing BLs that have already started counting. No automatic rewinds.

## Transfer Mail

The admin's Profile / Tools and options / Mail page includes transfer requests
alongside existing reception emails. It shows sender, recipient, activation,
registered Microsoft mail session, and the latest 100 request statuses, including
confirmation/expiry. Configuration is managed here, with a link from the BL.

The new status endpoint is authenticated, admin-only and no-store. It never
returns tokens, token hashes, guest links or MSAL cache contents. Reading it
neither sends email nor obtains a Microsoft token. A registered session is not a
guarantee of an accepted send: the outbox records authorization/send errors.

The existing server worker reuses cloud_auth and silently refreshes the same
Mail.Send session used by other corporate services. No second login store or
new permission request per BL is introduced. If Microsoft revokes consent, the
sender differs, or the session is no longer renewable, reauthorization is needed.
The separate activation and trusted HTTPS origin requirements still apply.
No production mail, service startup or deployment is performed by these changes.
