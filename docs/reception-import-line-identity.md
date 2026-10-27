# Identidad de linea al actualizar Importaciones

## NP Incorporados Despues De Crear Una Entrega

Un NP puede agregarse al corte documental despues de crear la llegada. Aparece
en el total acumulado de la BL, pero no entra automaticamente al plan congelado.
En Recepciones de la BL se muestra **NP por incorporar a una entrega**, con NP,
descripcion y requerido, para que no quede invisible en conteo/EM/ubicacion.

El administrador puede seleccionar pedidos, justificar y confirmar **Incorporar
a esta entrega**. Solo admite lineas con cantidad esperada positiva, recibida0,
sin lectura/destino de conteo guardados y nunca asignadas a ninguna atencion.
ARRIBADO/conteo conservan la etapa; EM/ubicacion reabren solo esa atencion a
Inicio de conteo. Cerradas/anuladas/validadas o con transferencia confirmada
exigen primero la reapertura administrativa existente. El resumen padre refleja
el nuevo trabajo de conteo, sin borrar la muestra guardada ni validaciones,
lecturas o destinos de otras atenciones.

La cantidad nueva empieza verificada0, sin lectura: el Excel no acredita
recepcion fisica. El trabajador debe escanear/validar el NP y puede dejarlo para
otra llegada con el flujo parcial existente. Quedan intactos los pedidos
anteriores, incluso varios del mismo NP con OC/OV distintas, sus cantidades,
historial y bultos. La accion registra usuario/motivo/ID/plan y reapertura.

La confirmacion queda ligada a BL, atencion, candidatos fuente y estado del plan.
Un cambio de corte/conteo, otra asignacion o repetir la peticion obliga a revisar
de nuevo. Escritura atomica con bloqueo SQLite y savepoint. El trabajador ve
los pendientes, sin accion ni token administrativo. No amplia por esta via la
cantidad congelada de un ID ya asignado: esa es otra regularizacion.

Solo lector mantenido. Una OC PRE que pasa a aprobada modifica los datos de la
misma linea, no representa otra recepcion ni otro pedido por si sola.

## Regla General De Actualizacion

Definicion de negocio solicitada por el propietario el2026-10-23 para TODAS las
BL del lector. Esta seccion define el contrato objetivo; no certifica que cada
casuistica o guardia este implementada. Los pases ya cubiertos y sus limites se
detallan abajo. No autoriza limpiar historicos ni modificar trabajo fisico.

1. Cada linea de pedido real conserva su ID interno durante su vida. NP, fila
   Excel, OC, IP y OV no son por si solos ese ID: pueden repetirse o cambiar.
   No cambiar globalmente las claves historicas para ocultar este problema.
2. El corte vigente valido gobierna datos DOCUMENTALES: OC, IP, OV, cliente,
   descripcion y cantidades de origen; FR/EM conservan su importador contable.
   PRE a OC y provisional a OV real son actualizaciones del mismo pedido solo
   cuando las anclas restantes prueban una correspondencia unica.
3. Cada atencion conserva su plan, NP previstos, lecturas, cantidades verificadas,
   ubicaciones guardadas y acciones confirmadas. El Excel no puede marcarlos como
   recibidos ni borrarlos. Documentos actuales no se congelan por iniciar conteo.
4. Resolver TODO el corte antes de escribir: reservar exactos, conciliar revisiones
   univocas y distinguir pedidos realmente nuevos. Mismo NP con dos OV/IP reales,
   o dos ocurrencias aun presentes en la fuente, no implica duplicacion.
5. Si no se puede demostrar si una fila es nueva o una revision, exigir revision
   explicita; no crear una segunda linea como solucion al conflicto ni elegir
   por parecido, cantidad o posicion. Cambios simultaneos sin ancla son dudosos.
   Este requisito es objetivo: no confundir los guardias actuales con deteccion
   universal de identidad cuando la fuente no trae un ID inmutable.
6. Ausencia en un corte no prueba anulacion, arribo ni cierre. Conservar historia
   y trabajo; nunca borrar automaticamente una linea trabajada o reabrir una BL
   cerrada. Duplicados previos requieren conciliacion autorizada y auditada.
7. Validar y confirmar el corte de forma atomica e idempotente: repetir el mismo
   archivo no crea lineas, movimientos o auditorias duplicadas; ante conflicto
   conservar el ultimo estado valido. Registrar que cambio, antes/despues y origen.
8. Pantalla, reporte y sticker usan la MISMA linea: documental vigente junto al
   trabajo de la atencion seleccionada. No copiar una OV vieja a otra tabla para
   imprimirla ni deducir Stock/Cotizacion solo porque falte una referencia.

Ejemplo: un NP contado con POR REG pasa a OV159001 en el corte. Se mantiene
su ID, lectura, cantidad y ubicacion, se actualiza la referencia documental y se
audita. El reporte y sticker muestran159001. Si el Excel conserva dos pedidos
distintos del mismo NP, ambos siguen separados. Ninguna regla infiere unidades
fisicamente recibidas solo de cantidades o referencias del Excel.

### Referencia Completa Y Vigencia Antes De Imprimir

La columna OV puede contener una OV real o una referencia de cotizacion. Se debe
conservar su contenido completo: por ejemplo, `COT 123456` se muestra e imprime
como `COT 123456`, no solo como `Cotizacion` ni como numero de OV inventado. No
recortar el numero, separadores o ceros significativos. Una correccion posterior
de esa referencia debe propagarse cuando se identifica de forma univoca la misma
linea, sin duplicar su trabajo. Su historial conserva el valor anterior.

Al abrir la BL y ANTES de generar una nueva previsualizacion de etiquetas,
consultar la referencia guardada mas reciente en el servidor para la atencion
elegida; no usar solamente el objeto que quedo cargado en el navegador. Actualizar
documentos no cambia las cantidades verificadas ni ubicaciones de esa atencion.
Una previsualizacion ya abierta o un archivo descargado es una instantanea: si
cambio la referencia, regenerarla antes de imprimir, no prometer que se actualiza
automaticamente. Un cambio en Excel solo se conoce despues de una sincronizacion
exitosa; consultar la BD no equivale a releer SharePoint en tiempo real.

`reception-labels.js:documentHtml` conserva ahora la referencia completa, incluidos
COT/COTI y numeros con ceros, despues de agrupar por el valor documental original.
`print` obtiene un detalle nuevo del servidor antes de crear la previsualizacion,
pero no sincroniza Excel ni refresca una ventana de impresion ya abierta.
Codigo y pruebas no equivalen a aprobacion ni instalacion en el servidor.

### Ciclo Automatico De Importaciones

El sincronizador existente del servidor revisa las fuentes cada300segundos entre
ciclos, mas el tiempo de descarga/proceso. No depende de Codex ni de un navegador
abierto. Si el contenido cambio, valida/importa el corte y actualiza las lineas
documentales mediante el mismo conciliador; si no cambio, registra la revision
sin crear otro corte. Ante error conserva el ultimo corte valido e informa en
el estado/historial de sincronizacion. No crear otro agente ni sincronizador
paralelo, ni descargar SharePoint en cada escaneo o impresion.

El intervalo predeterminado es300segundos y la configuracion puede variarlo;
una instancia concreta debe verificarse, no deducirse de este documento.
`tests/test_cloud_quotation_sync.py` ejecuta ciclos reales del worker con red y
libros ficticios: COT inicial, COT corregida y OV definitiva llegan al mismo ID,
detalle y XLSX sin alterar plan/cantidad/lectura/ubicacion de la atencion.

## Reconciliacion Del Corte

Las claves historicas incluyen hoja, BL, IP, OC, OV, NP y ocurrencia. Se conservan
para compatibilidad y para distinguir filas repetidas legitimas. Antes de escribir,
se reservan TODAS las coincidencias exactas del nuevo corte; el orden de las filas
no debe decidir a que pedido se aplica la actualizacion.

Para claves nuevas se busca la misma hoja/BL/IP/OV/NP, excluyendo la OC mutable.
Si queda una sola fila anterior y una sola nueva con IP u OV identificable, se
actualiza esa fila conservando su ID. Esto soporta PRE a OC aprobada, correccion
posterior de OC y reordenar Excel. El cambio OC anterior/nueva se audita.

Dos OV reales diferentes o pedidos simultaneos del mismo NP siguen
separados. Si PRE sigue presente en el Excel junto con otra fila aprobada, ambas
se conservan: no se presume que el usuario haya eliminado una de ellas. Si dos
referencias cambian a la vez y no hay correspondencia unica, o faltan tanto IP
como OV, la importacion avisa del conflicto ANTES de escribir. No se elige por
posicion de Excel, cantidad, primera coincidencia o parecido de descripcion.

El ID operativo, atenciones, cantidades verificadas, lectura NP, ubicaciones y
auditoria no se reinician por actualizar la OC. No se crea llegada o camion, ni
se registran FR/EM ficticias. Los campos documentales siguen su importador actual.

## Correccion De IP Con OC Y OV Estables

La IP tambien puede corregirse en la fuente. Despues de reservar las coincidencias
exactas y las actualizaciones de OC con IP estable, se busca una sola fila nueva
y una sola anterior con la misma hoja/BL/NP/OV/OC, requiriendo OC no vacia. Si la
IP anterior desaparecio del corte y solo cambia esa referencia, se actualiza el
mismo ID y se audita IP anterior/nueva. Esto incluye pedidos Para stock sin OV
real cuando la OC identifica la fila. No se basa en el numero de fila de Excel,
cantidad, descripcion o parecido entre numeros de IP.

Si las dos IP siguen presentes en el mismo corte, se mantienen como pedidos
distintos; no se fusionan por parecerse. Varias correspondencias para la misma
OC, OC ausente o IP/OC cambiadas juntas producen conflicto previo a escritura.
Si IP y OC apuntan a filas anteriores diferentes, tambien se exige revision;
el orden del Excel no puede resolver un cruce de identificadores.

Atenciones, plan congelado, conteos, escaneos y ubicaciones permanecen vinculados
al ID original. Se actualiza el dato documental, no la cantidad fisica confirmada.
Reimportar sin cambios no duplica ni repite la auditoria de IP.

## Regularizacion De OV Provisional

Despues de reservar exactos y revisiones de OC/IP, una referencia provisional
`POR REG`, `POR REGULARIZAR` o COT/COTI/Cotizacion puede pasar a una OV real en
el mismo ID. Tambien admite corregir esa referencia provisional, por ejemplo
`COT 001234` a `COT 005678`, sin recortar el numero. Requiere una sola anterior
no reservada y una sola nueva con misma
hoja/BL/NP/IP/OC, ambas IP y OC no vacias. Conserva plan, cantidad, lecturas y
destino de la atencion; audita OV anterior/nueva una sola vez. Detalle, reporte
Excel y sticker leen asi la OV documental vigente de la linea ya trabajada.

No se identifica por fila de Excel ni NP solamente. Varias candidatas, varias
OV nuevas o anclas vacias producen conflicto antes de escribir. Una OV real que
cambia por otra, un pedido Stock/SN, o una provisional todavia presente junto
con otra fila real NO se fusionan automaticamente. Tampoco se eliminan duplicados
historicos que ya existian: necesitan conciliacion separada, autorizada y auditada.

## Conteo Separado Del Corte Documental

Cada atencion conserva sus IDs de linea y `planned_qty`. En el detalle de esa
atencion, `expected_qty` y `attention_planned_qty` representan ese plan, no una
cantidad cambiada por un corte posterior. Lecturas, cantidades verificadas y
ubicaciones guardadas no se reemplazan al pasar PRE a OC aprobada.

Importaciones sigue guardando el corte actual en `reception_lines`; OC, OV, FR y EM
pueden actualizarse normalmente. No se detiene la sincronizacion ni se descarta
un cambio por la deduplicacion del archivo. Una llegada posterior toma el saldo
del corte actual, sin modificar el plan de atenciones anteriores.

Un NP nuevo o un pedido adicional del mismo NP queda en la fuente, pero no se
agrega a una atencion ya creada. Su indicador `in_selected_attention` es falso,
sus cantidades operativas para esa atencion son cero y no aparece como trabajo
de FR/EM en ella. Tampoco puede contarse mediante un POST manual sin lectura.
No se fusionan OV/IP simultaneas diferentes para hacer desaparecer una fila legitima.

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
identificar BL/NP y conciliar su historial de forma controlada. La regla de IP
anterior previene nuevos duplicados univocos, no borra duplicados ya contados ni
afirma que se regularizaron. Si cambian tambien OC/OV/hoja o BL sin correspondencia
estable, hace falta revision de origen o conciliacion explicita. No inventar un
identificador empresarial ni sumar dos lecturas como si fueran unidades reales.

Pruebas: tests/test_reception_import_identity.py, datos ficticios y bases nuevas.
Incluyen reserva de coincidencias, pedidos con/sin OV, varias IP/OV, cambios PRE,
idempotencia, fila movida, conflicto sin escrituras e historial operativo intacto.
tests/test_reception_import_ip_revision.py agrega cambios de IP, stock, varias
OC/IP, cruces de identificadores, cortes reordenados y atenciones congeladas.
La prueba de integracion modifica solo un libro en memoria, no el Excel empresarial.
tests/test_reception_import_ov_revision.py agrega OV provisional a real, reserva
de reales existentes, ambiguedad/movimiento de filas, y detalle/reporte de una
atencion con plan y conteo congelados.

Regresion de congelacion: tests/test_reception_count_snapshot.py, incluyendo
varias BL y roles, cantidades de fuente cambiadas, mismo NP con distintas OV,
pedidos agregados despues, carga por bytes/archivo, siguiente llegada, legado y
FR/EM documentales. Su estado de ejecucion se registra en el PR correspondiente.

Verificacion2026-10-15:631 unittest OK/2 skips sobre el candidato aislado sin
capacidad pendiente;61 pruebas enfocadas de importacion/conteo tambien OK. Los
cuatro recorridos browser de conteo/lecturas/ayudas/etiquetas se repitieron sobre
ese candidato con base desechable nueva. Sin limpieza automatica del historico,
acceso a Excel real, instalacion o cambios productivos.
