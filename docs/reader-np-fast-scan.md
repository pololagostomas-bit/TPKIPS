# Lectura NP sin confirmar cantidades

Solo WMS con lector. Cambio sujeto a aprobacion del PR, no instalado por publicar.

## Contrato de pantalla

El asistente escanea en Inicio de conteo de una BL/atencion ya recibida. Enter o
la camara existente guarda el NP sin abrir el formulario de cantidad. Conserva
el entero completo predefinido de esa atencion, no el stock disponible. Una
correccion existente, incluido cero, no se sustituye por el requerido. El NP,
descripcion, requerido y Sin stock permanecen visibles; OV/IP/linea adicionales
siguen la preferencia de ayudas. Los pedidos ambiguos requieren elegir la fila
correcta, sin confirmar cantidad; no se elige una OV arbitraria.

### Pedidos repetidos y llegadas parciales

La tabla y el escaner usan las mismas filas de la atencion seleccionada. El
detalle conserva el resto de la BL para consultas, pero expone
in_selected_attention para que otra llegada no aparezca como un pedido editable
del conteo actual. Un NP de otra llegada genera un aviso especifico sin enviar
una escritura que el servidor rechazaria.

Se elimina solo la repeticion del mismo ID de origen en la respuesta. Dos IDs
distintos siguen siendo dos pedidos, aunque coincidan NP, OV, IP y cantidad. No
se consolidan ni eliminan registros, cantidades o asociaciones en la base.

Una lectura automatica ofrece solo pedidos pendientes con cantidad en esta
atencion. No incluye filas con requerido y verificado cero de llegadas anteriores;
Corregir NP conserva esas filas para un eventual excedente real. Si hay varios
pedidos con cantidad en esta atencion, una sola
pulsacion elige un boton con OV o Sin OV, requerido e IP; estas referencias son
necesarias para distinguir el pedido incluso con las ayudas ocultas. No se
repite el encabezado del NP ni se exige abrir cada candidato antes de elegirlo.
Si queda un solo pedido pendiente, la siguiente lectura lo registra sin otra
seleccion ni confirmacion de cantidad. Corregir NP conserva todos los pedidos
de esta atencion, incluidos los ya revisados.

Una repeticion del mismo codigo mientras su lectura esta guardandose, pendiente
de elegir o fallida no consume otro pedido. No se usa una ventana temporal que
impida una segunda lectura deliberada tras completar la primera. Un reintento
conserva el ID y cuerpo originales; descartar retira tambien los candidatos
viejos. Un NP ya revisado no agrega cantidades ni marca como recibido un
faltante justificado.

La accion habitual es la propia lectura. Corregir NP abre deliberadamente el
editor anterior; no es un paso obligatorio. El listado completo conserva sus
ajustes de cantidad, observacion y ubicacion por defecto. No cambia el stock ni
la validacion fisica posterior, FR/EM, SLA o estados del camion.

## Autoridad y progreso

El POST existente /api/receptions/{BL}/lines/{linea}, con scan_np=true y la
atencion capturada, guarda cantidad/destino y marca np_scanned_at/by. La lectura
solo cuenta tras una respuesta valida del servidor con esa marca. Los campos
nuevos son aditivos; no se deducen escaneos de cantidades inicializadas, Excel,
EM, historial cerrado o del destino SAP. No se migran historicos como leidos.

El progreso cuenta NP distintos con requerido o verificado positivo. Un codigo
con varios pedidos queda pendiente hasta registrar todos sus pedidos. Recargar
recupera el registro por atencion; otra llegada no hereda sus marcas. Relecturas
no suman y el servidor hace idempotente un reintento incierto: tampoco sobrescribe
una cantidad corregida entre la primera escritura y su reintento.

Guardar revision completa y pasar a EM avisan de los NP pendientes. La API
tambien impide pasar a EM con lectura parcial una vez iniciado este modo. Las
atenciones anteriores atendidas exclusivamente por la via manual mantienen su
compatibilidad de API sin reconstruir lecturas ficticias; el nuevo flujo UI
exige resolver las lecturas antes de finalizar: leer el NP o confirmar que no
llego en esta atencion, nunca completar automaticamente lo no escaneado.

### Continuar Con Recibidos

Cuando hay NP leidos con cantidad positiva y otros aun sin leer, el operador
puede elegir Continuar con recibidos. La confirmacion lista los NP no recibidos
y el numero de pedidos que quedaran para otra llegada. Cancelar no escribe nada.
No hace falta corregir cada faltante a cero uno por uno. Una cola fallida o una
correccion sin guardar debe resolverse primero; no se omiten errores de lectura.

POST /api/receptions/{BL}/count/partial captura la atencion y los IDs de todos
sus pedidos pendientes, incluso con un filtro NP activo. El backend comprueba
asignacion/rol, confirmacion, Inicio de conteo, al menos una lectura positiva y
que el conjunto coincida con los pendientes actuales. Un nuevo escaneo desde
otra sesion invalida la confirmacion; no se sobrescribe esa lectura. Mismo NP
con otra OV sigue siendo otro pedido, no una fila duplicada para eliminar.

La operacion coloca solo los no leidos en cero con np_unreceived_reason y
auditoria, sin inventar np_scanned_at, ni reducir expected_qty/planned_qty.
Sincroniza las cantidades acumuladas y avanza esta atencion a EM en la misma
transaccion, respetando FR/IP, destino y demas validaciones. Si cualquiera falla,
revierte tambien los ceros y la auditoria parcial. Reintentar explicitamente una
respuesta incierta ya aplicada en EM no repite el ajuste ni sus eventos.

El pendiente no se imprime ni ubica como recibido. Se pueden terminar los pasos
de los NP que si llegaron, pero el maestro BL conserva las unidades por atender.
Una atencion posterior toma ese saldo y comienza sin las marcas de lectura o
no recibido de la anterior. El sistema no crea otra llegada ni fecha futura por
confirmar un faltante. Se mantiene el SLA fisico existente, sin reiniciarlo por
aplazar un NP.

Al terminar todas las atenciones fisicas de la BL, si solo quedan SKU por llegar,
el saldo se muestra en Pendiente de camion, con cantidad de SKU y sin inicio de
SLA. No se copia la fecha del primer arribo como estimada del siguiente. Una
recepcion positiva nueva aun sin atencion no se oculta como saldo futuro.

El boton y la confirmacion son los mismos en celular y PC; durante la escritura
se impide doble envio/navegacion. Un fallo conserva el conteo y permite reintento
explicito. Progreso sigue siendo, por ejemplo,9/10 leidos y1 no recibido, no10/10.

Un faltante fisico real no obliga a inventar una lectura: Corregir NP permite
guardar cero con observacion. El servidor conserva esa excepcion por atencion
como np_unreceived_reason, sin marcarla escaneada, y la pantalla la muestra como
No recibido. Resuelve ese pendiente para continuar la atencion parcial, pero no
lo suma a NP leidos. Cero sin observacion no sirve como excepcion. Una cantidad
positiva posterior elimina la excepcion, no inventa un escaneo.

## Errores, celular y PC

El prefijo AIM Data Matrix se reconoce como ]d1 o ]D1 cuando el teclado del
lector cambia su capitalizacion. Ambas variantes resuelven el mismo NP y la
misma lectura pendiente; no crean otra entrada en cola ni consumen otro pedido.
Si el codigo completo ya coincide literalmente con un NP de la BL, tiene
prioridad y no se recorta como si fuera un prefijo del lector.

Una cola local de hasta100 lecturas conserva codigo, BL, atencion y pedido
elegido. El campo sigue recibiendo Enter mientras se guarda; escrituras en serie,
sin otro worker, libreria o llamada externa. Una lectura desconocida, ambigua o
fallida pausa la cola y muestra acciones explicitas de resolver/reintentar o
descartar; no se oculta por el siguiente exito. No hay reintento automatico de
escrituras. Foco vuelve al campo, no a una confirmacion de cantidad.

La cola no es almacenamiento offline: salir/recargar con operaciones pendientes
se protege, y una pestaña cerrada a la fuerza puede perder lecturas no enviadas.
Solo el registro confirmado en servidor sobrevive. No iniciar otra BL ni el
cierre mientras haya cola sin resolver. Mismo flujo responsive y permisos que
Recepcion; progreso legible, errores visibles incluso con ayudas ocultas.

## Verificacion: 2026-10-14

613 unittest OK, dos skips previstos, sobre una exportacion del indice del PR
sin incluir los cambios locales pendientes de ubicaciones/capacidad. Pruebas de
servicio por atencion/idempotencia/cierre parcial y compatibilidad manual; modulo
JS para lecturas rapidas, cero, fallos/reintento y seleccion ambigua.

Navegador con base desechable en320/375/393/820/821/1440px y873px horizontal:
autoguardado, duplicados, pedido ambiguo, cero, recarga, correccion, cola503,
reintento explicito, cambio de BL bloqueado y faltante real justificado. Incluye
regresion del total predefinido tras una recarga parcial. Conteo/filtros/ubicacion
readonly/etiquetas y ayudas/correccion explicita pasaron en cinco tamanos cada
uno; texto ampliado sin desbordamiento. Capturas locales inspeccionadas.

Las pruebas de navegador no certifican un lector HID, camara Android o impresora
fisicos. Sin cambios de servicios, SQL productivo o correo real. No se publican
las bases, capturas, logos, libros Excel ni configuracion privada de las pruebas.

## Verificacion de estabilidad: 2026-10-15

621 unittest OK, dos skips previstos, sobre una exportacion del indice sin el
modulo local pendiente de capacidad. Incluye 43 pruebas enfocadas del servicio
y escaner: ID repetido, otra llegada, pedidos con/sin OV, referencias identicas
con IDs diferentes, repeticion durante el guardado y pedidos ya revisados.

reception_np_stability_browser.cjs paso en1366/393/375/320px y873px horizontal:
seleccion en un toque o Enter, escritura unica, cola conservada, aviso especifico
sin POST ajeno, recarga, descarte y texto al200%. Las suites de lectura rapida
(7 tamanos), correccion/ayudas (5) y conteo/ubicacion/etiquetas (5) tambien pasaron
sobre el candidato aislado y una base nueva. Capturas locales inspeccionadas.
No se certifico hardware real ni se modificaron datos productivos o servicios.
