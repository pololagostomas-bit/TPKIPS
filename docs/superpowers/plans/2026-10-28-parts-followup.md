# Parts Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Seguimiento simple de BL para Repuestos y cierre del paso5 por fecha de costeo del Excel.

**Architecture:** Reutilizar las recepciones, sus atenciones y referencias contables. Un servicio de costeo valida cobertura por IP/atención, deja evidencia y usa el cierre existente; un servicio de consulta proyecta estados simples sin mutaciones. Ruta de consulta aislada con rol de solo lectura, misma aplicación Python/HTML/JS.

**Tech Stack:** Python, SQLite, HTML/CSS/JavaScript existentes; sin nuevas dependencias.

**Spec:** docs/reader-parts-followup.md

## Global Constraints

- Solo lector; manual y servicios actuales intactos durante desarrollo.
- Fecha de costeo desde Facturas, sin marcar SAP ejecutado por inferencia.
- No confundir BL, atención, camión planeado y llegada física.
- No publicar datos reales, mapeos, credenciales, logos privados o evidencias QA.
- Preservar cambios ajenos de resiliencia del checkout.

## Review Focus

- Misma IP en dos entregas: fecha antigua no cierra la segunda sin EM inequívoca.
- Datos parciales/fechas futuras/conflictos no acreditan costeo completo.
- Un cierre contable no simula transferenciaSAP ni llegada de pendientes.
- Consulta con rol Repuestos no habilita rutas operativas, exportaciones internas o configuración.
- Respuestas obsoletas y filtros/paginación no mezclan filas o indicadores.

### Task1: Costeo por atención

**Files:** backend/services/reception_costing.py; hooks backend/services/reception.py; tests/test_reception_costing.py.
**Interfaces:** init_schema(connection), evidence(connection,shipment_id,attention_id), reconcile(connection,shipment_id,actor) -> cantidad de cierres; evidencia auditable por atención.

- [x] Escribir casos reales sintéticos: fecha válida cierra paso5, repetición no duplica, pasos anteriores intactos, documentos incompletos/fecha futura/otra IP/otra atención no cierran.
- [x] Observar RED con unittest.
- [x] Implementar con savepoint y cierre existente; conservar check SAP y fecha documental.
- [x] Hooks al importar Facturas y al alcanzar paso5; recuperación de pendientes al iniciar, sin reaperturas.
- [x] Ejecutar casos nuevos y regresiones transferencia/cierre/importación/atenciones.

### Task2: Consulta y acceso

**Files:** backend/services/reception_followup.py; backend/password_policy.py; cambios mínimos de rol/navegación en backend/app.py y frontend; tests/test_reception_followup.py y tests/test_reception_followup_http.py.
**Interfaces:** report(connection,options) -> filas resumidas, detalle de entregas, indicadores filtrados y paginación; GET /parts-followup y /api/parts-followup.

- [x] RED: planes no acreditan llegada; cuatro estados, parcial noDisponible, fechas de fuente; filtros/KPI antes de paginar; rol de consulta sin escrituras ni acceso interno.
- [x] Proyección de datos locales sin API/Excel por render; búsqueda y páginas acotadas.
- [x] Rol CONSULTA_REPUESTOS asignable por admin existente, redirección tras login, deny de otras rutas del rol.
- [x] Regresiones login/cambio de clave y permisos.

### Task3: Pantalla y paso5

**Files:** frontend/templates/parts-followup.html, frontend/static/parts-followup.js y .css; frontend/static/reception-transfer.js; pruebas navegador.

- [x] RED navegador para filtros, contadores, datos vacíos y disposición móvil/PC.
- [x] Listado legible y detalle de entregas; fecha costeo/EM informativas del servidor en paso5, sin campo manual.
- [x] Verificar320/393/1366px, teclado, error/reintento y respuesta obsoleta; revisar capturas.

### Task4: Integración y publicación

- [x] Exportar únicamente el índice seleccionado a candidato limpio; suite Linux y pruebas de regresión pertinentes.
- [x] Una revisión acotada del cambio completo con material público/sintético; corregir hallazgos reproducidos.
- [ ] Escaneo de secretos/diff limpio; commit y PR nuevo sin instalar; adjuntarPR.
- [ ] Actualizar memoria focalizada y checkpoint con límites reales.
