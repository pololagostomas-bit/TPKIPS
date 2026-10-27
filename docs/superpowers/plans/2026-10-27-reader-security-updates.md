# Reader security update implementation plan

**Goal:** Publish a tested security PR for the maintained reader, keeping the
approved deployment/manual app and Microsoft account unchanged until approval.

**Architecture:** Remain on Python3.12 with its security patch. Resolve MSAL and
cryptography together; lock every application package with artifact hashes.
Use one bounded XLSX reader shared by existing importers and defusedxml, without
changing workbook semantics, receipts, quantities or stock. Build and test Linux
with disposable fixtures and no production mounts, tokens or external sends.

**Stack:** Existing Python/openpyxl/MSAL/requests/SQLite and Docker; no frontend
framework change. Evidence: private version audit dated2026-10-27.

## Constraints and review focus

- Pin published versions/digests; reject missing hashes and source builds.
- Update MSAL1.39.0, crypto50.0.2, requests2.34.2, certifi2026.10.23,
  pip26.2.2; retain openpyxl3.1.5/waitress3.0.2 and add defusedxml0.7.1.
- Python3.12.16 includes Expat2.9.0; verify the actual built runtime.
- Keep old Microsoft cache/Graph/mail grants; no login, refresh or send to real
  accounts in QA. Existing synthetic OAuth tests cover the contract.
- Excel validation before parsing/writes; limit compressed50MiB, expanded512MiB,
  each member128MiB,10000entries. Preserve stricter location-master limits.
- Streams must remain usable; valid formulas/data_only/read_only behavior stays.
- Cloudflared version/digest for future reader maintenance only; Docker Engine
  and frozen manual maintenance stay separate, documented and uninstalled.

## Task 1 — Runtime and locked dependencies

- [x] Record clean baseline suite and verify official image tags/digests.
- [x] Create requirements.in, generated hashed requirements.txt and hashed
  requirements-build.txt; update main Dockerfile to patched pinned base and
  binary-only hash-checked installation, followed by pip check.
- [x] Resolve/generate inside Linux; audit all installed runtime packages.

## Task 2 — Bounded Excel loading (RED then GREEN)

- [x] Add tests/test_excel_security.py for normal bytes/path/stream workbooks,
  oversized expanded member/archive/entry counts, corrupt ZIP and XML entities.
- [x] Implement backend/services/safe_excel.py::load_workbook(filename,*args,
  **kwargs), forwarding all openpyxl options after archive validation.
- [x] Route app.py, reception.py, purchase_alerts.py and location_capacity.py
  through that reader. Preserve all earlier unrelated working-tree edits.
- [x] Test that a rejected operational import preserves existing SQLite data.

## Task 3 — Linux verification and reviewable delivery

- [x] Build a candidate image, check Python/SSL/Expat/dependency versions and
  health with disposable volumes. Run complete suite and targeted Microsoft/
  import/report/labels tests without external account/network operations.
- [x] Verify lock/hash integrity and pip-audit result; update future-reader
  tunnel image pin. Add PR security check without auto-merge/deploy.
- [ ] One bounded independent review, fixes/tests, redacted secrets/diff check.
- [ ] Commit selected files, push and reuse/create/attach PR; no merge/install.
- [ ] Record evidence and next approved deployment steps in focused memory.

## Ledger

- Authorized2026-10-27 after the version audit. Branch
  codex/reader-security-updates-20261027 starts at approved main46dd25b.
- Existing linked worktree reused. Dirty resilience work remains unstaged;
  Power BI preparation remains on its own local branch.
- Baseline1037testsOK/13skips. Candidate1046testsOK/2skips in130.107s on Linux;
  initial QA image lacked Node, corrected in a separate test-only image. No
  Node added to production. Installed19packages audit0known advisories; health
  and login200 in read-only/network-none container, offline cache+RSA/JWT OK.
- Bounded Antigravity text review used only proposed public/synthetic code.
  Claimed stream-leak issue was not reproduced: ZipFile does not own caller
  streams; normal/failure ownership tests pass. Deferred entity exceptions
  inherit ValueError and are rejected in the existing transaction/error path.
  Archive bounds use declared sizes plus Python3.12.16 ZIP safeguards; not a
  certification against all resource exhaustion or all malformed workbooks.
