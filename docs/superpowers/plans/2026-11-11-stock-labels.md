# Stock Labels Implementation Plan

> Execute inline with one coordinator. Follow executing-plans; use one external Gemini review before acceptance.

**Goal:** Add bulk stock labels inside Inventory, one label per distinct NP.

**Architecture:** Reuse inventory_label and the inventory print profile. Parse uploads without operational imports; resolve short batches on query-only connections. Keep the existing Python/HTML/JavaScript stack.

**Spec:** docs/inventory-stock-labels.md.

## Tasks

- [x] Add failing parser, batch access/identity and shared-renderer regression tests.
- [x] Add backend/services/inventory_stock_labels.py and two bounded POST routes in backend/app.py.
- [x] Add Inventory tab and scoped inventory-stock-labels.js/css; reuse the reception label renderer for arrays.
- [x] Verify real browser flows, errors, mobile layouts, print dimensions and Data Matrix. Use synthetic data only.
- [ ] Commit selected files, review exact BASE/HEAD externally, resolve findings, publish PR without deployment.

## Checks

Ignore quantities and duplicate rows; preserve distinct punctuated codes and leading zeros. Reject invalid roles, formula NP and oversized inputs. Missing codes cannot print. Existing single-item and reception labels must keep their behavior. No operational writes or private assets.
