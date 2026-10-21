# Purchase Alert Observation History

The reader's existing admin page, Alertas de compras / OC, includes an aging
history and CSV download. Viewing or exporting this history only reads the
private purchase-alert SQLite; it does not download Excel, send mail, query SAP
or access the operational WMS database. Existing worker scheduling and Microsoft
authorization are reused. No additional scheduler or mail integration is needed.

## Rules

- IP exactly X after trimming and case folding excludes the entire row from both
  rules. X123 is not excluded. Existing excluded archive sheets stay excluded.
- PRELIMINAR / REGULARIZAR: IP is present and the OC contains PRE or more than
  five digits in total. Two five-digit references still satisfy the digit rule.
- COT / GRAVE: OV starts with COT and has any OC or IP, even a five-digit OC.
  This is an independent rule. One order can have both issues and both clocks;
  severity identifies the higher-priority issue, not a physical WMS status.
- Nothing in these rules writes to the workbook, changes SAP or closes a BL.

## Clock And Identity

The clock starts at the first successful observation after installation, not
the unknown original creation time. It measures continuous calendar hours,
independently of the operational BL SLA calendar. Revisions update last observed
time; resolved periods keep a frozen end time and remain downloadable.

An ordinary issue is identified by normalized IP, not sheet row or PRE text.
Changing PRE while the same IP remains irregular does not reset its clock.
All OC values observed for that IP in a revision are retained together. COT
issues additionally use normalized OV; without IP they use OC plus OV. If IP
itself changes, there is no stable source identifier to prove continuity, so a
new issue may be created. Reappearance after resolution starts a new episode.

A completed, validated revision can end an episode when it no longer satisfies
the rule or is absent from the checked sheets. This is an observed end, not
proof of an approved OC, physical transfer or SAP verification. Resolution is
detected at the next successful revision, not the exact instant of an Excel edit.

Failed downloads, invalid formulas, missing previously recognized sheets and a
missing OV column on a sheet with open COT issues do not resolve previous issues.
Deliberately excluded sheets retain their history without claiming correction.
If a case spans checked and excluded sheets, the excluded evidence is retained
as Hojas sin revisar; correcting only the checked sheet cannot resolve it.
Old history is not reconstructed from mail or guessed from spreadsheet dates.

## Access And Download

Only administrators can view or export. Filters cover pending/resolved/all and
grave/ordinary levels, with 50 rows per page. Dates display in Lima; CSV timestamps
are UTC. CSV includes issue, reference, source sheets, detection/observation/end,
calendar hours and resolution explanation. Formula-like cell values are escaped;
UTF-8 BOM supports Excel. Downloads are single-flight in the page and capped at
50000 filtered episodes, keeping generation separate from the production DB.
