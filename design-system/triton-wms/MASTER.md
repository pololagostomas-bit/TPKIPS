# Triton WMS: Contrato Frontend

Version 1.0, 2026-10-14. Aplica al lector mantenido y a sus modulos operativos,
administrativos e integraciones. La aplicacion manual separada queda congelada.
Este documento define el trabajo futuro; no certifica que todas las pantallas
antiguas ya cumplan ni autoriza una remodelacion o un despliegue masivo.

## 1. Una Aplicacion Adaptable

Una sola fuente de datos, permisos y acciones para celular y PC. Cambia la
distribucion, no la logica del negocio. Mantener HTML/CSS/JavaScript y Python.
Usar CSS Grid/Flex, anchos fluidos y minmax(0,1fr); no detectar modelos o marcas
de telefono por user-agent ni crear una aplicacion paralela para cada dispositivo.

| Espacio disponible | Comportamiento |
| --- | --- |
| 320-820 CSS px | Una tarea/columna principal; lista y detalle alternan. Formularios apilados y registros legibles. Navegacion inferior existente, hasta cinco destinos. |
| Desde 821 CSS px | Se pueden distribuir campos y listas en columnas si caben. El expediente activo conserva el foco de trabajo; la cola no lo comprime. |
| Desde 1200 CSS px | Mayor densidad de comparacion y tablas, sin estirar formularios de una tarea a todo el monitor. |
| Poca altura o teclado abierto | Reorganizar o permitir desplazamiento para alcanzar todos los controles; nunca recortar el contenido para mantener una altura fija. |

820/821 conserva el umbral del shell actual. Los ajustes ya existentes a 720px
son de componentes, no una segunda definicion de navegacion. Usar el ancho real
del contenedor para detalles locales; no sumar breakpoints aislados por pantalla.
Las bandas son una convencion WMS, no valores impuestos por Fluent o Ant Design.

En formularios comunes, permitir desplazamiento vertical natural. En el escaner
se conserva un area de trabajo ajustada al viewport visible, contenido interno
desplazable y accion final separada. Utilizar el helper de viewport ya existente,
100dvh como respaldo y safe-area-inset; no fijar la altura al tamano de un Honor.
Evitar dos desplazamientos verticales competidores dentro de la misma tarea.

El teclado, las barras de Android y la navegacion inferior no pueden tapar el
campo activo ni Guardar. Con zoom/texto grande, la accesibilidad prevalece sobre
el intento de mostrar toda la pantalla sin desplazamiento. No desactivar el zoom
ni reducir toda la interfaz con transform:scale para hacerla caber.

## 2. Jerarquia Visual

Aplicacion de trabajo, no pagina promocional: identificador, estado, tarea actual,
datos esenciales y accion principal. Secciones sin tarjetas decorativas ni
tarjetas anidadas. Reservar marcos para registros repetidos, modales o herramientas
que realmente los necesiten. Mantener la identidad Triton con naranja como
acento, superficies claras y colores semanticos diferenciados.

Reutilizar los tokens actuales de reader-ui.css y el shell. Esta tabla es el
contrato de referencia, no una segunda hoja de estilos para pegar en cada modulo.

| Rol | Referencia |
| --- | --- |
| Superficie / pagina | --reader-surface #ffffff / --reader-page #f4f5f5 |
| Texto / secundario | --reader-ink #29343b / --reader-muted #526169 |
| Linea / foco | --reader-line #bcc8ce / --reader-focus #176b87 |
| Marca / texto sobre marca | --wms-orange #f58200 / texto oscuro #202d35 |
| Exito / advertencia / error | Mantener los roles semanticos existentes; verificar contraste con su fondo y anadir texto, no solo color. |
| Tipografia | Segoe UI, Arial, sans-serif; sin fuentes remotas obligatorias. |
| Texto / campos | Base 16px; texto secundario 14px; 12px solo metadatos no esenciales. |
| Titulos operativos | 20-24px; secciones 18-20px; paneles compactos 16-18px. |
| Numeros de progreso | 28-32px con cifras tabulares y espacio estable. |
| Espaciado | Escala 4, 8, 12, 16, 24, 32px; base entre controles 8px. |
| Radios | Controles 6px; marcos/modales como maximo 8px; secciones sin radio. |
| Objetivo tactil WMS | Minimo 44x44 CSS px; preferir 48x48 para escaneo y acciones frecuentes tactiles. |

No escalar tipografia con vw ni usar espaciado negativo entre letras. Los
identificadores largos pueden partirse visualmente sin modificar su valor;
clientes, marcas y estados deben reordenarse sin superponerse. No truncar un dato
necesario sin un modo accesible por toque/teclado para leerlo completo.

44px es nuestra convencion de uso tactil, no el minimo AA universal de WCAG.
En checkbox/radio, medir el area de la etiqueta accionable, no solo el cuadrado.
Aplicar el objetivo a acciones operativas y navegacion; no transformar cada
enlace dentro de un parrafo en un boton de 44px.
Los objetivos nativos en dp/pt no equivalen a CSS px. Buscar contraste de texto
normal >=4.5:1 y texto grande >=3:1, con foco y limites de controles verificables.
La existencia de tokens no prueba conformidad de toda la aplicacion.

## 3. Navegacion Y Botones

Conservar los destinos existentes: Inicio, Transito, Recepcion (BLs),
Transferencias y Mi perfil. Los filtros pertenecen a la lista a la que afectan;
Perfil > Herramientas y opciones agrupa configuracion y administracion. Si un
rol no tiene acceso, no presentar un destino operativo vacio.

Una accion principal por tarea. Si cada fila es una tarea independiente puede
tener su propia accion; no convertir todas las acciones de la fila en primarias.
Herramientas conocidas usan icono, nombre accesible y tooltip; acciones de
negocio como Guardar, Confirmar llegada o Reabrir ubicacion usan texto explicito.
Reutilizar la familia de iconos local; para nuevos iconos utilizar Lucide cuando
este disponible. No dibujar SVG equivalentes ni usar emojis como iconos.

| Accion | Contrato |
| --- | --- |
| Volver | Navega sin revertir lo guardado; una ruta clara a lista/camion de origen. |
| Cambiar BL | Cambia la revision; no reasigna silenciosamente el siguiente bulto. |
| Guardar | Envia una vez, indica progreso y confirma solo con respuesta valida. |
| Cancelar recepcion | Accion destructiva distinta de Volver; confirma alcance y conserva auditoria. |
| Reabrir llegada/ubicacion | Solo admin, paso destino explicito, confirmacion, motivo, validacion backend e historial. |
| Imprimir | Solo datos guardados y de la atencion elegida; nunca confundir vista previa con impresion realizada. |

No duplicar Lista/Volver/Retroceder/Cancelar cambios con efectos ambiguos.
Mantener la salida del modal, soporte de Escape y confirmacion de descarte cuando
haya borradores. Los controles administrativos pueden agruparse, pero no depender
de una preferencia de ayudas oculta. Ocultar un boton no sustituye un permiso API.

## 4. Formularios Y Datos

Etiquetas visibles y asociadas; placeholder no sustituye la etiqueta. Select para
opciones, checkbox/toggle para binarios e input numerico para cantidades. Una
cantidad vacia no equivale a cero. No redondear ni completar datos de negocio sin
regla explicita. Conservar borradores ante errores; enfocar el primer campo
invalido, con mensaje cercano y resumen si hay varios.

En celular, convertir tablas de tareas en registros apilados con etiquetas sin
perder asociaciones FR/EM/IP ni editar el NP incorrecto. Las tablas comparativas
que realmente requieren dos dimensiones pueden desplazarse dentro de su propio
contenedor; el resto de la pagina debe reflowar. No resolver overflow con
overflow-x:hidden global que recorta informacion o controles.

Por defecto mostrar lo necesario para trabajar. Respetar show_guidance para
ayudas y referencias adicionales. Nunca ocultar errores, requisitos para avanzar,
cantidades relevantes, diferencias o controles de permiso. Mostrar texto de estado,
no instrucciones internas, comentarios de desarrollo ni explicaciones de estilo.

## 5. Escaneo Y Estados WMS

El servidor es la autoridad. Camion, BL y atencion son entidades distintas.
Mantener IDs/atencion al filtrar NP, guardar, imprimir y volver al camion. Un
Excel, FR/EM completos, una fecha o una marca no prueban llegada fisica ni cambian
por si solos el SLA o el cierre. No reabrir historicos por cambiar la apariencia.

Progreso por BL: recibidos/esperados, fuente y faltantes; distinguir arribos
previos. Total desconocido se muestra como desconocido; no convertirlo en cero.
Duplicados no suman, excesos permanecen visibles. La marca o marcas de la BL se
muestran normalizadas sin modificar los datos de origen ni publicar logos.

Las lecturas rapidas conservan codigo, guia y contexto original al encolarse.
Una lectura fallida no desaparece al guardar otra: reintentar o descartar de forma
explicita. En modo bulto DHL no exigir leer BL si el cache local resuelve el bulto;
en modo BL la eleccion del contexto debe ser explicita. No reasignar una lectura
solo porque se abrio otra BL. No gastar una llamada externa por render o bulto.

## 6. Respuestas, Rendimiento Y Conexion

Cada vista distingue inicial, cargando, vacia, lista, guardando, error y sin
conexion/sesion vencida cuando corresponda. No mostrar datos viejos como actuales.
Las lecturas pueden tener progreso no bloqueante; Guardar impide doble envio.
Validar status y tipo de respuesta antes de interpretar JSON, preservando exports
binarios. Un 401 requiere inicio de sesion; un 403 explica falta de permiso.

Reutilizar los helpers existentes: API/respuesta, shell, preferencias, viewport y
conexion. Cancelar lecturas obsoletas con AbortController o guardas de secuencia;
una respuesta tardia no debe reemplazar otra ventana ni devolver el foco atras.
No disparar peticiones desde cada observacion DOM ni recrear listeners al navegar.

Paginar listas/reportes (referencia actual: 50 filas), filtrar antes de paginar y
conservar totales globales. Reutilizar cargas de identidad y maestros. Camara,
Data Matrix, logos y exports se cargan bajo demanda. No introducir otro proceso
o Web Worker sin medir que parte es CPU, red, SQL o render y justificar su costo.

Las credenciales y sincronizaciones viven en el servidor. La UI consulta estado
y solo pide reautorizacion cuando corresponda. Navegar o ver Correos no envia
mensajes. Las escrituras fallidas o con resultado incierto nunca se reproducen
automaticamente. Sin servicio, mostrar estado de conexion; no una aplicacion vieja
desde cache ni datos operativos obsoletos que parezcan validos.

La percepcion de respuesta debe comenzar inmediatamente. Como objetivos de
diagnostico, buscar feedback visible en 100ms y medir apertura de vista, latencia
de guardado y cantidad de requests; registrar equipo/red/datos y comparar contra
baseline. No prometer ese tiempo extremo a extremo ni afirmar una mejora sin medir.

## 7. Fuente Y Evolucion

Leer el [flujo de entrega](../../.agents/skills/wms-frontend-standards/references/delivery.md)
para pruebas y el [contrato de pantalla](../../.agents/skills/wms-frontend-standards/references/screen-contract.md)
para nuevos flujos. Las
[referencias verificadas](../../.agents/skills/wms-frontend-standards/references/sources.md)
son inspiracion tecnica, no dependencias instaladas. Cambios globales de tokens,
navegacion o componentes se prueban tambien en modulos vecinos. Excepciones locales
documentan motivo y prueba; no se acumulan overrides globales contradictorios.
