---
description: "Architectural decisions and rationale"
---

# Decisions

- [2026-09-06 04:12] La unidad de trazabilidad física del WMS es NP + lote interno de recepción, no número de serie individual.
- [2026-09-06 04:12] El lote interno se genera en recepción a partir de BL/AWB + OC/IP + NP y debe conservarse aunque cambie la OV asociada.
- [2026-09-06 04:12] El WMS debe reservar cantidades por OV y validar el lote reservado durante el picking.
- [2026-09-06 04:12] El proyecto se organiza como un monorepo con backend, frontend, data, docs, infrastructure, qa, tests y ui-design.