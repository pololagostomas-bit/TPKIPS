# Recepcion: estado y criterios de aceptacion

Evaluacion de codigo y QA del lector, 2026-10-24. No es una certificacion de
produccion, una auditoria completa de datos ni una prueba con hardware real.
La variante manual congelada queda fuera de alcance.

## Etapa actual

**Piloto operativo funcional, en consolidacion.** Existe un recorrido desde
camion/BL hasta conteo, EM, ubicacion, validacion y confirmacion de transferencia.
No basta que una pantalla abra o que /health este sano para darlo por terminado.
La nueva modalidad maritima descrita aqui es propuesta, no una funcion instalada.

| Parte | Evidencia y alcance | Estado |
| --- | --- | --- |
| Camion DHL | Identificacion por bulto, variantes de codigo, deduplicacion, control de roles y correcciones auditadas | Implementado; regresiones sinteticas |
| Maritimo sin etiqueta unica | BL existente + total fisico por llegada, sin inventar codigos o consultar DHL | Implementado en esta propuesta; falta aprobar/instalar |
| Zona temporal | General por camion y excepciones/repartos por BL; suma exacta de bultos | Implementado; flujo mixto probado en navegador |
| Conteo NP y parciales | Lectura, cantidad guardada, correccion administrativa y saldo entre atenciones | Implementado; tests de parciales y progreso acumulado |
| Identidad documental | Cambios PRE/OC/IP/OV separados de cantidades, lecturas y destinos fisicos | Guardas y regresiones existentes; no prueba de que todo el Excel este limpio |
| EM, etiquetas y ubicacion | Datos guardados por atencion, Data Matrix y confirmacion de destino | Implementado; impresion y lectura fisicas pendientes de aceptacion |
| Validacion/transferencia | Solicitud limitada por BL y confirmacion humana de transferencia en SAP | Implementado; NO es una escritura automatica en SAP |
| Historicos y excepciones | Cierre administrativo con permisos, confirmacion, motivo y auditoria | Implementado; no cierra masivamente por cabecera FR/EM |
| Reportes | Trabajos en segundo plano y controles de acceso | Implementado; tests sinteticos no equivalen a carga real sostenida |

La suite completa y los contratos navegador se verifican en un candidato limpio
con bases desechables. Los tests de transferencia, cierre, importacion, parciales,
ubicacion y reportes cubren logica existente; esta revision no vuelve a ejecutar
cada escenario con servicios corporativos ni a enviar correos de prueba.
Resultado: 966 unittest OK con dos omisiones existentes (130.105s), flujo de
cantidad en cuatro viewports y regresion maritima en cinco. Sin desbordamiento
horizontal ni errores JS en esos recorridos; no certifica otros dispositivos.

## Instalado frente a propuesto

En esta revision se observo el lector sano con imagen a1744f14d6cd. La comprobacion
es de estado y revision del servicio, no de todos sus datos. La ruta instalada
anterior seguia exigiendo codigo unico para bultos maritimos; esta propuesta
resuelve la carencia, pero no modifica el servidor al crear el PR.

PR40, relativo a la referencia COT completa, seguia abierto y no fusionado en
la consulta de esta fecha. Esta rama parte de main aprobado sin incluirlo de
forma oculta. Al fusionar varias propuestas se debe volver a ejecutar la QA
de la combinacion y verificar la imagen y los assets realmente instalados.

## Pendientes para produccion estable

1. Aprobar e instalar los cambios elegidos, con respaldo y comprobacion posterior
   de version, migracion, login y flujo. Fusionar un PR no prueba su instalacion.
2. Prueba de aceptacion con lector/camara Android y etiquetas de la impresora
   real: codigo de bulto DHL valido/repetido/incorrecto, BL maritima sin etiqueta,
   NP en dos OV legitimas, faltante que llega despues y correccion de admin.
3. Conectividad estable y recuperacion del acceso externo. Un tunel temporal
   no garantiza URL fija ni recuperacion autonoma por el solo hecho de usar Docker.
4. Ensayo de concurrencia con el volumen real y restauracion de respaldo. Medir
   p95 de lectura/guardado/reporte y errores, no inventar una capacidad certificada.
5. Power BI stock sigue siendo un conector pendiente: Excel sincronizado y un
   token Graph no acreditan acceso BI, frescura del modelo ni filtro de almacen.
6. Integracion directa SAP no terminada. Acordar primero interfaz, permisos,
   operaciones permitidas, ambiente de pruebas y conciliacion/idempotencia.

## Criterio de salida del piloto

Registrar evidencia de un turno controlado con casos aereos y maritimos, parcial
y faltante posterior, etiquetas legibles, permisos trabajador/admin, rechazo de
codigo ajeno, recuperacion tras desconexion y respaldo restaurado. Contrastar
cantidades con documentos y operacion, sin convertir una declaracion manual en
prueba de validacion DHL o SAP. Resolver discrepancias antes de ampliar uso.

Fuentes: tests/test_maritime_quantity.py, tests/test_maritime_quantity_http.py,
tests/test_reception_barcode_scanning.py, tests/test_reception_truck_partial_arrivals.py,
tests/test_reception_partial_count.py, tests/test_reception_np_partial_corrections.py,
tests/test_reception_import_identity.py, tests/test_reception_count_locations.py,
tests/test_reception_transfer.py, tests/test_reception_admin_closure.py,
tests/test_report_jobs.py y ambos scripts maritime_*_browser.cjs.
