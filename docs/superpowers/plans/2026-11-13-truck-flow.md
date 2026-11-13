# Ejecución: camiones y recepción operativa

Base: main 90d24eaf51fcce8c39de933daf46c8f6cc1dff34.
Responsable: Codex, inline; revisión externa Gemini antes de publicación.
Diseño: ../specs/2026-11-13-truck-flow-design.md.

- [x] Reproducir numeración prematura y progreso global confuso.
- [x] Probar identidad interna estable y número público al confirmar:
  borrador/cancelación, secuencia, reintento y concurrencia.
- [x] Implementar columna aditiva, asignación atómica y etiquetas en las
  respuestas/listas sin modificar claves o históricos.
- [x] Simplificar pantalla camión/cola y vista de recepción por rol. Conservar
  estado, filtros, lecturas, herramientas administrativas y navegación.
- [x] Integrar lector/cámara Data Matrix de ubicación temporal general y
  excepciones, con guardas de contexto y entrada manual.
- [x] Verificar parcialidad única y entregas/días en reporte y exportación.
- [x] Ejecutar pruebas dirigidas, navegador móvil/PC, suite local y detector UI; Linux en CI del PR.
- [ ] Revisar candidato exacto externamente; resolver hallazgos y publicar PR.

Revisión: numeración concurrente y cancelaciones, total desconocido, cambio
de BL durante una lectura, código esperado privado, guardado con error,
excepciones de ubicación y parcialidad sin duplicar recepciones.
