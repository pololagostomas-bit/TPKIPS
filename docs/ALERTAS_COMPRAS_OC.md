# Alertas de compras / OC

Funcionalidad compartida por lector y manual. Administracion en **Mi perfil >
Herramientas y opciones > Alertas de compras / OC**. La configuracion inicial
esta pausada y sin direcciones corporativas en el codigo publico.

## Regla aprobada

- Pedido Triton no vacio, y OC con mas de cinco digitos **sumados en toda la
  celda**, o texto PRE sin distinguir mayusculas.
- Se alerta incluso si la celda contiene dos OC de cinco digitos: indicacion
  expresa del propietario. No dividirlas ni excluir ese caso silenciosamente.
- ANIBAL.23.04 se excluye. Las demas hojas con las columnas requeridas se
  recorren completas, aunque la fila no tenga guia ni codigo de repuesto.
- Una combinacion preliminar/OC e IP es un caso. Filas duplicadas se agrupan,
  manteniendo hojas y numeros de fila. Pedido Triton proporciona la IP.
- El criterio de cinco digitos no certifica por si solo aprobacion en ERP.
  Se solicita validar y actualizar el registro, sin alterar estados del WMS.

## Programacion y correo

Al habilitar se envia el primer reporte completo. Revision cada 60 minutos,
editable entre 5 y 1440. Solo casos nuevos generan aviso incremental; tambien
se incluyen los demas pendientes. Se comparan identidades, no solo totales:
un caso nuevo y otro regularizado siguen justificando un aviso. Solo resolver
casos no genera un correo adicional.

Resumen completo de lunes a viernes a las 10:00 America/Lima, una vez por fecha
y solo con pendientes. Hora y dias editables. Una revision horaria que coincide
con el resumen produce un solo correo. Si el servidor estuvo apagado, al volver
durante un dia habilitado despues de la hora envia el resumen de ese dia, no
reproduce todos los dias omitidos. Fuera de los dias del resumen siguen vigentes
las revisiones de casos nuevos. Es necesario mantener encendido el servidor.

Remitente, firma, Para, CC, asuntos y texto editables. Marcadores permitidos:
`{fecha}`, `{total}`, `{nuevos}`, `{pendientes}`. Las tablas de preliminar e IP
se anexan siempre y el HTML se escapa. Vista previa nunca envia. Guardar texto
o destinatarios no autoriza Microsoft ni certifica entrega.

Correo separado de recepcion, recuperacion y avisos de acceso: no habilitar
TRITON_MAIL_ENABLED para activar estos reportes. Autorizar Mail.Send desde el
panel con la misma cuenta configurada como remitente. La app Entra debe tener
ese permiso delegado y TI puede exigir consentimiento/MFA. Los tokens quedan
en el servidor, nunca en la API de estado, correo o navegador.

Un 202 de Graph indica aceptacion, no lectura. Timeouts, respuestas ambiguas o
caida durante envio quedan REVISAR ENVIO, sin reenvio automatico. El admin debe
revisar enviados y registrar el resultado. Fallos conocidos quedan ERROR; para
reenviar se usa Enviar reporte ahora con confirmacion y una nueva lectura del
Excel. No se manda informacion de un archivo fallido, incompleto o con errores
en OC/IP. El ultimo snapshot valido se conserva y el panel muestra el fallo.

## Instalacion posterior al PR aprobado

1. Fusionar el PR por el propietario. No instalar codigo ni modificar Compose
   vivo antes de esa aprobacion. El agente actual no despliega ambas variantes.
2. Construir imagen completa del lector o el overlay para cada base aprobada
   usando infrastructure/cloud-overlay/Dockerfile. El overlay conserva app,
   pantallas, workflows y base manual; agrega solo la navegacion y el modulo.
3. Usar el mismo volumen protegido triton-wms-microsoft-auth en ambos programas
   con GRAPH_TOKEN_CACHE_PATH=/home/microsoft/cache.json y
   WMS_PURCHASE_ALERT_DB=/home/microsoft/purchase-alerts.sqlite3. Activar el worker
   con WMS_PURCHASE_ALERT_WORKER=1 en infraestructura privada revisada. El
   override docker-compose.microsoft.yml documenta estas opciones.
4. Retirar o actualizar los binds antiguos de password_policy.py al codigo
   aprobado: un shim montado desde el host puede ocultar la version de la imagen
   y dejar el panel/worker nuevo inaccesible. No sustituir otras cuentas/politicas.
5. Instalar la configuracion privada pausada mediante el panel o
   `python -m backend.services.purchase_alerts --configure /ruta/config.private.json`.
   Este comando exige enabled=false. No guardar direcciones/Excel/tokens en Git.
6. Confirmar cuenta remitente y permiso Mail.Send, previsualizar el primer
   reporte y luego activar desde el panel. Verificar aceptacion y enviados.

La base de reportes y bloqueo son compartidos: dos contenedores no pueden hacer
el mismo envio en paralelo. Las bases operativas permanecen separadas. Directorio
0700 y archivos 0600 en Linux; el contenido no esta cifrado en disco. Incluir el
estado de reportes en el respaldo privado: perderlo puede repetir la linea base.

## Fuentes

- Microsoft Graph sendMail: https://learn.microsoft.com/en-us/graph/api/user-sendmail
- Zona horaria multiplataforma: https://pypi.org/project/tzdata/
- Pruebas sinteticas: tests/test_purchase_alerts.py, test_cloud_connection.py y
  test_cloud_overlay.py. No prueban entrega al buzon empresarial real.
