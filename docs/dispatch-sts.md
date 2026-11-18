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
