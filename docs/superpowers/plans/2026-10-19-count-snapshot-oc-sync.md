# Count Snapshot And OC Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the selected receipt attention's NP identities and planned quantities stable while documentary imports continue updating OC, FR and EM.

**Architecture:** Reuse reception_attention_lines and its planned_qty rather than stopping imports or queuing workbooks. Keep reception_lines as the latest documentary source, reconcile PRE/OC on the existing stable ID, and scope operational detail, accounting links, writes and difference alerts to the selected attention. Preserve compatible legacy work before replacing its documentary source.

**Tech Stack:** Existing Python, SQLite, unittest, openpyxl, HTML/JavaScript and local Playwright.

**Spec:** Owner-approved first option on 2026-10-19; docs/reception-import-line-identity.md.

## Global Constraints

- Reader only; frozen manual deployment and running services untouched.
- No production SQL, real mail, corporate workbook, secret or deployment change.
- No merging different OV/IP identities by NP or Excel row number.
- Preserve PR30's worker/admin package permissions and unrelated local changes.
- Use disposable databases; only selected changed files enter the commit.

## Review Focus

- A changed Excel quantity must not change the expected quantity of an existing attention or generate a false discrepancy.
- A new source line must not become work for an already-created attention, even through a manual POST without scan_np.
- Two legitimate orders for one NP must remain distinct through PRE/OC updates and row reordering.
- A later arrival must use the current documentary balance, not a stale globally frozen source quantity.
- Legacy active work without attention rows must retain its counted quantity and scan/location evidence when its source is refreshed.

## Task 1: Pin Receipt Attention Boundaries

**Files:** backend/services/reception.py; the system-report route only in backend/app.py; physicalLineCells only in frontend/templates/reception.html; tests/test_reception_count_snapshot.py.

**Interfaces:** Keep import_reception_workbook and reception_detail signatures. Selected attention planned_qty is authoritative for operational expected_qty. New documentary lines remain outside the selected attention. update_reception_line_quantity rejects every foreign-attention line, including non-scan requests; discrepancy messages compare against the attention plan.

- [ ] Add synthetic regression tests for PRE/OC plus changed quantities, legitimate repeated NPs, source-only lines, selected/other arrivals, documentary FR/EM, legacy work and false notifications.
- [ ] Run the tests against the unchanged source and record the expected failures.
- [ ] Make minimal changes in reception.py; keep source imports current and preserve verified work.
- [ ] Run the focused tests and existing identity/accounting/scanner/permission regressions.
- [ ] Preserve legacy zero/nonzero counts without inventing scan markers and carry existing transfer confirmation; test the actual renderer.
- [ ] Export the explicitly selected attention's plan and verified quantities; reject foreign attention IDs and keep unrelated local app.py edits out of the staged patch.

## Task 2: Verify And Publish The Same PR

**Files:** docs/reception-import-line-identity.md and private verification evidence outside Git.

- [ ] Document source versus operational quantities, legacy limits and no automatic historical cleanup.
- [ ] Export the committed baseline plus only this task's edits into a clean QA candidate; run full unittest discovery there, excluding other tasks' uncommitted work.
- [ ] Exercise the selected-attention UI/API at mobile and desktop widths with synthetic data; verify OC changes once and new source lines do not appear under FR work.
- [ ] Obtain a fresh-context review, resolve important findings and rerun relevant checks.
- [ ] Stage only task files, scan the selected diff for secrets, commit and push the existing PR30 branch without force.
- [ ] Verify the remote head and updated PR description; do not merge or deploy. Save focused private project memory.
