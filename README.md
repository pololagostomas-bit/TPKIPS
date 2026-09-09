# TRITON WMS — Piloto independiente

## Inicio actualizado — revisión 0.2.0 (06/09/2026)

Estas instrucciones reemplazan los ejemplos antiguos de arranque de este documento.
No use `--reset` sobre registros operativos. Recepción controla tiempos y compromisos;
no incrementa el stock de Despacho. El stock proviene del corte Excel SAP.

En PowerShell, desde esta carpeta:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:TRITON_AUTH_MODE = 'local'
$env:TRITON_MAIL_ENABLED = '0'
.\.venv\Scripts\python.exe -m backend.setup_local
.\.venv\Scripts\python.exe .\app.py --host 127.0.0.1 --port 8000
```

Si `.venv` ya está instalado, omita su creación. Abra http://127.0.0.1:8000.
El asistente de configuración solicita el primer administrador solo si no existe.
Los usuarios se administran con el botón Usuarios; las contraseñas se almacenan
derivadas, no en texto plano. La sesión no permite cambiar de rol mediante el selector.
La aplicación conserva la base existente. Revise `TRITON_DB_PATH` si antes utilizaba
una ruta personalizada; no apunte involuntariamente a otra base.

Las tres cargas manuales están en **Cortes Excel** (en móvil, **Más opciones**):
OV/stock SAP, Importaciones y referencias FR/EM. Solo el administrador puede cargarlas.
Los reportes de carga usan eventos válidos de finalización, no la fecha de asignación.
La meta mínima es 20 OVs Y 200 unidades por día de lunes a viernes: verde al alcanzar
ambas, amarillo desde 70% y rojo por debajo. Semanas completas: 100 OVs y 1.000 unidades.

Linux y conservación del volumen: [Operación Linux](docs/OPERACION_LINUX.md).
Correo corporativo: [Configuración de correos](docs/CORREOS.md).
Verificación y límites: [Revisión 0.2.0](docs/REVISION_0_2_0.md).
La ejecución Docker y el envío real Microsoft 365 requieren validación con TI;
no se han desplegado ni enviado correos desde estas pruebas.

Piloto local que conserva el módulo validado de Despacho e incorpora un módulo independiente de Recepción. Esta carpeta no incluye ni modifica la base de datos del Triton Picking anterior.

## Módulos y permisos

- **ADMINISTRADOR:** puede ingresar a Despacho y Recepción, crear expedientes y consultar auditoría.
- **PICKER / GUIADOR:** solo pueden ingresar a Despacho.
- **ASISTENTE_RECEPCION / AUXILIAR_RECEPCION:** solo pueden ingresar a Recepción.

En Recepción, el administrador asigna el asistente y/o auxiliar de cada BL/AWB. Cada usuario solo ve y puede operar las BL que tengan su usuario en uno de esos dos campos; el administrador conserva la vista completa.

Recepción se abre en `http://127.0.0.1:8000/reception`. Permite cargar **IMPORTACIÓN DE REPUESTOS** desde el botón **Cargar Excel** del administrador, crear expedientes BL/AWB, registrar varios arribos físicos sobre la misma BL, congelar el flujo mientras exista saldo por arribar, cargar FR y EM desde el Excel contable, avanzar sus etapas, repetir ubicación cuando la muestra no sea conforme y conservar el historial.

El importador identifica todas las hojas que contengan `GUIA DE IMPORTACION` y `CODIGO`, agrupa por BL/AWB y carga IP, OC, OV, NP, descripción, cantidades, marca, transporte, país y fecha confirmada/estimada. Una recarga actualiza los datos fuente sin duplicar expedientes ni eliminar operaciones ya registradas. Los bultos esperados no se editan manualmente: el trabajador registra únicamente arribos acumulados; si la fuente no tiene una expectativa de bultos, el expediente queda como `ARRIBO REGISTRADO`.

El botón administrativo **Cargar FR/EM** procesa la hoja `FACTURAS DHL` del segundo Excel. Lee sus bloques con `AWB`, `IP`, `FACTURA RESERVA`, `ENTRADA DE MERCANCIA`, `FECHA DE RECEPCION` y `FECHA DE EM`; primero cruza por AWB/BL y usa IP solo como respaldo. Una BL puede conservar varias referencias FR/EM. Las filas sin coincidencia se reportan pero no crean BL nuevas ni alteran el flujo, las cantidades o los responsables. Volver a cargar el mismo archivo no duplica referencias.

Regla de habilitación: sin factura de reserva la BL queda como **PENDIENTE CONTABILIDAD** y no puede iniciar la revisión física; con factura de reserva pero sin EM queda como **PENDIENTE EM** y sí puede trabajarse para solicitar/generar la EM; cuando tiene FR y EM queda como **EM REGISTRADA**, se marca automáticamente como **CERRADO/COMPLETADO** al cargar el Excel contable y no requiere trabajo operativo de recepción. Si una BL tiene varias referencias, se controla cada FR/EM y la BL permanece pendiente mientras exista alguna FR sin EM.

En la cola de asistentes no aparecen BL con **PENDIENTE CONTABILIDAD**, **PENDIENTE FR** o **CONFLICTO IP**, porque corresponden a control administrativo. El administrador sí puede verlas y corregirlas. Una BL **PENDIENTE EM** sí aparece para que recepción continúe el trabajo correspondiente.

Regla por IP: una misma IP solo puede relacionarse con una combinación FR/EM. Si el Excel trae la misma IP con FR o EM diferentes, las filas conflictivas no se aplican, la BL queda como **CONFLICTO IP** y el administrador debe corregir el archivo antes de liberar la recepción. Las IP con la misma combinación repetida no generan conflicto. Si una IP ya tiene FR y EM, sus líneas quedan identificadas como contablemente completas; durante **REVISIÓN DE SISTEMA** todavía se pueden revisar y corregir cantidades, pero desde **EM** quedan bloqueadas para evitar reprocesos. La BL se marca **CERRADO/COMPLETADO** únicamente cuando todos los IP de sus líneas tienen FR y EM; una BL mixta permanece abierta para atender solo las líneas pendientes.

El flujo inicial es:

`Programado → Arribado → Revisión sistema → EM → Ubicación → Validación → Solicitud transferencia → Cerrado`

La revisión física se realiza con el packing list fuera de la aplicación; no es una etapa adicional en la interfaz vigente.

En **Revisión física** la aplicación muestra únicamente la información del arribo y oculta NP y cantidades: el trabajador realiza el conteo con el packing list físico. Al entrar a **Revisión sistema**, recién se muestra el detalle importado; las cantidades verificadas comienzan al 100% de lo facturado/esperado y se modifican solo cuando exista una diferencia u observación. Si una línea ya tiene FR y EM y la fuente trajo su cantidad verificada en cero, el sistema toma automáticamente la cantidad esperada como atendida; no sobrescribe una diferencia manual ya registrada.

Durante **Revisión física** existe una consulta opcional y cerrada de NP, descripción, OC y OV. Solo aparece si el trabajador la abre expresamente y no muestra cantidades, para conservar la independencia del conteo físico. En **Revisión sistema**, cada línea muestra OC, OV, FR y EM enlazadas por IP cuando la relación existe.

Las observaciones de Revisión sistema y la solicitud de transferencia se guardan en una bandeja auditable de notificaciones. En el piloto quedan como **PENDIENTE ENVIO**; el envío real requiere que TI configure Microsoft 365/Graph con la cuenta remitente autorizada. Por defecto se prepara el aviso para `mpucurimay@triton.com.pe`, configurable mediante `TRITON_IMPORTACIONES_EMAILS` y `TRITON_CONTABILIDAD_EMAILS`.

El botón **Reportes** es exclusivo del administrador. Muestra BL/AWB pendientes o próximas a llegar, agrupadas por etapa y transporte, junto con responsables, estado FR/EM, fecha programada y tiempo transcurrido. El control de atención usa la primera fecha de arribo registrada: **72 horas para AEREO/COURIER** y **96 horas para MARITIMO**. Una BL aún no arribada aparece como `SIN ARRIBO`; una abierta se marca como `DENTRO SLA`, `VENCE PRONTO` cuando le quedan 12 horas o menos, o `VENCIDO`.

## Flujo operativo actual

`Pendiente → Asignado → En picking → Picking finalizado → Por guiar → En guiado → Guiado finalizado → Entregado`

- El administrador asigna o reasigna al picker antes de que se inicie el picking.
- El picker asignado inicia y finaliza el picking.
- Al finalizar el picking, se guarda el evento `PICKING FINALIZADO` y la atención pasa automáticamente a `POR GUIAR`.
- El administrador asigna al guiador/entregador antes de que empiece el guiado.
- El guiador/entregador asignado inicia y finaliza el guiado, y registra la entrega.
- Una OV entregada puede generar una nueva atención independiente, con sus propias asignaciones e historial.
- Cada atención conserva una foto de sus líneas; una recarga posterior de SAP no altera su detalle histórico.
- El picker registra la cantidad recogida por línea; el guiador/entregador registra la cantidad entregada.
- Una atención completa solo puede finalizar si se recogió toda la cantidad planificada. Una entrega solo puede cerrarse cuando se entregó toda la cantidad recogida.
- El reporte operativo calcula tiempos de picking, espera de guiado, guiado y espera de entrega desde el historial.

## Ejecutar con el Excel

El argumento `--excel` pertenece solamente a Despacho/Picking:

```powershell
python .\app.py --excel "C:\ruta\exportacion_query.xlsx"
```

Para importar el archivo de Recepción desde PowerShell utiliza un argumento separado:

```powershell
python .\app.py --reception-excel "C:\ruta\IMPORTACIÓN DE REPUESTOS.xlsx"
```

Después de cargar las BL, también puedes importar las referencias contables:

```powershell
python .\app.py --accounting-excel "C:\ruta\FACTURAS DHL SEGUN IP Y AWB.xlsx"
```

No uses `--reset` para Recepción. También puedes iniciar normalmente con `python .\app.py`, entrar a `/reception` como administrador y pulsar primero **Cargar Excel** y después **Cargar FR/EM**.

Luego abrir `http://127.0.0.1:8000`.

No uses `--reset` al reiniciar la app si deseas conservar las atenciones registradas. El Excel puede volver a cargarse sin `--reset`; no duplica OVs, líneas ni atenciones.

Un administrador también puede usar **Cargar Excel** desde la barra superior. El archivo se procesa temporalmente y no se conserva; la carga actualiza las OVs sin eliminar atenciones ni historial.

### Filtro operativo del query SAP

Cuando el Excel contiene estas columnas, la aplicación aplica las reglas de almacén automáticamente:

- **Grupo de Articulo:** solo `Repuestos` y `Accesorios`.
- **Almacen:** solo `1`.
- **Status de Documento:** solo documentos `Abierta`/`Abierto`.
- **STATUS:** únicamente las líneas `OV ABIERTA` entran como SKU pendientes de despacho. Valores como `FACTURA DE RESERVA` o `DEUDORES` se contabilizan como SKU ya atendidos por SAP y aparecen en el indicador de la OV, pero no se pueden pickear de nuevo.

La vista de cada OV conserva como indicadores **Tipo de Atención**, **Situación de Máquina**, **Status de Documento SAP** y el resumen de `STATUS`. La confirmación de carga muestra cuántas filas quedaron fuera de estos filtros.

## Usuario de demostración

La barra superior permite elegir el rol y escribir el usuario que está probando la aplicación. El valor escrito debe coincidir con el usuario asignado por el administrador para que el picker o guiador pueda avanzar el estado.

Ejemplo: el administrador asigna `picker.juan`; para probarlo se selecciona el rol `PICKER` y se escribe `picker.juan` en **Usuario asignado**. No uses el botón de avance como administrador: el picker es quien inicia y finaliza su tramo.

Esta identificación es solo para las pruebas locales. En producción se reemplazará por Microsoft Entra ID.

## Preparación para Azure y PWA

La aplicación incluye `Dockerfile`, `azure.env.example`, manifiesto PWA, icono y un service worker. Para Azure, configura `HOST=0.0.0.0`, `PORT=8000`, `WEBSITES_PORT=8000`, una ruta persistente para `TRITON_DB_PATH` y `TRITON_AUTH_MODE=entra`.

Para un piloto de una sola instancia existe el script `deploy-azure-pilot.ps1` y la guía [AZURE_PILOT.md](AZURE_PILOT.md). Construye la imagen directamente en Azure Container Registry, por lo que no requiere Docker local. No uses Azure Files como ubicación de SQLite ni escales a varias instancias: para producción se migrará a PostgreSQL.

Para compartir el piloto con otra PC sin instalar Python, usa `infrastructure/docker-compose.yml` y la guía [docs/COMPARTIR_CON_DOCKER.md](docs/COMPARTIR_CON_DOCKER.md). La base SQLite queda en un volumen Docker persistente y no se incluye en el paquete distribuible.

## Estructura del proyecto

El código ejecutable está separado por responsabilidad:

- `backend/`: servidor HTTP y servicios de negocio.
- `frontend/`: plantilla de Recepción y archivos estáticos.
- `infrastructure/`: Docker, Compose y scripts de despliegue.
- `data/`: ejemplos, mapeos y esquemas; los Excel reales no se versionan.
- `tests/`: pruebas ejecutables con `py -m tests.nombre_del_test`.
- `docs/`: operación, Azure y futura integración SAP.
- `ui-design/`: wireframes, mockups y sistema visual.

La base operativa `triton.db` permanece en la raíz durante el piloto para proteger la compatibilidad con las cargas existentes. No se debe borrar ni reemplazar manualmente.

Azure puede usar `/health` como comprobación de disponibilidad del contenedor.

Al activar Microsoft Entra, asigna uno de estos roles de aplicación: `ADMINISTRADOR`, `PICKER`, `GUIADOR`, `ASISTENTE_RECEPCION` o `AUXILIAR_RECEPCION`. La app toma la identidad del encabezado que App Service agrega después de autenticar al usuario.

SQLite permite el piloto en una sola instancia. Antes de usar varias instancias o producción se debe migrar la base a Azure Database for PostgreSQL.

## Preparación para SAP Business One

`sap_service_layer.py` es un cliente de solo lectura para Service Layer. Usa `sap.env.example` como guía y guarda las credenciales reales en Azure Key Vault, nunca en el código ni en el Excel.

Falta confirmar con TI/SAP la consulta OData y el identificador estable de cada línea (`DocEntry` + `LineNum`). El contrato completo, los campos necesarios y las reglas para no alterar el historial están en [SAP_INTEGRATION.md](SAP_INTEGRATION.md).

## Pruebas incluidas

```powershell
py -m tests.test_phase2
py -m tests.test_real_import "C:\ruta\exportacion_query.xlsx"
py -m tests.test_reception_import "C:\ruta\IMPORTACIÓN DE REPUESTOS.xlsx"
py -m tests.test_reception_accounting_import "C:\ruta\IMPORTACIÓN DE REPUESTOS.xlsx" "C:\ruta\FACTURAS DHL.xlsx"
py -m tests.test_security
py -m tests.test_http
```

Las pruebas cubren roles, reasignaciones, estados, historial, entrega, importación de BL/AWB y la carga repetible de FR/EM sin duplicados ni alteración del flujo.

## Alcance pendiente para producción

- Usuarios reales y permisos mediante Microsoft Entra ID.
- Conexión de solo lectura con SAP Business One.
- Registro de cantidades efectivamente recogidas y entregadas por línea.
- Datos de stock y cantidad pendiente provenientes de SAP para validar atención parcial o completa.
- Base de datos PostgreSQL administrada para producción y escalamiento.
- Autenticación Microsoft Entra configurada en el recurso real de Azure.
- Publicación del piloto y posterior despliegue productivo en Azure.
