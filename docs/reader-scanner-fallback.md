# Lector, camara y recuperacion manual

Solo WMS con lector. Un PR no autoriza su instalacion; la variante manual sigue
congelada. El servidor valida permisos y movimientos en todas las vias.

## Contrato de trabajo

| Aspecto | Regla |
| --- | --- |
| Usuario / tarea | Asistente o auxiliar recibe bultos exactos y revisa NP; admin conserva correcciones ya existentes. |
| Contexto | Conservar camion, modo, BL, atencion e ID de linea originales durante lecturas y reintentos. |
| Principal | Leer codigo; el backend confirma antes de aumentar el contador. No confirmar cantidad otra vez para NP normal. |
| Alternativa | Trabajador: codigo conocido en el bulto/copia; admin: Por BL > Ingreso manual / etiqueta borrosa. Elegir NP no cambia. No sustituir identidad por semejanza. |
| Celular / PC | Un mismo flujo, controles tactiles >=44px, camara48px, listas50 registros y acciones accesibles con scroll. |
| Error | Conservar codigo/borrador; reintentar o descartar explicitamente. No reproducir escrituras automaticamente. |
| Salida | Cerrar/Escape libera camara y restaura foco. Cambiar contexto invalida respuestas/callbacks antiguos. |

## Bultos

Con pieza DHL conocida, el modo Por bulto resuelve la BL desde la cache local.
Leer de nuevo el mismo codigo no suma otra pieza. No hay consulta DHL por
bulto, render o seleccion manual; las consultas siguen en su worker existente.

El total DHL pertenece al envio completo, no acredita llegada fisica. El estado
separa `received_pieces` (lecturas activas), `total_pieces` (documental) y
`pending_arrival_pieces` (saldo del total conocido). Por ejemplo, una lectura de
un envio de tres piezas muestra1 recibida y2 pendientes; no crea otros arribos.
La vista normal del admin lista solo codigos recibidos; los esperados siguen
exclusivamente en su herramienta manual. Trabajador conserva cantidades sin
listas de codigos. Lecturas anuladas no cuentan. Sin cache vigente se conserva
la evidencia fisica, pero el total/saldo desconocido no se inventa.

Se aceptan los formatos completos de AI GS1(00) seguido de18 digitos, tambien
`00` sin parentesis y portador AIM GS1-128/DataMatrix/QR cuando envia ese mismo
elemento. Los18 digitos se conservan como texto, incluidos ceros iniciales;
no se recortan otros campos ni se usa coincidencia por sufijo. Referencia de
formato: [GS1 Application Identifiers](https://www.gs1.org/gs1-application-identifiers).
El envoltorio SAP `*JD...*`, `*JJD...*` o `*(J)JD...*` se reconoce solo con
ambos asteriscos y cola numerica completa. No se quitan asteriscos de codigos
arbitrarios. Esto decodifica formato, no certifica presencia ni sustituye la
coincidencia exacta con DHL. La lectura original queda en auditoria.

Si no lee la etiqueta, elegir Por BL y buscar/digitar la BL correcta. Solo el
administrador consulta y selecciona la lista de piezas retenidas: faltantes,
recibidas y conflictos. Buscar por codigo o sufijo y paginar no crea llamadas
DHL. La lista puede estar incompleta o vencida; no confundirla con un ASN.

Asistentes y auxiliares ven cantidades recibidas/faltantes, no los codigos DHL
esperados, ni siquiera en el JSON GET/POST de estado. La API manual-pieces y el
registro con source=cache exigen administrador; cambiar HTML, rol del cuerpo o
parametros no concede acceso. Un trabajador puede ingresar un codigo completo
leido del bulto/copia, con motivo y confirmacion, pero no elegir una pieza del
cache. La via normal tambien permite digitar y aplica la misma validacion.

Para guia DHL (Courier/Aereo con AWB de10 digitos), todo registro nuevo exige
coincidencia exacta con su BL en cache vigente, incluso el registro manual del
admin. Codigo desconocido, otra BL, cache parcial sin esa pieza, vencido o DHL
deshabilitado generan alerta y no suman. No se resuelve con confirm_unverified
ni eligiendo una BL. Un reintento de una lectura ya guardada sigue idempotente
aunque expire el cache; no suma un nuevo bulto. La llegada de un camion lector
cerrada por un trabajador debe coincidir con sus lecturas guardadas, tambien
si llama directamente la API de cantidades. La correccion admin sigue separada.

Elegir **una** pieza exacta de esa lista o ingresar su codigo unico conocido.
Registrar evidencia, comprobar BL/bulto y confirmar su presencia fisica. El
backend valida el manifiesto activo y la relacion DHL cuando existe, y guarda
auditoria del registro manual. Reintento del mismo codigo conserva el contador;
una pieza registrada en otra BL no se reasigna desde esta pantalla.

Si la etiqueta se perdio y no hay identidad verificable, no inventar un ID ni
elegir cualquier faltante. La recepcion por cantidad de una BL requiere revision
administrativa en el flujo existente de transito confirmado y conciliacion para
no duplicar estas lecturas. Este cambio no convierte piezas desconocidas en
piezas DHL ni registra el lote entero. BL maritima permite digitacion/seleccion
explicita y codigo de bulto conocido, sin exigir consulta DHL.

GET `/api/receptions/truck-guide/manual-pieces` es solo admin, lee persistencia,
devuelve50 piezas por pagina y no encola consultas. POST `manual-package`
requiere rol operativo (source=cache solo admin), proteccion de solicitud, BL
del manifiesto, codigo, evidencia y confirmacion booleana; usa transaccion y
auditoria, sin tocar el total esperado. Estas restricciones no se aplican a
la lista de NP: elegir un pedido/OV no es simular la llegada de un bulto DHL.

## NP

Enter del lector o camara registra cantidad entera predefinida de la linea.
Elegir NP de la lista usa la misma validacion por ID/atencion y permite hacerlo
sin teclado ni codigo legible. No elige un codigo parecido al no encontrado.

Mismo NP en varias OV conserva pedidos distintos. Exige elegir el pedido
correspondiente incluso cuando solo queda uno, para que un callback repetido
no consuma silenciosamente otra OV. El NP unico normal no agrega confirmaciones.
IP y numero interno de linea siguen la preferencia de ayudas; OV distingue la
eleccion. Una lectura o correccion pendiente debe resolverse antes de elegir otra.
Continuar con recibidos sigue dejando los SKU no recibidos para otra llegada.

## Camara y dispositivos

La biblioteca existente html5-qrcode2.3.8 se sirve localmente, bajo demanda y
sin CDN. Se conserva el motor para Data Matrix, QR y codigos lineales. Inventario
tambien usa ese mismo bundle local, sin cambiar su flujo. Licencia Apache2.0 y
hashes en `third-party-notices/html5-qrcode`; licencia incluida en los assets.

Camara NP/bulto puede continuar tras guardado confirmado; BL termina su lectura.
Repeticion de frames no suma registros. Error pausa, ambiguedad lleva a elegir
pedido/BL, y un NP escrito pendiente no se sobrescribe. HTTPS y permisos del
navegador siguen siendo necesarios. Un lector fisico1D no se convierte por
software en lector Data Matrix/QR: para esos stickers se requiere lector2D o
camara compatible. No se certifica hardware por una prueba emulada.

## Verificacion

Fixtures sinteticos y pruebas especificas cubren cuotas, permisos, identidad,
duplicados JJD/JD, cache vencida, transaccion, guardado tardio, cola NP, borradores,
9/10 recibidos, errores/reintento y preferencia de ayudas. Playwright cubre320,
393,1366 y873px horizontal, texto200% y el bridge real contra bases desechables.
El decoder real lee imagenes sinteticas Data Matrix, QR yCode128. No se usaron
bases productivas, correos reales, impresora ni camara/lector fisicos en QA.
