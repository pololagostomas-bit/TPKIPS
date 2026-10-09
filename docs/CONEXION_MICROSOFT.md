# Cortes Excel con Microsoft 365

El administrador abre `Microsoft 365` en el WMS y autoriza una cuenta corporativa
en la pagina oficial de Microsoft. No se solicita ni almacena su contrasena.
Los empleados conservan la autenticacion local del WMS.

Decision del propietario 2026-10-09: OV se carga manualmente en ambos pilotos.
`WMS_CLOUD_DISPATCH_MODE=manual` excluye dispatch de la sincronizacion nube aun
si se conserva un antiguo enlace OV. No se requiere enlace OV para esta conexion.

TI debe registrar una aplicacion propia en el tenant corporativo, habilitar
"Allow public client flows" para device code y aprobar el permiso delegado
Microsoft Graph `Files.ReadWrite` requerido por `/shares/.../driveItem`.
El conector solo efectua GET; nunca escribe en los Excel. No reutilizar un
Client ID de otra aplicacion sin verificar propiedad y permisos.

El Client ID puede guardarse desde el panel administrativo o configurarse por
`GRAPH_CLIENT_ID`. Las URLs se configuran privadamente en `GRAPH_SHARE_URL_*`.
No incluir enlaces compartidos, archivos reales, tokens o claves en Git.

Ambos contenedores pueden montar un volumen dedicado Microsoft. La cache y
sus metadatos usan directorio 0700, archivos 0600, reemplazo atomico y bloqueo
entre procesos. No estan cifrados en disco: quien administre el host/volumen
puede acceder a ellos. Proteger y cifrar el disco del servidor. No compartir
las bases operativas ni incluir la cache en exportaciones/backups de negocio.
Desconectar elimina el acceso local para las dos versiones; la revocacion del
consentimiento en Microsoft se gestiona aparte.

MSAL renueva el acceso sin navegador. MFA, revocacion, cambio de permisos o
politicas de TI pueden exigir autorizacion otra vez. Una cache presente no
certifica acceso al archivo: el estado por fuente refleja las consultas reales.

Con `WMS_CLOUD_AUTO_SYNC=1` el worker consulta cada 300 segundos (minimo).
Esta consulta periodica no es una notificacion inmediata ni refresca Power BI.
Cada base registra su propio resultado. El contenido igual al ultimo corte
no se reimporta; la fecha automatica es `lastModifiedDateTime` de SharePoint,
no la hora de consulta ni una fecha de corte de negocio inventada.
Archivos anteriores al corte vigente son rechazados por las reglas actuales.
Una fuente con error no impide revisar la otra. La conciliacion automatica
de entregas permanece desactivada; no se alteran claves, roles o estados
administrativos por el conector. La carga manual sigue disponible.

El enlace de Power BI identifica un reporte, no un Excel ni su modelo de datos.
El stock permanece pendiente hasta identificar dataset/workspace, tabla y
columnas y verificar Read+Build y el ajuste Execute Queries del tenant.
Usar exclusivamente almacen `01`, con prueba de exclusion de otros almacenes
antes de activarlo. No transformar el enlace del reporte en una fuente stock.
Alternativa: obtener de TI el Excel fuente/exportacion autorizada del stock.

Referencias verificadas el 2026-10-09:
- https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-acquire-token-device-code-flow
- https://learn.microsoft.com/en-us/graph/api/shares-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries
