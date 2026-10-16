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

Verificacion2026-10-15:631 unittest OK/2 skips sobre el candidato aislado sin
capacidad pendiente;61 pruebas enfocadas de importacion/conteo tambien OK. Los
cuatro recorridos browser de conteo/lecturas/ayudas/etiquetas se repitieron sobre
ese candidato con base desechable nueva. Sin limpieza automatica del historico,
acceso a Excel real, instalacion o cambios productivos.
