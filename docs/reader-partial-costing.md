# Entregas parciales y costeo documental

Las lecturas conservan la cantidad solicitada por línea. El progreso de NP de
la BL es acumulado entre entregas: por ejemplo, 8/10 deja dos NP pendientes;
no convierte en «no recibidos» los ocho ya leídos en otra llegada.

El comentario automático de ausencia pertenece a la atención que lo generó.
Al consultar una entrega posterior se muestra su observación actual, sin
heredar esa ausencia anterior. Las observaciones humanas y los registros
históricos permanecen intactos.

Una FR puede repetirse en Facturas para distintas EM. Si una IP tiene varias
llegadas, el costeo necesita una EM vinculada a la atención correspondiente.
Una fila vacía reservada para una EM futura de la misma FR no bloquea una
entrega con EM vinculada y fecha de costeo válida. Tampoco completa las otras
entregas. Distintas FR y conflictos mantienen sus validaciones anteriores.

En Transferencia, el administrador dispone de «Relacionar una EM existente»
cuando hay EM sin entrega asociada. Debe seleccionar una, confirmar la entrega
e indicar un motivo. El servidor valida BL, FR, IP, trabajo recibido y etapa;
no permite mover una EM ya vinculada a otra atención. Se guarda auditoría.
No se crea otra EM ni se alteran su fecha, autor o número.

Una EM numérica seguida únicamente de un separador vacío, como «70001 -», se
interpreta como «70001». Sus registros originales se conservan; no cuentan
como dos documentos. Los códigos con guiones significativos se mantienen.

El costeo nunca salta los pasos físicos ni afirma por sí mismo que se marcó
la confirmación de transferencia SAP. La fecha debe ser válida y cubrir las
IP efectivamente recibidas. Una EM retirada de la referencia vigente no
puede acreditarse usando solo una entrada histórica.

## Excepción: una EM para varias entregas

La regla predeterminada sigue siendo una EM por recepción. Una FR puede tener
varias EM. Cuando un único documento realmente cubre varias llegadas físicas,
el administrador puede usar «Una EM para varias entregas» en Transferencia.
Debe elegir una EM existente ya ligada a su entrega de origen y seleccionar
individualmente las demás entregas cubiertas, confirmar y dejar motivo.
No se seleccionan automáticamente todas las llegadas.

La cobertura es una asociación auditada, no otra EM. Conserva el documento y
las cantidades/lecturas originales. No se aplica a nuevas llegadas ni a otra
BL/IP. Solo las entregas con trabajo físico terminado llegan al cierre por
costeo; no se saltan etapas ni se marca SAP. Las EM pendientes se calculan
por recepciones cubiertas, sin multiplicar el número real de documentos.

Si cambia la FR/IP/EM o su atención original, la excepción deja de acreditar
el costeo. «Quitar excepción» permite retirarla con motivo e historial: los
cierres históricos no se reabren, pero el seguimiento deja de afirmar un
costeo vigente para las entregas que ya no están cubiertas.
