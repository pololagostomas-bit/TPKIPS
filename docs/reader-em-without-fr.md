# Recepcion fisica con FR pendiente

Aplica al WMS con lector. Terminar Inicio de conteo permite entrar a EM (sticker)
aunque falte toda la FR o solo la de alguna IP recibida. El conteo parcial tambien
puede continuar, conservando en cero los NP explicitamente pendientes para otra
entrega. Entrar a esta etapa no crea una entrada de mercancia contable.

Se mantienen permisos/asignacion, secuencia, cantidades positivas de ESTA
atencion, lecturas pendientes, ubicacion guardada y bloqueo de conflictos IP.
Las cantidades de una entrega anterior no sustituyen lo recibido en la actual.
Una IP aun sin recibir no se convierte en recibida por la ausencia de documentos.

La pantalla conserva Factura de reserva pendiente y permite preparar etiquetas.
Guardar una EM real sigue validando su FR/IP y alcance de atencion. La accion
explicita Continuar con los NP disponibles permite el trabajo de ubicacion con
documentacion pendiente; no rellena FR/EM ni marca una transferencia SAP hecha.
Validacion y confirmacion de transferencia conservan sus checks existentes.

## Espera documental observada

DOCUMENTACION/fr_wait en reception_history registra inicio/fin de intervalos.
Para trabajo nuevo comienza al terminar el conteo sin FR; para trabajo antiguo
solo puede empezar en la primera observacion durante un refresco documental.
Nunca se inventa el tiempo anterior a esa observacion ni se confunde un cero
desconocido con una espera comprobada. No requiere tabla, cron o worker nuevo.

El refresco real de documentos/manual resuelve la espera cuando las IP recibidas
ya disponen de FR. Las IP aun sin SKU recibido no mantienen abierta una espera
ajena. Repetir la observacion o tener atenciones superpuestas no multiplica el
tiempo; periodos distintos se suman. Si se retira una FR durante trabajo activo,
una nueva observacion abre otro periodo. Un conflicto IP es una deuda distinta:
el reloj de FR se resuelve cuando existe FR, aunque persista el conflicto.

Son horas calendario continuas, independientes del SLA operativo. El seguimiento
lee timestamps existentes al consultar, sin escrituras ni ticks periodicos.
Detalle administrativo y Excel filtrado muestran horas y comentario documental.
El historial completo conserva los eventos originales. Los trabajadores reciben
la alerta documental, sin el contador administrativo. No se modifica el reloj SLA.

## Aviso de validacion

La transicion de validacion conforme reutiliza su misma solicitud, destinatario,
remitente, autorizacion Microsoft y politica de reintentos. Si falta FR, la alerta
aparece en rojo en la BL y en ese correo, cuyo asunto indica Pendiente FR e
incluye la espera observada. Primero solicita regularizar la documentacion.
El enlace conserva su funcion: confirmar una transferencia IMP a01 ya realizada
en SAP. No ejecuta SAP, inventa documentos ni confirma nada automaticamente.
El aviso no se envia al entrar en EM ni durante consultas o impresiones.
