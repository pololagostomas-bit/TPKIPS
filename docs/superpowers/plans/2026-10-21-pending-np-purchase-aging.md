# Pending NP And Purchase Aging Implementation Plan

> Execute inline using executing-plans; one bounded text-only auxiliary advises.

**Goal:** Carry confirmed missing NP into the next arrival and retain purchase-control aging with a downloadable audit history.

**Architecture:** Keep Python/SQLite and vanilla JS. Read physical count evidence across valid attentions without changing quantities or DHL packages. Extend the existing private purchase-alert SQLite, worker and admin page; never query the operational database for this history.

**Rules:** Missing is explicitly confirmed, not a forgotten scan. One accumulated NP counter, with prior positive saved reads only. A deferred balance appears in the arrival queue even while received items progress. Existing administrative closure remains authoritative. Normal purchase issues require IP plus PRE or more than five total OC digits. Exact trimmed, case-insensitive IP X excludes the row from both rules. OV beginning COT with any OC or IP is a separate grave issue, including a five-digit OC. No source writes or new real mail during development.

**Aging:** Calendar time from first successful observation, not claimed creation date. Normal identity is issue type + normalized IP; COT adds normalized OV (or OC when IP is blank). PRE edits and row reorders do not reset an active episode. Distinct issue types retain their own clock. A complete successful snapshot can end an episode; absence means no longer observed, not proof SAP or an approved OC was verified. Failed/missing-sheet snapshots do not resolve anything. Excluded sheet histories remain available. Reappearance starts a new immutable episode.

**Frontend:** Existing WMS design contract; 50-row admin history, status/severity filters, CSV download single-flight; mobile reflow and readable dates/elapsed hours. Viewing history never downloads Excel or sends mail.

## Tasks
- [x] Reproduce partial arrival projection and cumulative-counter gaps with synthetic tests; add purchase X/COT/lifecycle regressions (RED).
- [x] Implement count evidence and deferred queue projection; keep per-order identity and selected-attention edits, verify next-arrival completion (GREEN).
- [x] Extend purchase parsing and private episode storage; persist only complete observations, preserve delivery dedupe and uncertainty guards.
- [x] Add admin paginated history and formula-safe CSV; test authorization and mobile error/download paths.
- [x] Run targeted/full clean-candidate regressions, browser screenshots, secret and diff checks; prepare one PR against main, no merge/deployment.

## Verification
Clean candidate: 889 unittest, OK with two planned skips, 136.631 seconds.
24 browser contracts, partial/fallback/correction real-backend flows, cumulative
next-arrival progress, and purchase-history filters/download/errors passed at
320/393/1366 CSS px (partial correction also873px landscape and200% text).
Two independent P2 findings were reproduced RED and fixed GREEN: excluded-source
evidence survives payload updates, and refreshed prior-read flags revoke stale
progress without replacing drafts. Reviewer rechecked, no remaining P1/P2 in
those fixes. Secret scan and diff/syntax checks passed. Hardware not certified;
no production writes, real mail, app/tunnel restart, deployment or manual change.

## Review Focus
- Prefilled quantity is not proof of a scan; annulled attentions cannot contribute.
- Multiple OV for the same NP remain separate orders; missing/read groups cannot duplicate.
- Deferred stock already assigned to a new physical attention is not still awaiting a truck.
- PRE rename must retain first observation; COT resolution must not end another issue's clock.
- Excel errors/missing sheets must not mass-resolve; CSV cells cannot execute formulas.
