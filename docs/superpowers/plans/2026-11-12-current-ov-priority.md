# Current OV priority implementation plan

> Execution: inline with executing-plans; one external review of the final candidate.

**Goal:** A current real OV replaces its earlier quote when a single matching blank-OV documentary antecedent also exists.
**Architecture:** Reuse the existing stable line ID, alias map, legacy relation and source eligibility. Match before writes; do not merge physical records.
**Stack:** Existing Python/SQLite; no dependencies or frontend changes.
**Spec:** `docs/reception-import-line-identity.md` and owner's current-source OV priority instruction.

Constraints: reader only; no production writes, merge, deployment or restart. Public/synthetic fixtures only. Current source OV wins, never the largest number or newest internal ID. Distinct real/current orders remain separate.

## Work and verification

- [x] Add a regression for one prior quote plus one blank OV, both with saved work, becoming one current real OV. Observe failure first.
- [x] Add a narrow same-sheet/BL/IP/OC/NP, same-quantity/description antecedent match. Reuse legacy audit/exclusion; preserve all physical IDs and values.
- [x] Cover reimport, moved rows, different quantities/descriptions, multiple quote/blank/current orders and prior real OV guards. Verify detail/report use current OV.
- [x] Run focused regressions and real-current-cut preflight against a readonly planning connection; never import into production. Exact final logs live outside Git.
- [ ] Delivery gate: commit selected files, review exact BASE/HEAD externally, publish a PR and verify its checks. Approval/installation remain separate; receipt outside Git records the result.

Review focus: real orders not collapsed; no guessed match from row position; no physical quantities/locations rewritten; removed source data not resurrected; repeat import has no duplicate audit.
