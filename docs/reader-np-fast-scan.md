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
siempre exige completar las lecturas antes de finalizar.

Un faltante fisico real no obliga a inventar una lectura: Corregir NP permite
guardar cero con observacion. El servidor conserva esa excepcion por atencion
como np_unreceived_reason, sin marcarla escaneada, y la pantalla la muestra como
No recibido. Resuelve ese pendiente para continuar la atencion parcial, pero no
lo suma a NP leidos. Cero sin observacion no sirve como excepcion. Una cantidad
positiva posterior elimina la excepcion, no inventa un escaneo.

## Errores, celular y PC

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
