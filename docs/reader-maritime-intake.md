# Lector: ingreso por BL maritima y otros transportes

## Dos modos en el mismo camion

Bulto DHL conserva la identificacion automatica local por Piece ID, sin elegir
una BL antes de cada bulto. Por BL permite escanear el codigo de una BL/AWB o
digitar su referencia y pulsar Buscar BL. No requiere DHL, ni una BL nueva, ni
otro programa. Ambos modos pueden usarse en el mismo camion.

La BL debe existir en Importaciones. Se conservan ceros y referencia fuente;
espacios, mayusculas y guiones se comparan con la busqueda existente. Codigo
desconocido, ambiguo o cerrado no crea un expediente provisional ni registra
una llegada. Un administrador o asistente elige la BL de recepcion; los permisos
del auxiliar no se amplian para ingresar BL.

## Contexto de recepcion y consulta

Una BL buscada correctamente se muestra bajo Recibir bultos de, con su tipo de
transporte. El formulario se pliega en Cambiar BL para dejar espacio al bulto.
El campo BL acepta lector HID/Bluetooth, digitacion y el control de camara
existente, sujeto a HTTPS y permisos del dispositivo.

Cada codigo unico se registra con el ID de esa BL capturado antes de encolarlo.
Revisar otra BL en el resumen no cambia la BL de recepcion. Usar esta BL para
recibir es una accion explicita y vuelve a validar su pertenencia al camion.
Cambio de modo/BL se bloquea durante un guardado; reintentar una lectura fallida
conserva su modo, camion y BL originales.

Los borradores de codigos se separan por modo y BL. Una nueva BL de recepcion
no hereda un codigo pendiente de la anterior; volver recupera ese borrador.
Cancelar cambios los descarta expresamente y no anula las lecturas guardadas.
Terminar llegada no acepta codigos todavia sin registrar, ni fallos pendientes.

## Recepcion fisica y arribos parciales

Buscar BL solo vincula el expediente, inicialmente con cero bultos. No inicia
SLA ni confirma llegada. Registrar bultos conserva la deduplicacion durable,
auditoria original y rechazo de codigos usados en otra BL/camion. Una BL/AWB
no se acepta como codigo unico de bulto. Las piezas DHL conocidas tampoco
pueden vincularse a una BL equivocada usando este modo.

Una BL comprometida en otro camion pendiente, en curso o en zona de recepcion
se rechaza indicando el camion de origen. Cuando ese camion termina sus pasos
fisicos, una BL todavia abierta puede tener otro arribo parcial con nuevos
codigos. Se consulta la atencion de ese camion: una atencion anterior que ya
avanzo a EM/ubicacion no oculta el nuevo arribo ni sustituye su atencion.

Terminar llegada utiliza los bultos efectivamente registrados, sin exigir una
cantidad esperada documental. Continuan los pasos existentes de zona temporal,
conteo, EM, ubicacion y validacion. Una BL elegida con cero bultos no se recibe
ni bloquea la ubicacion de las otras BL recibidas. Los historicos cerrados
permanecen cerrados sin exigirles un camion.

## Limites y verificacion

Por BL reutiliza el registro de bultos con codigos unicos; NO crea codigos falsos
ni agrega recepcion por cantidad manual. Falta confirmar si los bultos maritimos
reales tienen etiquetas unicas; si no, esa modalidad requiere un ajuste distinto
con cantidad fisica explicita, sin duplicarla con lecturas. No asumir que todos
los proveedores entregan etiquetas o ASN.

Pruebas en `tests/test_reception_barcode_scanning.py`,
`tests/test_reception_scan_ui.py` y `tests/maritime_intake_browser.cjs`.
Fixtures ficticias verifican BL existente/desconocida, camion mixto, duplicados,
contextos y borradores, llegada/ubicacion, cinco viewports y cero llamadas DHL
adicionales. Camara y lector Android fisicos requieren validacion posterior al
despliegue aprobado. La version manual no se modifica ni se despliega.
