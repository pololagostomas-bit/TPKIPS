# Purchase follow-up and scan audio implementation plan

**Goal:** Follow requests from 2026-10-01 inclusive, newest request first, attach
recent and historical purchase episodes (including resolved ones), and verify
package/NP scan feedback on the reader WMS.

**Architecture:** Keep episode identity, clocks and complete observations in the
existing private purchase SQLite. Apply date scopes only to presentation and mail
eligibility. Share one workbook builder between admin download and Microsoft mail.
Unknown dates remain explicit; mixed-date cases retain each source in its scope.
Keep COT severity sections, recipients, approved text, schedules and X exclusion.

**Stack:** Existing Python/openpyxl, SQLite, HTML/JavaScript and Web Audio.

- [x] Add failing tests for inclusive cutoff, request-date ordering, resolved
  history, mixed/missing dates, XLSX attachment and download, and alert dedupe.
- [x] Implement scoped history/mail and bounded, formula-safe workbook export.
  Default admin scope is recent; full workbook includes every recorded status.
  Retain legacy CSV for existing clients. No real email during validation.
- [x] Exercise real browser audio after keyboard/camera gestures, plus accepted,
  rejected, duplicate and late scan results. Fix only reproduced failures.
- [x] Verify focused tests and clean staged-source suite; review and prepare a
  separate PR. No merge, production changes, services or manual WMS changes.

Verified: Linux 1052 unittest tests, 2 expected skips; 33 audio/truck/browser
checks; purchase UI and mail at 320/393/1366 CSS px; authenticated real XLSX bytes
and denied worker/anonymous access. Existing sound behavior passed; no sound
rewrite. Real handheld speaker/volume and Outlook delivery are not certified.
