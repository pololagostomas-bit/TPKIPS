# Identidad de linea al actualizar Importaciones

Solo lector mantenido. Una OC PRE que pasa a aprobada modifica los datos de la
misma linea, no representa otra recepcion ni otro pedido por si sola.

## Reconciliacion Del Corte

Las claves historicas incluyen hoja, BL, IP, OC, OV, NP y ocurrencia. Se conservan
para compatibilidad y para distinguir filas repetidas legitimas. Antes de escribir,
se reservan TODAS las coincidencias exactas del nuevo corte; el orden de las filas
no debe decidir a que pedido se aplica la actualizacion.

Para claves nuevas se busca la misma hoja/BL/IP/OV/NP, excluyendo la OC mutable.
Si queda una sola fila anterior y una sola nueva con IP u OV identificable, se
actualiza esa fila conservando su ID. Esto soporta PRE a OC aprobada, correccion
posterior de OC y reordenar Excel. El cambio OC anterior/nueva se audita.

Dos OV diferentes, IP diferentes o pedidos simultaneos del mismo NP siguen
separados. Si PRE sigue presente en el Excel junto con otra fila aprobada, ambas
se conservan: no se presume que el usuario haya eliminado una de ellas. Si dos
referencias cambian a la vez y no hay correspondencia unica, o faltan tanto IP
como OV, la importacion avisa del conflicto ANTES de escribir. No se elige por
posicion de Excel, cantidad, primera coincidencia o parecido de descripcion.

El ID operativo, atenciones, cantidades verificadas, lectura NP, ubicaciones y
auditoria no se reinician por actualizar la OC. No se crea llegada o camion, ni
se registran FR/EM ficticias. Los campos documentales siguen su importador actual.

## Conteo Separado Del Corte Documental

Cada atencion conserva sus IDs de linea y `planned_qty`. En el detalle de esa
atencion, `expected_qty` y `attention_planned_qty` representan ese plan, no una
cantidad cambiada por un corte posterior. Lecturas, cantidades verificadas y
ubicaciones guardadas no se reemplazan al pasar PRE a OC aprobada.

Importaciones sigue guardando el corte actual en `reception_lines`; OC, FR y EM
pueden actualizarse normalmente. No se detiene la sincronizacion ni se descarta
un cambio por la deduplicacion del archivo. Una llegada posterior toma el saldo
del corte actual, sin modificar el plan de atenciones anteriores.

Un NP nuevo o un pedido adicional del mismo NP queda en la fuente, pero no se
agrega a una atencion ya creada. Su indicador `in_selected_attention` es falso,
sus cantidades operativas para esa atencion son cero y no aparece como trabajo
de FR/EM en ella. Tampoco puede contarse mediante un POST manual sin lectura.
No se fusionan OV/IP diferentes para hacer desaparecer una fila legitima.

Las diferencias y avisos de conteo comparan con el plan de la atencion: si era5
y el Excel pasa a9, contar5 no genera una falsa diferencia. Un conteo real de4
se compara con5, no con9. No se envia correo real durante estas pruebas.

Para trabajo antiguo activo que aun no tenga ninguna atencion, el importador
crea una atencion de compatibilidad antes de reemplazar la fuente. Conserva
cantidad, lectura y ubicacion existentes; no inventa una llegada, camion o FR/EM.
La marca `legacy_count_snapshot` conserva tambien ceros verificados sin marcas
de lectura nuevas, sin presentarlos como cantidades predeterminadas, y retiene
una transferencia que ya estuviera confirmada.
No reconstruye datos anteriores que ya se hubieran perdido ni reabre historicos
cerrados. No modifica una atencion existente al volver a importar.

El reporte de revision usa los mismos IDs, cantidades planeadas y verificadas
de la atencion elegida. La ruta acepta `attention_id`, valida que pertenezca a
la BL y no mezcla sus cantidades con otra llegada ni con el ultimo corte. El
reporte documental general de BL sigue conservando el corte actual de origen.

## Limites

Esta correccion previene duplicar una actualizacion univoca; no elimina filas
historicas ya duplicadas ni consolida movimientos. Para las existentes hay que
identificar BL/NP y conciliar su historial de forma controlada. Si tambien cambian
IP/OV/hoja o BL, no se presume identidad: hace falta una referencia estable del
origen o conciliacion explicita. No inventar un identificador empresarial.

Pruebas: tests/test_reception_import_identity.py, datos ficticios y bases nuevas.
Incluyen reserva de coincidencias, pedidos con/sin OV, varias IP/OV, cambios PRE,
idempotencia, fila movida, conflicto sin escrituras e historial operativo intacto.
La prueba de integracion modifica solo un libro en memoria, no el Excel empresarial.

Regresion de congelacion: tests/test_reception_count_snapshot.py, incluyendo
varias BL y roles, cantidades de fuente cambiadas, mismo NP con distintas OV,
pedidos agregados despues, carga por bytes/archivo, siguiente llegada, legado y
FR/EM documentales. Su estado de ejecucion se registra en el PR correspondiente.

Verificacion2026-10-15:631 unittest OK/2 skips sobre el candidato aislado sin
capacidad pendiente;61 pruebas enfocadas de importacion/conteo tambien OK. Los
cuatro recorridos browser de conteo/lecturas/ayudas/etiquetas se repitieron sobre
ese candidato con base desechable nueva. Sin limpieza automatica del historico,
acceso a Excel real, instalacion o cambios productivos.
