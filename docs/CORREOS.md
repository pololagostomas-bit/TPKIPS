# Correos de Recepción por Microsoft Graph

El servicio `backend/services/notifications.py` consume la bandeja durable
`reception_notifications` que ya llena el dominio de Recepción. Cada fila conserva
su destinatario, asunto y cuerpo; el sender no sustituye destinatarios ni presupone
cuentas por tipo de aviso.

El correo está **deshabilitado por defecto**. Tener credenciales configuradas no es
suficiente: solo se reclama una fila cuando `TRITON_MAIL_ENABLED=1`.

## Configuración

La identidad de Microsoft Entra debe ser una aplicación con permiso de aplicación
Microsoft Graph `Mail.Send` y consentimiento administrativo. Se recomienda limitar
en Exchange Online los buzones que esa aplicación puede usar. El buzón remitente
predeterminado es `tomas.polo@triton.com.pe`; la aplicación debe estar autorizada
para enviar como ese usuario.

Referencias oficiales: [flujo OAuth client credentials](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
y [`user: sendMail` de Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).

Variables preferidas de Triton:

```text
TRITON_MAIL_ENABLED=1
TRITON_GRAPH_TENANT_ID=<tenant UUID>
TRITON_GRAPH_CLIENT_ID=<application/client UUID>
TRITON_GRAPH_CLIENT_SECRET=<secreto>
TRITON_MAIL_FROM=tomas.polo@triton.com.pe
```

También se aceptan `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` y
`AZURE_CLIENT_SECRET` como fallback. Si están presentes ambos juegos, prevalecen
las variables `TRITON_GRAPH_*`. Opcionales:

- `TRITON_GRAPH_ENDPOINT`: predeterminado `https://graph.microsoft.com/v1.0`.
- `TRITON_MAIL_HTTP_TIMEOUT_SECONDS`: predeterminado 30 segundos.

Los secretos deben inyectarse desde el almacén de secretos del entorno y no deben
guardarse en el repositorio ni en la base SQLite.

No se agrega ninguna dependencia Python: el cliente HTTP usa exclusivamente
`urllib` y otros módulos de la biblioteca estándar.

El flujo OAuth usa client credentials contra
`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` con scope
`https://graph.microsoft.com/.default`. El envío usa
`POST /users/{TRITON_MAIL_FROM}/sendMail` y contenido `Text`.

## Estados, reintentos y seguridad ante caídas

- `PENDIENTE ENVIO`: disponible o esperando `next_attempt_at`.
- `ENVIANDO`: claim durable y exclusivo adquirido antes de tocar la red.
- `ENVIADO`: Graph devolvió una respuesta 2xx.
- `ERROR`: fallo definitivo o agotamiento del máximo de intentos.
- `REVISAR ENVIO`: resultado ambiguo. No se reenvía automáticamente.

Los HTTP 408, 429 y 5xx se reintentan con backoff exponencial, hasta tres intentos
por defecto. Los demás 4xx, incluido 403 por permiso denegado, terminan en `ERROR`.
Un corte de red puede ocurrir después de que Graph haya aceptado bytes; por eso los
errores de transporte desconocidos pasan a `REVISAR ENVIO`. Si un proceso muere
dejando `ENVIANDO`, otro ciclo lo mueve a `REVISAR ENVIO` al vencer el claim (15
minutos por defecto). Solo `retry_notification(connection, id, actor)` puede reabrir
un `ERROR` o `REVISAR ENVIO`, registrando quién lo solicitó.

Una caída al obtener el token sí se considera reintentable: en ese punto todavía no
se llamó a `sendMail` y no existe riesgo de duplicar un correo.

## Hooks pendientes en `main`

La integración principal debe:

1. Ejecutar `init_notifications_schema(connection)` después de
   `init_reception_schema(connection)` durante la inicialización de la base.
2. Ejecutar periódicamente `process_notifications(DB_PATH)` en un worker separado
   del request que encola la notificación. La función abre sus propias conexiones
   SQLite, reclama de forma transaccional y devuelve contadores del ciclo.
3. Exponer para administración `notification_summary(connection)` y una acción
   protegida que llame `retry_notification(connection, id, actor)`. El `actor` debe
   provenir de la identidad autenticada, no del cuerpo libre de la solicitud.

`notification_summary` devuelve `total`, `other` y `by_status`, con una clave para
cada uno de los cinco estados conocidos.

## Pruebas sin envío real

El transporte es inyectable mediante `process_notifications(..., transport=...)`.
Las pruebas usan solamente dobles locales; no invocan Microsoft Graph:

```powershell
py -m unittest tests.test_notifications
```

Cubren éxito, permiso denegado, reintentos acotados con backoff, dos workers sobre
la misma fila, configuración ausente y resolución administrativa de un resultado
ambiguo.
