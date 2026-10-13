# Reader: EM labels and count destinations

Scope: barcode-reader app only. The separate manual deployment is frozen.
Changes require an approved, merged PR before the reader image is installed.

## Operational Rules

- The EM action "Imprimir etiquetas por NP" prints the NP barcode, description,
  OV number, customer, BL and the destination recorded during count.
- Customer comes from the same row's `Cliente` column in Importations, as
  clarified by the owner after PR17. It is stored per reception line, not
  derived from the OV/orders cut or another row of the BL. Empty/missing
  `Cliente` stays blank even when the OV cut has a name. Unknown or combined
  OVs do not prevent printing a customer actually present in Importations.
- At count start, an NP with positive SAP stock uses its reference destination.
  The operator can correct that destination during count. An NP without stock
  starts blank, leaving a bordered box for handwriting on the printed label.
- Save destination and the no-stock/manual choice per arrival attention and
  line. Subsequent stock cuts and repeated quantity saves do not replace a
  saved destination or turn a saved manual blank into an unknown address.
- Location shows that saved value as readonly and only allows confirmation.
  No-stock/manual blanks can be explicitly confirmed without fabricating a bin.
  Positive-stock lines need a destination before EM and location confirmation.
- A nonconforming location validation returns to count, retains quantities and
  destinations, clears that attention's location confirmations and audits the
  return. Correct there, then repeat EM, location and validation. Administrator
  reopening and correction permissions remain in force.

## Filtering And Printing

Both count and location offer "Buscar NP en esta BL". Matching ignores spaces
and case and allows partial NP searches. Filter state belongs to the BL,
attention and stage. Hiding a row never deletes its draft or excludes it from
the complete-save action. Duplicate NPs with different OVs remain separate.
The scanner still requires explicit line selection for an ambiguous NP.

Labels include only lines with a positive count in the selected attention.
They deduplicate by NP/OV/customer/destination, not NP alone. Text is escaped
and wraps; backgrounds are white and no-stock boxes have no placeholder text.
The 90 mm label width retains the existing paper-print workflow and leaves at
least 10 mm of vertical space for the destination. No fixed thermal-printer
height, hardware support or physical barcode readability is claimed.

## Compatibility

Existing databases need the Importations workbook reprocessed after this
correction is installed: the previous importer discarded `Cliente`. Use the
existing administrator action `Cortes diarios > Forzar carga`, or upload the
Excel again from Reception. The new column alone cannot recover discarded
names. Normal cloud polling still skips unchanged file hashes; it picks up
customers automatically when a new cut is actually imported. No connection,
OAuth session or business-rule changes are needed for this correction.

Schema additions are idempotent and do not backfill or rewrite historical
destinations. Old saved line-level destinations remain readable until an active
attention captures its own snapshot. Opening a historical detail does not write
locations. Old quantity clients can omit `count_location`; the existing choice
or SAP suggestion is captured. Old location payloads may repeat the same address
but cannot change it, including when submitted by an administrator.

Source: `backend/services/reception.py`, `frontend/templates/reception.html`,
`frontend/static/reception-np-scan.js`.

Focused regression coverage: `test_reception_count_locations.py`,
`test_reception_final_locations.py`, `test_reception_np_scan_ui.py` and
`reception_items_browser.cjs` with `support_reception_items_server.py`.
The browser fixture creates a new disposable database; never point it at
production. Corporate APIs, actual printers and physical Android scanning
require separate acceptance testing.

## NP Search Identity

Search only hides existing rows, without appending lines, rebuilding quantity
inputs or altering saved values. Count rows show source line ID, OV and IP;
the filter reports both line count and distinct NP count. The same NP in two
different OV/IP lines is not a duplicate to delete or merge. Scanning that NP
still requires choosing the correct source line before saving its quantity.

The repeated-search browser regression asserts unchanged unique source line
IDs, actually hidden rows on mobile, retained quantity/location drafts and one
search input and scanner. A reported duplicate beyond those legitimate lines
needs its BL/NP example; no source rows are deleted or auto-consolidated.
