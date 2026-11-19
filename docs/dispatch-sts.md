# Despacho y STS en el WMS con lector

Este cambio pertenece al WMS original. No instala ni modifica el prototipo Odoo.
Compartimos el libro de reservas y cantidades existente; no creamos otro stock.

## Despacho

1. Crea una atención y asigna picker y guiador, como en el flujo existente.
2. Inicia picking y escanea el Data Matrix del NP.
3. Cada lectura valida la cantidad preparada de su línea. Repetirla no suma unidades.
4. Un código ajeno se rechaza. Si tiene varias líneas, elige la línea correcta.
5. Para una excepción manual, registra cantidad y motivo. Cambiar la cantidad invalida la lectura anterior.
6. Finaliza el picking. El botón comprueba los NP preparados pendientes de validar.
7. Finaliza el guiado. La entrega permanece pendiente de validación.
8. Adjunta la foto y confirma que aparecen las firmas del receptor y del almacén.
9. Registra la entrega después de revisar el documento.

El Data Matrix identifica el artículo. No es un identificador único por unidad.
Retroceder a picking o reiniciar la atención invalida las verificaciones anteriores.
Su auditoría permanece en el historial. Una STS ya enviada no admite retroceso ni
reinicio mediante las correcciones genéricas; estas acciones no certifican un retorno físico.
El sistema comprueba archivo, formato, tamaño y confirmaciones; no reconoce firmas
ni determina automáticamente si una foto es legible o auténtica.

La API conserva la compatibilidad con atenciones OV anteriores sin lecturas.
Cuando hay lecturas, o el documento es una STS, también comprueba los NP al cambiar
el estado desde la API general. Las atenciones ya cerradas no se reabren.
Las fotos antiguas de una atención aún abierta deben adjuntarse nuevamente con
las confirmaciones. El histórico cerrado permanece intacto.

## STS · sucursales

Abre Despacho y selecciona «STS · sucursales». El administrador registra la
sucursal destino y crea la solicitud con fecha requerida, referencia SAP opcional,
NP y cantidades. Las OV siguen procediendo de su corte. Las STS locales sobreviven
a las cargas siguientes del Excel de OV.

Picking y guiado usan las mismas reservas, validaciones y responsables que una OV.
La salida necesita guía y foto firmada por receptor o transportista y almacén.
La atención de origen termina; el envío queda «EN TRANSITO». Esto no certifica
que la sucursal ya recibió ni que SAP registró la transferencia.

El administrador registra cantidades recibidas y receptor en la sucursal.
Cada recepción, parcial o completa, requiere su propia foto de guía firmada.
La recepción final cambia el envío a «RECIBIDO». Reintentar la misma solicitud
no duplica cantidades ni evidencia. Un reintento con datos distintos se rechaza.
Recibir en destino nunca vuelve a descontar el almacén de origen ni acredita SAP.

Las evidencias se conservan en la base junto con usuario y fecha. Su consulta
requiere sesión y permisos. No se publican fotos ni enlaces anónimos.

## Cargar las STS de SAP

El administrador abre «Cortes Excel» y usa «STS SAP / sucursales».
El archivo debe contener solicitudes SOL TRANSF, con sus encabezados originales.
Se cargan Repuestos y Accesorios del almacén 01 hacia otros almacenes.
Se identifica cada línea por número de documento y número de línea SAP.
Las repeticiones causadas por llamadas o reportes de servicio no suman cantidades.
El mismo NP en líneas SAP diferentes conserva cada línea.

El reporte habitual es completo, sin filtros. La casilla de reporte completo
aparece marcada y explica su efecto. Si se carga una selección parcial,
debe desmarcarse: los documentos y líneas ausentes conservarán su estado.
Un archivo vacío, sin encabezados o sin documentos del alcance no cierra pendientes.
Los cortes anteriores y las contradicciones se rechazan sin aplicar cambios parciales.

Una STS abierta crea una solicitud identificada como STS-SAP seguida del número SAP.
Un cerrado histórico desconocido no crea trabajo. Una STS conocida que aparece
cerrada o desaparece de un reporte completo sale de pendientes SAP.
Se conserva el expediente para buscarlo por su número, con historial y evidencias.
El trabajo físico iniciado y los envíos pendientes de recepción siguen visibles.
La ausencia en SAP no confirma picking, salida, entrega ni recepción en sucursal.

Las nuevas cargas actualizan la misma línea; no recrean sus cantidades entregadas.
Las atenciones iniciadas conservan su detalle. Un cambio de NP en una línea
trabajada requiere revisión y bloquea la carga completa, sin alterar el corte vigente.
El archivo STS no aporta existencias: se utiliza el stock global del corte SAP.
Las STS creadas manualmente y las conexiones de Recepción permanecen independientes.
