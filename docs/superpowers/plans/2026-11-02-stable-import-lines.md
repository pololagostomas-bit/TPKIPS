# Stable import line references implementation plan

**Goal:** permitir la revisión PRE → OC con antecedentes incompletos sin duplicar el pedido ni mover trabajo físico.

**Architecture:** conservar `reception_lines.id` como numeración interna. Un registro de claves documentales anteriores apunta a ese mismo ID; la fila Excel es solo evidencia complementaria. Conciliar únicamente un antecedente sin IP de la misma hoja/BL/NP/OV/posición histórica/cantidad cuando el otro antecedente tiene la IP vigente y una PRE, y solo hay un pedido vigente en ese grupo. Mantener ambos registros físicos; señalar el antecedente documental sustituido sin sumar, borrar o transferir cantidades. Los cruces reales siguen bloqueados.

**Tech stack:** Python/SQLite, sin dependencias nuevas. Reutiliza la exclusión de asociaciones no vigentes y regularización ADMIN del PR55, ya fusionado; este PR se dirige a main. No cambia Excel, servicios ni datos productivos al publicar.

- [x] Reproducir legado sintético, desplazamiento de filas, repetición legítima, cambio inverso, conservación física y diagnóstico cloud.
- [x] Implementar registro estable, prevalidación sin escrituras y persistencia atómica/auditada.
- [x] Distinguir conflicto de identidad de formato sin publicar celdas en estado/historial.
- [x] Ejecutar regresiones, preflight de solo lectura y dos importaciones en copia privada aislada; candidato limpio Linux y revisión acotada.
- [ ] Escanear/publicar PR a main, adjuntar, comprobar CI y guardar memoria. Sin merge/despliegue ni limpieza productiva.
