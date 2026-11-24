# Triton Tracking — diseño propuesto

Fecha: 23 de noviembre de 2026. Estado: propuesta para aprobación del propietario; no implementada ni publicada.

## 1. Objetivo y público

Dar al personal autorizado de Triton una consulta por documento que explique dónde está su pedido, qué falta y qué fechas están informadas, desde compra/importación hasta almacén. El propietario confirmó uso exclusivamente interno con acceso autorizado. No se habilita acceso de clientes externos.

Nombre: Triton Tracking. Una entrada propia y su propio túnel. La apariencia se inspira en la claridad de un tracking de envíos, con identidad Triton y sus logos existentes.

## 2. Recomendación de arquitectura

Elegir una extensión de consulta del WMS QR mantenido, no crear otra fuente de verdad ni usar el antiguo visor Odoo. Reutilizar Python/SQLite/HTML/CSS/JS, conectores y reglas verificadas. El nuevo WMS nativo18772 sigue separado como laboratorio sintético; no suministra hechos operativos.

Crear una superficie /tracking con sus recursos, acceso y API bajo ese mismo prefijo. Reutilizar las funciones de identidad/política de contraseñas y un permiso explícito de consulta Tracking, sin conceder permisos de almacén. Las cuentas existentes no obtienen ese permiso automáticamente. El administrador lo asigna a personas concretas; no se crean cuentas compartidas ni se publica una contraseña.

El módulo no altera recepciones, pedidos ni archivos de origen. Solo las funciones normales de autenticación pueden registrar auditoría y bloqueos. Consultas parametrizadas y un objeto de respuesta con campos permitidos; no reutilizar el payload de administrador con campos ocultos solo en pantalla.

El túnel propio debe terminar en una entrada restringida que exponga únicamente /tracking y sus recursos/autenticación. No publicar con ese túnel las rutas administrativas ni operativas del WMS. Validar Host/Origin, cookies seguras por host, permisos y límites. El proceso/túnel independiente no debe reiniciar el lector ni el nuevo local al arrancar o detenerse.

Decisión del autor: gateway ligero separado delante del mismo backend; escoger su implementación instalada más pequeña durante el plan. Antes de instalarlo, demostrar que bloquea las rutas ajenas y no altera el túnel QR actual. Despliegue del módulo requiere PR revisado, pruebas, aceptación y las autorizaciones operativas vigentes. La primera revisión visual/datos se hace localmente con datos sintéticos.

## 3. Búsqueda de la primera versión

Selector OV / OC y campo con etiqueta y botón Consultar. No intentar adivinar el tipo por una coincidencia numérica. Conservar identificadores y prefijos significativos; usar las normalizaciones ya verificadas, sin aproximaciones por nombre/NP.

OV es el recorrido principal para comerciales. OC es también necesaria en la primera versión porque una compra para stock puede no tener OV. Buscar una OC sin OV muestra la compra y sus repuestos; solo etiquetar Para stock cuando la fuente lo indica, de lo contrario Sin OV asociada.

BL no es una tercera búsqueda independiente de la primera versión. Se muestra como referencia asociada y como agrupación de embarques del documento. Una OV puede contener varias OC y BL, una OC puede alimentar varias OV y un repuesto puede llegar en varias recepciones.

No existe una lista pública de todas las órdenes. La búsqueda exige autenticación y el permiso Tracking. Decisión del autor para esta primera versión interna: ese permiso permite consultar estados de los documentos de la empresa, no solo los asignados al comercial. Ocultar precios, márgenes, credenciales, correos personales y documentos ajenos a la consulta. Esta decisión queda visible para que el propietario pueda corregirla antes de construir.

## 4. Datos existentes comprobados

Fuente operativa: lector QR, imagen observada b0143693b9df. Código mantenido consultado en el checkout nativo con base de producción b0143693b9dfe78e0e42d6b42ef8f7b96393f4e1; no se modificó ese checkout.

Comprobación remota acotada: una descarga del Excel de Importaciones usando la conexión Microsoft/SharePoint ya configurada. Se inspeccionaron solo cabeceras, sin guardar el libro ni exportar filas operativas. Se encontraron nueve hojas con cabeceras compatibles. No se deben añadir consultas al Drive de cada visitante.

Cabeceras observadas: FECHA DE SOLICITUD DE IMP OV; OV/ORDEN DE VENTA; ORDEN DE COMPRA; CLIENTE; CODIGO/CÓDIGO; DESCRIPCION; cantidades solicitada/facturada/pendiente; ESTADO POR NP; PEDIDO TRITON; PEDIDO FABRICA; FECHA DE PEDIDO; STATUS; N° FACTURA; GUIA DE IMPORTACION; MODO DE TRANSPORTE; PAÍS DE ORIGEN; FECHA DE FACTURA; FECHA RECOJO; FECHA CALLAO; FECHA TRITON ESTIMADA; FECHA CONFIRMADA TRITON; FECHA COSTEO.

La base actual retiene relaciones OV/OC/BL/NP, fechas de recepción/contabilidad y trabajo de almacén. No retiene por separado todas las fechas previas del Excel. order_importation_refs.source_date agrupa alias de fechas diferentes: NO usarlo como si acreditara una fecha específica de proveedor, pedido o solicitud.

Para cubrir las etapas tempranas se necesita ampliar la proyección de lectura del mismo importador: conservar campos de seguimiento separados, incluidas filas sin BL y referencias preliminares/cotización. No modificar las cantidades o estados operativos para lograrlo. Aplicar las exclusiones y validaciones de hojas actuales.

No se observó columna explícita de aprobación de OC ni una columna llamada Fecha proveedor. La primera versión debe informar esa limitación; no deducir aprobación porque una OC tiene cinco dígitos. No mapear fecha de pedido a fecha de proveedor sin una definición de origen.

## 5. Recorrido y evidencia

El recorrido tiene dos bloques: Compra/importación y Almacén. Dentro del primer bloque mostrar los hitos aplicables: solicitud; situación OV/cotización y OC/preliminar; pedido a fábrica; factura/recojo; Callao; previsión de llegada Triton. Los hitos de transporte se adaptan al modo: Callao no se exige en un envío aéreo/nacional donde no aplique.

La fecha Triton confirmada tiene prioridad sobre la estimada para la previsión principal. Las dos siguen visibles con sus etiquetas y procedencia. Una fecha confirmada de origen sigue siendo una previsión, no demuestra una llegada física al almacén. Nunca marcar un hito completo solo porque su fecha estimada ya pasó.

Distinguir fecha informada por el Excel, fecha prevista y hecho comprobado. Por ejemplo, FECHA RECOJO/FECHA CALLAO se presentan inicialmente como fechas informadas con su fuente, no como confirmación independiente de presencia o ubicación. La interfaz no promete GPS ni ubicación en tiempo real. Último hito informado y ubicación física confirmada son conceptos distintos.

Almacén usa proyecciones existentes de recepciones/atenciones, no el estado global del camión: Recibido; Ubicado; Costeo/transferencia. Dentro del último hito distinguir costeo documental informado y transferencia confirmada en WMS. Una casilla del WMS no certifica por sí sola un movimiento contabilizado en SAP. No fusionar esos hechos hasta contar con su evidencia.

El final es Atención de almacén completada según las reglas actuales de cierre, no necesariamente pedido entregado al cliente. La entrega final al cliente queda fuera de esta primera versión.

## 6. Estados parciales y relaciones

La pantalla resume la OV/OC sin ocultar repuestos pendientes. La etapa principal se apoya en evidencia del conjunto, con contadores y texto Parcial cuando corresponde; no promover toda la OV por el repuesto más adelantado.

Mostrar filas de repuesto con descripción, cantidades y estado, agrupables por OC/BL. Cantidad pedida, pendiente de origen, recibida, ubicada y transferida solo cuando exista evidencia correspondiente; no sumar eventos duplicados ni mezclar cantidades facturadas con recibidas. No restar cantidades de dimensiones distintas. Una cantidad desconocida se muestra como tal.

Reutilizar la identidad documental/atenciones existente y resolver por referencias de documento y línea. No enlazar dos compras solo porque comparten NP. Referencias ambiguas, cotización con OC/IP y estados contradictorios quedan visibles como Datos por confirmar; no se resuelven inventando una cadena.

Las revisiones PRE→OC deben conservar el antecedente cuando exista una relación estable demostrable. Si no existe, mostrar referencias actuales sin fabricar un historial. La desaparición de una fila del corte no equivale a cancelación. Mostrar Ya no aparece en el corte actual cuando esa sea la única evidencia.

## 7. Documentación

Panel Referencias documentales con OV o cotización, OC o preliminar, pedido Triton/fábrica, factura, BL/guía y FR/EM cuando correspondan. Estados: Registrado, Pendiente, No aplica y Sin verificación.

El panel no certifica que todos los documentos estén aprobados o firmados porque haya números registrados. Una OC con número válido se etiqueta OC registrada; Aprobación no verificada si no hay evidencia explícita. Una cotización no aparece como OV confirmada. No mostrar comprobantes descargables si no existe un documento real autorizado.

La evaluación documental y la física se muestran en paralelo: un dato documental faltante no borra una recepción real, y una BL/fecha no crea mercancía recibida.

## 8. Fechas, SLA y actualización

Reutilizar reception_sla/reception_work y su calendario vigente, no crear otro reloj: actualmente72h o96h según transporte y reglas existentes, con exclusiones del calendario del WMS. El inicio real y las excepciones deben coincidir con la proyección de almacén. Antes de la llegada no iniciar el SLA de almacén.

Mostrar responsable del siguiente paso por área, no prometer un nombre sin asignación guardada. Usar títulos Importaciones/Compras/Almacén según evidencia. Fechas sin hora no se convierten en eventos con hora inventada.

Mostrar Última actualización del corte para cada fuente y separar del momento de consulta. Datos atrasados, conexión caída o ausencia de una fecha se indican expresamente. No poner En vivo ni usar hora de la consulta como hora del dato. La promesa es seguir el corte sincronizado existente, no información que todavía no llegó al sistema.

No backfill de historia inventada. Las fechas existentes se presentan como fechas del origen; cualquier historial de cambios solo puede comenzar al implementarse o usar eventos ya auditados.

## 9. Rendimiento y protección del WMS

Sin descargas de Excel/Graph/DHL ni llamadas a IA desde una búsqueda. El importador ya existente proyecta la información con el mismo archivo y marca de corte/hash. No iniciar otro importador o bucle de sincronización para Tracking.

Primera carga por consulta explícita; sin polling de todo el catálogo, búsquedas por tecla ni refresco automático de una página oculta. Botón Actualizar vuelve a leer la proyección, no fuerza la nube. Límites de longitud, paginación de líneas y concurrencia; consultas agrupadas e índices por documento, sin una consulta por NP/BL. Medir lecturas reales con SQLite trace/EXPLAIN y datos sintéticos antes de fijar un presupuesto final.

Actualización del snapshot de tracking atómica por corte válido. Un Excel corrupto/incompleto no elimina el último snapshot correcto: conservarlo y marcarlo desactualizado. Los cambios del importador deben probar que no alteran los flujos actuales de recepción/OV.

## 10. Diseño de pantalla

Pregunta principal: ¿En qué está esta OV/OC y qué falta para que almacén la complete?

Entrada: logo Triton, título Triton Tracking, selector OV/OC, campo de número y botón Consultar. Tras consultar: documento/cliente permitido, estado actual, fecha Triton prevista más relevante y aviso de frescura.

Debajo: cronología con puntos, etiquetas y fechas; explicación corta del bloqueo/siguiente paso; repuestos y embarques parciales; referencias documentales. El detalle completo se abre solo al seleccionarlo. No convertir el tracking en un tablero de administración con decenas de métricas.

Identidad: logo real local, naranja Triton, fondo claro, texto oscuro y tipografía del WMS. Naranja para el paso activo; estados confirmados y alertas con texto/iconos además de color; futuro/sin dato diferenciado. Sin porcentajes de avance inventados, mapas falsos, iconos animados gratuitos, carruseles ni fuentes remotas obligatorias.

PC: recorrido horizontal cuando quepa y repuestos debajo. Móvil: recorrido vertical, una columna, tabla transformada en filas legibles sin perder cantidades. Teclado, foco visible, controles44px y contraste accesible. Validar320/393/1366px y zoom/texto grande.

UI/UX Pro Max se consultó: la primera recomendación cayó en una categoría de video no aplicable y se descartó. La segunda aporta legibilidad y estado de datos; su estructura de landing comercial no aplica. Se conserva la identidad y el contrato WMS; no se persistió una paleta ajena ni se añadió un framework.

## 11. Fuera de la primera versión

Usuarios externos; consulta pública anónima; búsqueda independiente por BL; GPS/mapa; modificación de pedidos; mensajes/correos nuevos; nueva conexión SAP/DHL/Microsoft; certificación de aprobación de OC sin fuente; historial retroactivo; entrega al cliente; remodelación del WMS; dependencia del antiguo Odoo.

## 12. Comprobaciones de aceptación

1. Usuario sin permiso no obtiene datos del Tracking ni puede entrar por API/rutas operativas a través de su túnel.
2. Una OV con dos OC, dos BL y llegada parcial no aparece completa ni mezcla NP de otra compra.
3. Una OC para stock se consulta sin exigir OV; una fila sin BL sigue visible como etapa temprana.
4. Cotización y preliminar se distinguen de OV/OC; una OC de cinco dígitos sin aprobación no aparece aprobada.
5. Confirmada Triton sustituye la previsión principal pero no marca recibido. Fecha vencida sin llegada señala retraso/sin confirmación.
6. Recibido/ubicado/costeo/transferencia coinciden con evidencia y reglas actuales, con SLA idéntico al WMS.
7. Una búsqueda genera cero descargas de nube y cero llamadas DHL/IA; la actualización de la proyección usa el ciclo existente.
8. Corte fallido conserva el último dato bueno con aviso. No se filtran precios, secretos ni filas ajenas a la consulta.
9. Navegador real móvil/PC: carga, no encontrado, error/reintento, datos viejos, parcial y usuario sin permiso.
10. Pruebas pertinentes aprobadas y revisión externa Gemini del candidato exacto antes de aceptación; primera demostración sintética sin datos operativos en paquetes de revisión.

## 13. Decisiones pendientes del propietario

Aprobar o ajustar este alcance antes de construir. La falta de una fuente explícita de aprobación de OC y fecha de proveedor no bloquea un MVP honesto: se muestran Sin verificación/Sin dato. Si se requiere certificar esas dos cosas en la primera versión, debe identificarse la fuente antes de prometerlo.

Tras aprobación: plan pequeño en rama/worktree propios; implementar proyección y portal; probar permisos/casos parciales/carga; revisión externa vigente; presentación local; PR/instalación y túnel según autorizaciones. No se crea código de producto ni túnel durante esta fase de diseño.
