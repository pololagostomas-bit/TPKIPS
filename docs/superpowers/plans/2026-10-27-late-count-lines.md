# Late source lines in an existing arrival

**Goal:** Make NP added after an arrival plan visible and let an administrator
explicitly include unallocated orders in that same arrival without losing reads.

**Architecture:** Keep automatic import and frozen plans unchanged. Add a small
count-plan service, authenticated POST, and disclosure in the existing arrival
summary. A source line is a candidate only when it has positive expected quantity,
zero received quantity and no attention assignment at all. This does not merge
distinct orders with the same NP. Include selected IDs with reason, confirmation
and a state token, under SQLite write lock/savepoint; preserve existing lines.

**Role/task:** Assigned workers can see NP outside this delivery; administrator
can select orders to include. ARRIBADO/count can add without rewinding. EM/location
reopens only the selected arrival with an administrative audit, preserving other
arrivals' validation evidence. Later stages/closed/annulled
arrivals require the existing explicit administrative reopening first. New order
starts at verified0/no scan; the user must scan or correct physical quantities.

- [x] Reproduce frozen plan hiding a new source NP with synthetic tests.
- [x] Add candidate visibility, state-bound administrative inclusion and route.
- [x] Add mobile/desktop disclosure, confirmation/reason, single flight and errors.
- [x] Verify permissions, stale/race rejection, untouched previous reads/packages,
  late-stage guards, partial arrival semantics, and prepare a separate PR.

Verified:1048 Linux unittest OK/2expectedskips;38 focused tests after preserving
the original validation sample. Browser320/393/1366px with role separation,
checkbox/reason, one POST, error recovery and44px targets. One bounded public
auxiliary review; parent stage summarizes reopened work, other arrivals and
their validation evidence stay intact. Actual case preview ran read-only and
found the missing candidate; no production inclusion or receipt was executed.

No real operational rows in tests/public code. No production DML, install,
service/tunnel/manual WMS changes or physical receipt inferred from Excel.
