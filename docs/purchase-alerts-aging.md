# Purchase Alert Observation History

The reader's existing admin page, Alertas de compras / OC, includes an aging
history and CSV download. Viewing or exporting this history only reads the
private purchase-alert SQLite; it does not download Excel, send mail, query SAP
or access the operational WMS database. Existing worker scheduling and Microsoft
authorization are reused. No additional scheduler or mail integration is needed.

## Rules

- IP exactly X after trimming and case folding excludes the entire row from both
  rules. X123 is not excluded. Existing excluded archive sheets stay excluded.
- PRELIMINAR / REGULARIZAR: IP is present and the OC contains PRE or more than
  five digits in total. Two five-digit references still satisfy the digit rule.
- COT / GRAVE: OV starts with COT and has any OC or IP, even a five-digit OC.
  This is an independent rule. One order can have both issues and both clocks;
  severity identifies the higher-priority issue, not a physical WMS status.
- Nothing in these rules writes to the workbook, changes SAP or closes a BL.

## Request Dates And Report Priority

Initial, daily and incremental mail separates GRAVE / COT issues first from
ordinary preliminary/OC with factory-order issues. New and previously reported
cases remain distinct inside each level. These are separate rules, not exclusive
row classifications: the same order can appear once for each applicable rule.
Speech, recipients, schedule and delivery keys are unchanged.

Each table includes Fecha de solicitud IMP/OV from that specific source column
(with or without DE or the slash in IMP/OV). Native Excel dates, numeric serials
using the workbook epoch and unambiguous day/month/year or ISO date strings are
accepted. Missing/invalid values and old records display Sin fecha; alerts still
run. ETA, synchronization time and first detection are never substituted.

Dates are retained per source row in the existing private JSON payload. Grouped
cases display all distinct dates in chronological order, plus Sin fecha if any
source lacks a usable date. Updating a date does not change case/episode identity
or reset its clock. History and CSV include the same date field and order grave
issues first, including when viewing both pending and resolved episodes. The
admin history keeps severity filters; mobile history/mail stack fields instead
of widening the whole page. No workbook date is used to backdate observation.

## Clock And Identity

The clock starts at the first successful observation after installation, not
the unknown original creation time. It measures continuous calendar hours,
independently of the operational BL SLA calendar. Revisions update last observed
time; resolved periods keep a frozen end time and remain downloadable.

An ordinary issue is identified by normalized IP, not sheet row or PRE text.
Changing PRE while the same IP remains irregular does not reset its clock.
All OC values observed for that IP in a revision are retained together. COT
issues additionally use normalized OV; without IP they use OC plus OV. If IP
itself changes, there is no stable source identifier to prove continuity, so a
new issue may be created. Reappearance after resolution starts a new episode.

A completed, validated revision can end an episode when it no longer satisfies
the rule or is absent from the checked sheets. This is an observed end, not
proof of an approved OC, physical transfer or SAP verification. Resolution is
detected at the next successful revision, not the exact instant of an Excel edit.

Failed downloads, invalid formulas, missing previously recognized sheets and a
missing OV column on a sheet with open COT issues do not resolve previous issues.
Deliberately excluded sheets retain their history without claiming correction.
If a case spans checked and excluded sheets, the excluded evidence is retained
as Hojas sin revisar; correcting only the checked sheet cannot resolve it.
Old history is not reconstructed from mail or guessed from spreadsheet dates.

## Access And Download

Only administrators can view or export. Filters cover pending/resolved/all and
grave/ordinary levels, with 50 rows per page. Dates display in Lima; CSV timestamps
are UTC. CSV includes issue, reference, source sheets, detection/observation/end,
calendar hours and resolution explanation. Formula-like cell values are escaped;
UTF-8 BOM supports Excel. Downloads are single-flight in the page and capped at
50000 filtered episodes, keeping generation separate from the production DB.
# Seguimiento por solicitud y Excel completo — 2026-10-27

El corte fijo es **01/10/2026 inclusive**, por la fecha de solicitud IMP/OV del
origen. No es la ETA, la fecha de deteccion ni una ventana movil. En Alertas de
compras, el periodo inicial es Desde el 01/10/2026. Se puede consultar Historico,
Sin fecha o Todas las fechas y combinarlo con estado/nivel. El orden del historial
es fecha de solicitud descendente antes de paginar; en el correo se conserva la
separacion COT grave / preliminar y nuevos / anteriores, con fecha descendente
dentro de cada grupo. Si un caso agrupa fechas diferentes, se muestran todas y
se ordena por la mas reciente del periodo seleccionado.

El correo adjunta `alertas_compras_historial.xlsx`; el mismo archivo se obtiene
con Descargar Excel completo. Incluye **Recientes** y **Historico**, tanto
pendientes como resueltos, independientemente de los filtros de pantalla.
Si hay fechas ausentes o invalidas agrega **Sin fecha**. Un episodio con fuentes
de distintos periodos puede aparecer en varias hojas con el mismo ID: no son
compras adicionales. Las fuentes y fechas se separan sin borrar evidencia ni
cambiar el reloj. Celdas de texto, fechas Excel, filtros y cabecera inmovilizada.
Se mantiene el CSV anterior para clientes existentes.

Filtrar por fecha nunca resuelve un episodio: se observa el Excel completo antes
de filtrar. Un caso historico nuevo no dispara un correo incremental; sigue en
SQLite y el adjunto. El resumen diario y un envio manual conservan el historial
aunque ya no queden pendientes. Una correccion de fecha puede cambiar el periodo
sin crear otro episodio. Los episodios ya resueltos sin fecha registrada quedan
Sin fecha: no se inventan fechas ni cambios anteriores a la primera observacion.

Se usa la autorizacion Mail.Send existente. El XLSX se genera en memoria solo al
descargar/enviar; la vista previa no retorna base64. Maximo 50000 episodios; si el
adjunto excede 2500000 bytes o el payload 3800000 bytes, el envio falla antes de
crear la salida, sin omitir silenciosamente casos. El Excel completo sigue
disponible en la app dentro del limite de episodios. La auditoria de envio guarda
metadatos, no otra copia permanente del binario. No cambia el horario/remitente,
texto aprobado, destinatarios, reglas OC/COT/X ni permisos administrativos.

El transporte sigue el ejemplo oficial de
[sendMail con adjunto](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0#example-3-create-a-message-with-a-file-attachment-and-send-the-message).
HTTP 202 confirma aceptacion de Microsoft, no entrega/lectura.
