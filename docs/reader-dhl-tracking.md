# DHL Tracking: lector WMS

## Alcance y operacion

- API oficial Shipment Tracking Unified, sin wrappers externos. Solo Express
  y AWB numerica de diez digitos; una BL interna distinta requiere un mapeo
  explicito futuro, no se inventa una guia ni una BL.
- Carga automatica: BL COURIER abierta cuya fecha prevista o llegada fisica
  cae en el mes local del servidor. Tambien fechas previstas desde siete dias
  atras hasta catorce dias adelante, para cubrir cambios de mes. Hasta 100 guias
  unicas por precarga, priorizando futuras sin arribo fisico y fechas cercanas.
  No usar fechas
  de importacion/modificacion del Excel ni recorrer el historico de DHL.
- Al seleccionar/escanear una BL abierta AEREO/COURIER de diez digitos, se
  puede consultar puntualmente aunque sea anterior o no tenga fecha prevista.
  BL cerrada no se encola. Un formato numerico no demuestra por si solo que
  la guia pertenezca a DHL; 404 se muestra sin alterar la recepcion.
- Guias ya consultadas y todavia abiertas siguen actualizandose cada 24
  horas, incluso al cambiar el mes. Una recarga Excel o un escaneo no adelantan
  esa consulta. Nuevas guias detectadas se encolan en segundo plano sin esperar
  al siguiente ciclo diario. Nuevas consultas tienen prioridad.
  Una entrega DHL detiene las actualizaciones de esa guia.
- Cola, cache, intentos, ritmo y presupuesto se guardan en SQLite. Recargar
  pantallas o reiniciar no reinicia cuotas ni hace consultas duplicadas.
  Consultar estado en pantalla solo lee datos locales. La peticion externa
  ocurre en un hilo de servidor, sin transaccion SQLite abierta.
- El lector inicia directamente con el codigo unico del bulto. El endpoint
  `/api/receptions/truck-guide/scan-piece` resuelve el Piece ID en cache hacia
  una BL existente; no requiere escanear antes una BL y admite lecturas mezcladas.
  La ultima BL visible nunca se usa para asignar la siguiente lectura.
  BL cerrada, ambigua, inexistente o comprometida en otro camion activo se
  rechaza antes de modificar asociaciones. Un camion con pasos fisicos
  terminados permite otro arribo parcial de una BL aun abierta, con otra pieza.
  Repeticiones se deduplican tambien con los registros fisicos propios, aunque
  ya haya vencido el cache externo; no mover una pieza a otro camion.
- Los desconocidos/no disponibles NO se guardan contra la ultima BL. Quedan
  como lecturas sin guardar con Reintentar/Identificar BL/Descartar. Un asistente
  o admin puede confirmar explicitamente su BL existente para ESE bulto;
  queda auditado SIN VERIFICACION DHL, sin asignar lecturas posteriores.
  AUXILIAR_RECEPCION puede recibir piezas conocidas, pero no adivinar una BL.
  No bloquear otros transportistas: misma identificacion manual por excepcion.
  No se interpreta
  un AWB como identificador unico de todas sus cajas.
- Total DHL es informativo, no reemplaza cantidades del corte/operario,
  FR/EM, arribos parciales, SLA ni cierre. Delivered no recibe ni cierra la BL.
  DHL tampoco aporta el NP/cantidad por caja que requiere packing list/ASN.
- Datos externos minimos: estado normalizado, fechas, total y Piece IDs;
  sin guardar respuesta JSON, eventos completos, nombres, direcciones o POD.
  Se eliminan treinta dias despues de la entrega informada (y como maximo
  treinta dias desde la consulta sin entrega). Limpieza sigue ejecutandose
  con la integracion desactivada o sin clave. No elimina escaneos/historiales
  fisicos del WMS. Una guia expirada no se vuelve a consultar automaticamente.
  Si DHL dice entregado sin ninguna fecha de entrega valida, no se conserva
  ese cache; no se inventa la fecha. Backups online excluyen el cache externo
  y conservan los registros fisicos y contadores propios.

## Configuracion segura

Usar `infrastructure/docker-compose.dhl.yml` SOLO en el lector junto con las
configuraciones aprobadas de home/Microsoft. El agente usa un Compose fijo,
revisado en el servidor: agregar alli el secreto/environment despues de revisar
este PR; publicar el archivo de ejemplo no cambia ese Compose automaticamente.

- Guardar la clave en archivo del host fuera del checkout, permiso 0600;
  establecer `DHL_API_KEY_SOURCE` con su ruta absoluta. Compose lo monta en
  `/run/secrets/dhl_api_key`; no incluirlo en la imagen ni volumen publico.
  El montaje no cifra el archivo del host. Respaldar el DB solo en
  almacenamiento privado; el backup incorporado elimina el cache DHL de la
  copia, sin alterar el original. No hacer copias brutas externas del cache.
- Solo `DHL_API_KEY_FILE`; no aceptar clave del navegador, en URL, en Git,
  en `.env.example` ni en argumentos de proceso. API Secret no es necesario.
  Rotar credenciales compartidas en conversaciones antes de produccion.
- `WMS_DHL_ENABLED=1`, presupuesto `WMS_DHL_DAILY_BUDGET=200` (maximo200),
  `WMS_DHL_REFRESH_HOURS=24` (minimo 24; configuraciones antiguas de 8h se limitan
  a 24h), `WMS_DHL_PREFETCH_LIMIT=100` (maximo 100 por precarga).
  Presupuesto UTC compartido entre
  trabajadores de esta base, minimo5.2 segundos entre consultas y maximo10
  por guia/dia. Otras apps con la misma clave consumen cuota adicional.
- 401/403 detiene consultas hasta cambio de clave o reintento explicito del
  administrador; 429 pausa24h; fallas de red tienen backoff. Nunca exponer
  cuerpos de errores/proveedores en pantalla o logs. Reintentar no borra cuotas.
- Administrador: `Cortes diarios > Conectar con Microsoft` muestra
  estado DHL, consultas del dia, guias en cache y cola. No solicita correo/
  nueva autorizacion DHL por usuario; la clave reside en el servidor.

La cuota inicial publicada es250/dia, una cada5s y solo para desarrollo.
Solicitar ampliacion para uso empresarial, aunque el cache reduzca consumo:
[documentacion oficial](https://developer.dhl.com/tracking).
No prometer que200/dia alcanzara cualquier numero de guias abiertas.
Como dimensionamiento, 100 guias activas con una consulta diaria requieren unas
100 consultas exitosas, no una por bulto. Reintentos y consultas puntuales
comparten el mismo presupuesto de 200; si llegan al limite, se conserva la cola.
La cuota inicial de 250/dia sigue documentada para desarrollo; solicitar a DHL la
cuota de produccion no se sustituye por tener volumen bajo.

## Despliegue y pruebas

Cambios via PR aprobado/fusionado; nunca publicar desde una rama sin aprobar.
Mantener manual y su base intactos. Antes de habilitar, backup privado,
secreto montado y lectura de estado; despues, verificar hilo/heartbeat,
cache real de una guia propia y segundo escaneo sin otra peticion externa.
Los tests usan respuestas ficticias y bases temporales, no credenciales reales.
