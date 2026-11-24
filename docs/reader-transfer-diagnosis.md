# Diagnóstico de cierre en Transferencia

En Recepción → entrega → paso 5, el administrador ve qué falta para aplicar
el costeo. Cada observación indica el campo, la causa y la corrección.
Cuando existe una referencia, también muestra hoja, fila, FR y EM del corte.
Los asistentes y auxiliares no reciben estos detalles en la API ni en pantalla.

| Grupo | Casos detectados | Corrección |
| --- | --- | --- |
| Documentos y origen | IP recibida ausente de Facturas; FR o EM faltante; referencia sin corte verificable. | Revisar la fila y el corte de Facturas. Vincular una IP solo si el documento realmente la cubre. |
| Fechas | Costeo ausente, inválido, futuro, anterior a la llegada o anterior a la EM. | Revisar la fecha real y el alcance de los documentos en Facturas. |
| Entregas parciales | La misma IP aparece en varias entregas sin EM vinculada a la entrega elegida. | Usar las herramientas administrativas existentes de vínculo o cobertura excepcional de EM. |
| Asociaciones y trabajo físico | Conflicto contable; NP cuya BL cambió; IP faltante en un NP recibido; entrega sin llegada válida o sin NP recibidos; atención anulada, administrativa o inexistente. | Revisar Importaciones o la operación correspondiente, sin inventar recepción ni documentos. |

Se reutilizan las condiciones de cierre existentes. No se agregan reglas para
cerrar más BL ni se cambian cantidades, lecturas, documentos, fechas o historial.
Se muestran conjuntamente los problemas documentales independientes; una
asociación estructural inválida se corrige antes de evaluar sus documentos.
Una misma observación de una fila contable no se repite por cada IP de esa fila.
En una entrega cerrada, las observaciones son una revisión documental y no
reabren la operación ni solicitan repetir el cierre.

«Actualizar diagnóstico» vuelve a leer el último corte ya sincronizado, para la
misma BL y entrega. No descarga Excel ni inicia sincronizaciones o envíos.
Después de corregir el origen, espera la sincronización habitual y actualiza.
La siguiente importación válida aplica el cierre mediante el mecanismo habitual.

El diagnóstico es informativo. No confirma una transferencia SAP ni reemplaza
la validación de la cobertura de una EM. Los permisos, confirmaciones, motivos
y auditoría de las herramientas administrativas existentes se conservan.

Pruebas sintéticas: `tests/test_reception_costing_diagnostics.py`, prueba de
privacidad en `tests/test_reception_transfer.py`, contratos de interfaz en
`tests/assistant_transfer_ui.cjs` y navegador en `tests/costing_diagnosis_browser.cjs`.
