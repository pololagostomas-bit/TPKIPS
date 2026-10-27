# Reader: EM labels and count destinations

Scope: barcode-reader app only. The separate manual deployment is frozen.
Changes require an approved, merged PR before the reader image is installed.

## Saved Quantity On Receipt Stickers: 2026-10-15

Inicio de conteo and EM share the same receipt label: Cantidad appears beside
BL/AWB in the lower block, with a bold number next to the Data Matrix. It uses
the saved selected-attention verified quantity, never planned/expected or SAP
stock. No additional input or confirmation is required. Zero, another attention
and invalid quantities do not produce a misleading receipt label.

Existing one-label NP/OV/customer/destination/normalized-brand grouping is kept.
The printed quantity totals the distinct source lines represented by that label;
a repeated source ID contributes only once. Different OVs keep their own labels
and quantities. This aggregation is print presentation, not a database merge or
a physical package/unit quantity. Source rows and saved counts are not changed.

The confirmed TE2004x3 landscape format, prominent manufacturer, equal NP/OV,
description, customer, Data Matrix and7mm blank manual location remain intact.
The quantity field participates in the fit guard; overflow still blocks print.
Generic Inventory labels remain without a receipt quantity: stock is not the
quantity of a particular newly labelled package. No stock snapshot is invented.

## Operational Rules

- Receipt stickers show the actual OV reference, `Stock` for existing no-OV/stock
  markers, or `Cotizacion` for an explicit COT/cotizacion reference. Administrative
  placeholders such as `POR REG` or `POR REGULARIZAR` print an empty OV value;
  they do not become a fabricated OV, stock order or quotation. Customer is
  preserved except for the existing `Para stock` wording on stock labels.
  This is print-only formatting after grouping: original source references,
  customer, quantities, distinct orders, alert rules and audits are unchanged.
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
- Updated owner rule, 2026-10-27: Location permits entering/changing the final
  destination and **Guardar** per received NP. It saves partial progress without
  finishing the stage or losing other drafts. Every received NP needs a nonempty
  saved destination before validation, including no-stock/manual-label cases.
  A blank box remains allowed on count/EM stickers; it no longer substitutes for
  recording the actual later putaway destination. Positive-stock lines still
  need a count destination before EM. Other arrivals/absent NP are not putaway
  requirements for the selected arrival.
- Final-location fields accept a physical keyboard reader: focusing selects the
  suggested value so scanning replaces it; Enter saves only that NP. The camera
  icon reads one location into that NP's draft and focuses Guardar, without an
  automatic write or continuous scanning. The existing local decoder reads the
  rack Data Matrix, QR and supported barcodes. Standard AIM scanner identifiers
  are removed from the stored location; empty/overlong/control-character values
  are rejected. Manual entry stays available if the camera is denied. A BL,
  arrival, stage or field replacement invalidates the previous camera session;
  no scan is routed through truck packages or NP quantities.
- The same Location NP search accepts the physical reader/Enter or its camera
  icon to choose the NP before reading a destination. Lookup is exact after
  whitespace/case normalization and optional scanner wrappers, preserving leading
  zeros and punctuation. Only positive received lines of the chosen arrival can
  be selected. Distinct orders for the same NP remain separate, with an explicit
  OV/Stock choice (IP only if needed to distinguish equal OVs). A partial search,
  absent NP or stale choice never selects another row or counts anything. After
  a successful unchanged save, focus returns to the NP field for the next scan,
  unless the operator has already moved to another field or changed the draft.
- A nonconforming location validation returns to count, retains quantities and
  destinations, clears that attention's location confirmations and audits the
  return. Correct there, then repeat EM, location and validation. Administrator
  reopening and correction permissions remain in force.

## Filtering And Printing

Both count and location offer "Buscar NP en esta BL". Matching ignores spaces
and case and allows partial NP searches. Filter state belongs to the BL,
attention and stage. Hiding a row never deletes its draft or excludes it from
the save action. Location saves affect only the chosen source line and retain
the other rows' drafts, including filtered-out rows. Duplicate NPs with different
OVs remain separate.
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
or SAP suggestion is captured. Location payloads can now change the address in
UBICACION for assigned reception workers/admin, retaining audit and stage checks.
The existing final_location_confirmed field records completed saving; no schema
rename or historical backfill is required. Optional previous_location and
previous_confirmed protect new clients from overwriting another user's change.
Late responses update only their original row/arrival; they cannot replace a new
BL on screen. Saving/unsaved changes block UI advancement; the server independently
requires every received NP's saved, nonempty location. No stock/SAP movement or
temporary receipt-location change is made by this action.

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
inputs or altering saved values. Source line ID, OV, IP, reference stock location
and stock amounts are optional details controlled by the user's show_guidance
preference, hidden by default. The filter reports results and distinct NP count.
The same NP in two
different OV/IP lines is not a duplicate to delete or merge. Scanning that NP
still requires choosing the correct source line before saving its quantity.

The repeated-search browser regression asserts unchanged unique source line
IDs, actually hidden rows on mobile, retained quantity/location drafts and one
search input and scanner. A reported duplicate beyond those legitimate lines
must be traced through its BL/NP source and attention IDs; no source rows are
deleted or auto-consolidated by search.

The scan result keeps NP, description and required quantity; zero stock is shown
only as a status, not a stock balance. The quantity starts with the existing
integer count/draft (normally the full planned amount), preserving corrected or
saved zeroes. If no count exists, use the current attention's planned integer,
never stock or a shipment-wide remainder. Fractional/unsafe values are not
rounded into an invented integer. Scanning never submits a save automatically.
NP save confirmations do not expose internal line IDs.
The full-list quantity renderer also refuses implicit truncation. Bulk Save
rejects empty, fractional and unsafe values instead of converting an empty
field to zero; single-NP and bulk validation now agree on whole quantities.

When an NP has multiple legitimate order rows, the scanner cannot silently pick
one. Each choice initially shows NP, description and required quantity; opening
it reveals OV/IP and its explicit selection button. This is an on-demand business
decision, not a technical ID displayed in the normal single-result workflow.
Line IDs in those expanded choices still obey the user's optional-help setting.

The editable destination label is now `Ubicacion por defecto`, consistently in
the scan result, full count table and later read-only confirmation. This is a
display-name correction: storage remains the per-attention count-location
snapshot; edits stay in Inicio de conteo and do not change the SAP stock master.
The optional `Referencia SAP` is kept separately when help is enabled. No-stock
destinations remain empty, not prefilled with a fake address.

## Manufacturer Logos And Print Format

Reader labels use the brand of the same Importations line, not a shipment-wide
guess or a stock brand from another source. Display-only normalization maps
regional qualifiers such as BOBCAT EUROPA/INDIA to BOBCAT. Catalog: KALMAR,
TRITON, CROWN, HYUNDAI, BOBCAT, KUBOTA, HOWO, TVH, HUSQVARNA and LIEBHERR.
Unknown or ambiguous multi-brand text is preserved, without choosing a logo.
The raw stored brand and imported row identities remain unchanged.

The brand logo is the first block, followed by NP, description, barcode, OV/BL,
customer and destination. Customer/destination share the lower row to use the
horizontal label without wasting the bottom area. NP and OV share the same font
size on each label:20pt initially, reduced together to at least16pt only if the
configured physical paper needs it. Locations without stock remain blank with
a10mm writing box.
Label identity includes NP, OV, customer, destination and normalized brand;
different legitimate OV/brand/destinations never lose their labels.

The owner confirmed TSC TE200 stock of4x3 inches:101.6x76.2mm, horizontal.
This preset is the new default; editable dimensions accept tenths of a millimeter.
An explicit paper selector can restore the preset or use a custom size. The old
unconfirmed150x100 browser preference never silently overrides the TE200 default:
it remains available as an explicit previous-format option. Version2 preferences
preserve subsequently chosen custom sizes and orientation between popups.
Settings are local numeric preferences, not business data. The app print button
waits for logos/fonts and refuses clipping; an unavailable logo or insufficient
paper shows an error. One label per page,2mm page margin and1.5mm internal padding.
Fit checks include the bottom padding rather than accepting rounded scroll-height
overflow. Preview-only page heights use a CSS variable, not an inline height that
would override the print layout and clip a long customer's final lines.
Only the preview is scaled to the screen; printed font sizes use physical units.
Code39 keeps the existing encoding and a10-narrow-bar quiet zone on both sides.
The SVG fills its reserved barcode area without squeezing its height to the
source aspect ratio. No caption or logo overlaps the quiet zones.

TE200 is a203dpi/8dots-per-mm printer according to the
[official TSC specification](https://apac.tscprinters.com/en/product-comparison?skus=TE200).
Browser print tests rasterize the physical PDF at203dpi and decode the synthetic
NPs independently with ZXing-C++; this does not certify actual head calibration,
ribbon, scaling, driver margins or hardware scanner performance. Select4x3-inch
stock and100%/actual size in the printer driver, without browser headers/footers.

Logos stay private in `<database directory>/brand-logos/`, or the explicit
`WMS_BRAND_LOGO_DIR`. One lowercase PNG/JPG/JPEG per catalog brand. Store outside
Git/images with database files excluded from the public repository; a persistent
volume is required across image upgrades. The source Excel is never published.
Back up this folder privately as well as the DB; the DB backup alone does not
include manufacturer assets. Directory0700/files0600 owned by the application
user. Source images are preserved, not cropped, recolored or regenerated.

`/api/reception-brand-logo?brand=...&v=...` requires Reception access. Allowed
catalog keys only; no arbitrary paths, SVG or remote URL fetching. Ambiguous
files, oversized files and unsupported signatures are not served. Fingerprinted
URLs and stale-version rejection prevent reuse of an old asset after a change;
the API wrapper applies no-store. A missing manufacturer logo never uses another
brand's image. The server bounds and caches file reads; printing does not fetch
the Excel or call DHL/Microsoft.

`scripts/extract_brand_logos.py <private.xlsx> <private-output-directory>`
extracts the ten local in-cell images from MARCAS!B6:E15. It follows the cell's
metadata and the named `_rvRel:LocalImageIdentifier` structure key, as specified
by [Microsoft's local-image specification](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/aac1e2a6-7072-4e66-b1de-f20b8bf63318),
not file order or the cached #VALUE! cell value. No inventory import, workbook
rewrite, external images or macros. Incomplete mappings fail before writing;
existing different assets are not overwritten automatically.

EM reference rows carry source IDs. The display removes only repeated instances
of the exact same source ID within a FR/IP card; distinct source rows and OV/IP
quantities are preserved. This defensive guard does not prove the cause of an
unreproduced production duplicate. An owner-provided example was traced to two
distinct imported occurrence keys, not repeated DOM rows: an older second
occurrence remained after the workbook returned to one occurrence. Imports
update their present keys; they do not delete prior worked rows removed from
Excel. Search, FR cards and other line-based views correctly reflected those
stored rows. A targeted owner-authorized correction retained the current first
occurrence and its confirmed quantity, with a private SQLite backup and full
removed-row/attention-row archive in reception history. No blanket SKU merge,
quantity summation or deletion of other legitimate OV/IP lines is performed.

Coverage: test_reception_brands.py, em_labels_browser.cjs (five viewports, both
orientations, ten real private logos, stale-logo/overflow errors, no-stock box)
and reception_items_browser.cjs. Browser PDFs validate3/3 label pages and10 logo
pages with the selected physical dimensions. `verify_label_pdf.py` checks page
sizes, complete long customer text and independent Code39 decoding at203dpi.
Its pypdf/Pillow/ZXing-C++/Poppler dependencies are QA-only, not server requirements.
Actual thermal printer alignment
and scanner readability still require physical acceptance after approved deploy.
