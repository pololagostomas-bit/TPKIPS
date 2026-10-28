# Stock Power BI y trazabilidad de cortes

Actualizacion2026-10-27: el conector automatico opt-in esta descrito en
[powerbi-stock-auto.md](powerbi-stock-auto.md). Sustituye el estado anterior
not_implemented por un estado local verificable de carga/corte. La descripcion
que sigue conserva el diagnostico inicial y sus limites; no representa una
fuente ya activada por instalar este codigo. El lector requiere aprobacion y
configuracion privada, y el despliegue manual permanece congelado.

El codigo exacto del articulo Power BI gobierna la identidad del stock: no
fusionar codigos por quitar espacios, puntos o guiones. Cada codigo mantiene su
cantidad y ubicaciones propias, incluyendo las consultas y etiquetas WMS.

Lo que sigue es documentacion historica del diagnostico previo al conector;
para configuracion y comportamiento actuales consultar el contrato enlazado.

Alcance: lector. La variante manual esta congelada. Este cambio prepara un PR;
no autoriza instalar, reiniciar ni modificar configuracion o permisos.

## Evidencia y limite actual

En la base aprobada `64904db5639d`, `cloud_excel.py` descarga `.xlsx` de Graph
y `cloud_sync.py` los importa con las reglas existentes. `cloud_auth.py` solicita
scopes Graph para archivos/correo; su token no acredita acceso a Power BI.
`POWERBI_STOCK_REPORT_ID` solo producia un mensaje de pendiente. No habia cliente
BI, `executeQueries`, mapeo de modelo ni filtro BI comprobado de almacen 01.
Un reporte/embed no es un archivo Excel ni su ID es el ID del modelo semantico.
Una tabla/archivo ExcelStock y un corte local tampoco prueban ese origen.

La verificacion operativa se conserva por separado en evidencia privada. No
publicar identificadores de destino, cuentas, tokens, filas, cache ni historial
productivo. Un panel con fuentes Graph correctas no acredita acceso al modelo BI;
el corte de stock local y el ultimo refresh de Power BI son hechos distintos.

## Contrato para integracion

Se amplia **GET/HEAD `/api/cloud-connection/status`**, con el mismo permiso
administrador. No hace falta una ruta nueva ni editar `backend/app.py`.
Los campos existentes mantienen su forma; `connection.resource` ahora es
`microsoft_graph_excel`. `interval_seconds` y `automatic_enabled` siguen siendo
el sondeo WMS de archivos Excel. No representan frecuencia ni ejecucion de un
refresh del modelo Power BI.

Nuevo `powerbi_stock`:

- `state=not_implemented`, `connector_implemented=false`, `stock_connected=false`.
- `configuration.report/workspace/dataset`: `missing`, `invalid` o `declared`;
  nunca devuelve IDs/URLs. Declarado no significa validado ni accesible.
- `required_warehouse="01"`, `warehouse_filter_verified=false`.
- `api_access=model_mapping="unverified"`.
- `refresh_schedule={"state":"unknown"}`, `last_refresh_at=null`.
- `action`: requisito pendiente controlado, sin respuestas Microsoft ni secretos.

`POWERBI_STOCK_WORKSPACE_ID` y `POWERBI_STOCK_DATASET_ID` son nombres reservados
para diagnostico local. Este cambio NO los configura ni implementa acceso API.
`registered_stock_import` es null o `{import_id,cutoff_at,source_kind:"excel",
powerbi_verified:false}` del corte stock vigente por cutoff/id en `data_imports`.
No infiere carga cloud, frescura BI ni procedencia de una fila operativa.

`sources[].source_kind=excel` identifica el conector actual; Stock Excel se
muestra separado del estado Power BI. Un enlace del dominio Power BI en
`GRAPH_SHARE_URL_*` tiene `health=configuration_error`; al sincronizar falla con
`source_not_excel` antes de adquirir token o llamar Graph. Los errores preservan
las cargas anteriores. La consulta del panel no sincroniza ni refresca BI.

## Metadatos Microsoft: siguiente integracion

Requiere identificar privadamente workspace y dataset del reporte esperado,
validar su modo de conexion y acordar columnas/medidas, unidades, fecha de corte
y filtro exclusivo de almacen 01. El token debe pertenecer al recurso Power BI,
con permisos efectivos sobre ese modelo. No reutilizar un bearer Graph, abrir
consentimiento automaticamente ni ampliar los scopes del flujo Excel existente.

[Get Refresh Schedule In Group](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/get-refresh-schedule-in-group)
usa GET `groups/{groupId}/datasets/{datasetId}/refreshSchedule` y
`Dataset.Read.All` o `Dataset.ReadWrite.All`. Retorna dias, horas y zona horaria
para modelos importados; una programacion no prueba una ejecucion correcta.
DirectQuery/LiveConnection tienen otro endpoint de programacion:
[Get Direct Query Refresh Schedule In Group](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/get-direct-query-refresh-schedule-in-group).

[Get Refresh History In Group](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/get-refresh-history-in-group)
usa GET `groups/{groupId}/datasets/{datasetId}/refreshes?$top=1`. Ademas del scope
Dataset, Microsoft exige Write sobre el modelo y no devuelve historial de
refresh OneDrive. `Unknown` puede ser en curso; `Completed` con fin valido
acredita ese refresh, no una importacion WMS. Un 403 de historial no prueba que
las consultas de stock carezcan de permiso. No pedir permisos adicionales solo
para que el panel parezca completo; mostrar metadatos no disponibles.

[Execute Queries](https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries)
requiere habilitar Dataset Execute Queries REST API en el tenant, Read y Build
del modelo, y scope `Dataset.Read.All` o `Dataset.ReadWrite.All`. Solo DAX: ese
endpoint no admite INFO, DMV ni MDX. Una consulta, una tabla por llamada;
limites de 100000 filas/1000000 valores, 15 MB y 120 solicitudes/minuto/usuario.
Un HTTP200 puede contener errores o resultado limitado: validar el cuerpo,
sin registrar filas ni mensajes privados. Service principal tiene restricciones
con RLS/SSO. No confundirlo con el endpoint distinto Execute Dax Queries.

La siguiente validacion autorizada debe limitarse a metadatos del destino
confirmado, con timeout y sin reintentos automaticos. No ejecutar consultas de
stock, POST refreshes, PATCH schedules ni cambios de consentimiento para este
diagnostico. Un conector futuro debe validar el filtro 01 con datos sinteticos
y comprobar acceso real antes de cambiar `stock_connected`.

## Checks

Pruebas sinteticas en `test_cloud*` y `test_powerbi_stock.py`: aislamiento Graph/BI,
sin red al leer estado, IDs redactados, URL embed rechazada antes del token,
permisos admin y trazabilidad del corte local. La UI comprueba fecha del corte,
separacion de estados, errores/reintento y reflow; un error de lectura deshabilita
acciones hasta obtener estado valido y marca el estado anterior sin actualizar.
Las pruebas no certifican una conexion BI ni hardware Android.
