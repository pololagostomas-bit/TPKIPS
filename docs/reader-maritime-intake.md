# Lector: ingreso por BL maritima y otros transportes

Alcance: lector. El ingreso maritimo por cantidad de esta propuesta necesita
aprobacion, fusion e instalacion antes de estar disponible en el servidor.
La version manual permanece congelada.

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
En BL maritimas sin lecturas previas se usa el formulario de cantidad descrito
abajo, no el campo de codigo unico.
Revisar otra BL en el resumen no cambia la BL de recepcion. Usar esta BL para
recibir es una accion explicita y vuelve a validar su pertenencia al camion.
Cambio de modo/BL se bloquea durante un guardado; reintentar una lectura fallida
conserva su modo, camion y BL originales.

Los borradores de codigos se separan por modo y BL. Una nueva BL de recepcion
no hereda un codigo pendiente de la anterior; volver recupera ese borrador.
Cancelar cambios los descarta expresamente y no anula las lecturas guardadas.
Los borradores de cantidades tambien pertenecen a su BL. Terminar llegada no
acepta codigos o cantidades sin guardar, ni fallos pendientes.

## BL maritima sin etiquetas individuales

En Por BL, buscar o escanear una BL existente de tipo MARITIMO. Si no tiene
lecturas activas de bultos en ese camion, aparece Total de bultos recibidos en
esta llegada en lugar de exigir un codigo unico. El operador cuenta fisicamente
los bultos y guarda el total de ESA BL en ESE camion, no el acumulado historico.
No se genera un codigo, etiqueta de proveedor ni validacion DHL ficticia.

Solo administrador o asistente de recepcion puede guardar. El campo comienza
vacio cuando no existe un total guardado; nunca se rellena con los esperados.
Guardar 8 dos veces deja 8, no 16. Cambiarlo a 9 reemplaza el total pendiente
con auditoria. Un cambio concurrente distinto se rechaza y actualiza la consulta
del total guardado sin descartar el borrador local. Cero retira una cantidad
pendiente; no anula un recibo confirmado ni recibe una BL con cero bultos.

El manifiesto conserva package_count_mode=QUANTITY y una version. El conteo de
lecturas sigue siendo literal: registered_package_count=8 y package_scan_count=0
no son contradictorios. Sin total documental conocido se muestra total por
confirmar, no un supuesto 8/8 que declararia completa toda la BL.

Guardar cantidad no crea todavia la llegada, SLA o conteo de NP. Terminar llegada
confirma los bultos guardados y continua a zona temporal; la suma de ubicaciones
de cada BL debe coincidir. Despues se recibe cada NP en su atencion normal. Un
bulto no identifica por si mismo los SKU que contiene ni los da por contados.
Otro arribo parcial guarda su propia cantidad y ubicacion, sin sumar de nuevo
la llegada anterior. No se declara completa una BL solo por tener esos bultos.

Una BL/camion no mezcla cantidad con lecturas activas. Registros maritimos
anteriores con codigos reales conservan su flujo de escaneo. DHL y otros
transportes no pueden usar esta ruta para saltarse su control de codigos.
Cancelar la recepcion pendiente o retroceder administrativamente a Transito
reinicia la cantidad pendiente con historial; los bloqueos existentes contra
retroceder trabajo ya avanzado se conservan. No se borran lecturas ni auditoria.

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

Los proveedores maritimos no necesariamente entregan etiquetas unicas o ASN.
La cantidad declarada acredita el registro humano, no la trazabilidad unitaria
de cada bulto que proporciona una lista de Piece IDs. Para detectar bultos
maritimos repetidos o intercambiados sigue siendo necesaria la revision fisica.

Pruebas en `tests/test_reception_barcode_scanning.py`,
`tests/test_reception_scan_ui.py`, `tests/test_maritime_quantity.py`,
`tests/test_maritime_quantity_http.py`, `tests/maritime_intake_browser.cjs`
y `tests/maritime_quantity_browser.cjs`.
Fixtures ficticias verifican BL existente/desconocida, camion mixto, duplicados,
contextos y borradores, llegada/ubicacion, cinco viewports y cero llamadas DHL
adicionales. Camara y lector Android fisicos requieren validacion posterior al
despliegue aprobado. La version manual no se modifica ni se despliega.
