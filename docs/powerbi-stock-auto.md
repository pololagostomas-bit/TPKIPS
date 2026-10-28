# Automatic reader stock from Power BI

The reader checks its selected Import-mode model every300seconds, independently
of the Excel polling interval. The owner manages the upstream BI refresh cadence.
The existing Microsoft account/cache supplies a delegated Dataset.Read.All token;
no Graph token fallback, new interactive login, secrets or destinations in Git.

Opt in only on the reader with POWERBI_STOCK_ENABLED=1 and a private JSON mapping
at POWERBI_STOCK_CONFIG_PATH (default next to the WMS DB, powerbi-stock.json).
Mapping: dataset_id, optional report_id/workspace_id, table, columns containing
warehouse/item_code/description/location/quantity, storage_mode=Import and
quantity_kind=physical_by_bin. Destination identifiers/column mappings stay on
the server. A synthetic example belongs in tests, never the actual tenant.

Fetch only after a new completed model refresh. Validate source timestamps,
count distinct projected rows before download, enforce bounded full JSON bodies,
reject all API200 error/limit rowsets and inconsistent counts, then recheck the
refresh marker. Empty, truncated, conflicting or changing snapshots keep the
last valid cut. No source refresh, schedule, roles or SAP writes are performed.

Exactly warehouse01/1 participates. Preserve text identifiers/leading zeroes;
stock is per bin, not a warehouse total repeated per location. Identical repeated
bins are idempotent, conflicting duplicates fail. Choose greatest positive stock
location, retain all positive alternatives, and keep no-stock destination blank.
Never overwrite count/putaway destinations or reception quantities/states.

Power BI article codes are authoritative. Keep punctuation, internal spaces and
leading zeroes. Different source codes stay separate even when they collide in
the older punctuation-stripped WMS key. Store exact per-article cuts and bins;
the legacy inventory row is only a compatibility index with zero stock/no bin
for colliding codes. Stock summaries, catalog/labels, operational reservations,
movement adjustments and commitments resolve the exact source article. Unknown
spellings get zero, never another article's stock. Existing allocation/history
rows are retained; exact item_code scopes their use for a BI cut. Manual cuts
retain their previous matching contract and hide old BI per-bin data.

Activate a complete cut in one short SQLite transaction, after all network and
normalization work. Preserve allocations, movement/reconciliation history, other
warehouses, user catalog edits and newer manual cuts. Record source kind,
fingerprint, model refresh, actual cutoff and import identity. Record check/error
history without raw model responses, identifiers, tokens or item rows in logs.
Disable automatic Stock Excel for an opted-in BI source; manual fallback remains.

Use one bounded BI background thread started from the existing cloud startup,
not an HTTP/render side effect. A separate loop is required because an Excel
network timeout must not postpone the300second BI schedule. No service/process
or library is added. Keep Excel's own interval and support Excel being disabled.
Status reads never query Microsoft. Show checked/last success/BI refresh/WMS cut
separately, including source errors and stale state, in the existing admin panel.
Positive alternate bins are available in inventory; labels retain their current
default-location and stored count destination rules. No framework/library added.

Release requires PR approval/merge followed by an approved reader install and
private mapping/activation. No production DB or source switch during development.
The separate manual deployment remains frozen.

API contracts: [Execute Queries](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries)
and [Refresh history](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/get-refresh-history).
