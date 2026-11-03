# Costeo con EM compartida: plan

**Objetivo:** reconocer una EM declarada por Facturas para varias IP sin alterar el registro manual ni cerrar otra entrega.

**Arquitectura:** proyección separada del último corte de Facturas para filas con una sola EM y varias IP. Mantener la asignación manual de EM y las comprobaciones de fechas/FR/IP/atención. La consulta usa esa evidencia explícita; una referencia contable agregada o una fecha por sí solas no prueban cobertura. Reprocesar una sola vez el corte sin cambios al instalar la nueva versión del parser, sin inventar otra fecha de corte ni duplicar data_imports.

- [x] Reproducir la EM ya asociada a una IP, ambas IP en la misma entrega y el cierre bloqueado.
- [x] Probar conservación de registros manuales, varias llegadas, retirada/cambio de fuente y fechas inválidas.
- [x] Implementar proyección atómica y reprocesamiento único con pruebas de corte idéntico.
- [x] Candidato limpio Linux; validar copia privada aislada y proyección de consulta, sin escribir en producción.
- [ ] Revisión acotada pública, escaneo de secretos, PR a main y CI. Guardar evidencia/memoria. Sin merge ni instalación.
