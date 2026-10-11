# Recepcion: Trabajo en Curso

## Documentos y Mercaderia

La existencia de FR y EM no demuestra una llegada fisica en el WMS. El resumen
documental valida todas las IP esperadas, no solo las IP ya recibidas. Una FR sin
EM, una IP faltante o un conflicto contable impiden marcar documentos completos.

Las BL documentadas sin evidencia operativa quedan en el historial de trabajo
como `FR/EM COMPLETAS`. Esto no cambia su estado almacenado, no inventa cantidades
ni las cierra. Si tienen bultos recibidos, atenciones, guia confirmada o una etapa
operativa posterior, continuan en trabajo hasta terminar su flujo.

Una llegada heredada cuyo ultimo evento de arribo es `IMPORTACION EXCEL` no inicia
el SLA del trabajador. Con documentos incompletos permanece visible en su etapa,
con la advertencia de verificar la fecha fisica. Un recibo positivo registrado
en WMS prevalece sobre la fecha heredada. Etapas avanzadas sin inicio quedan como
datos por revisar, no se rebajan a pendiente de arribo.

## SLA e Indicadores

Se conserva la regla actual: 96 horas para MARITIMO y 72 para AEREO/COURIER,
horas continuas de lunes a sabado, excluyendo domingos. No se descuentan turnos,
feriados ni pausas administrativas. Cada atencion parcial usa su propio recibo
positivo; si falta, usa el primer arribo operativo valido de la BL.

La vista muestra inicio, fecha limite y tiempo restante. Al faltar 12 horas o
menos es amarillo; vencido es rojo. Sin inicio verificable no hay tiempo ficticio.
Una BL se cuenta una sola vez por indicador y por etapa. Si tiene varias
atenciones, su indicador de urgencia usa el peor SLA. Los trabajadores solo ven
sus atenciones; el administrador conserva las correcciones existentes con motivo
y auditoria. El resumen global no depende de las diez BL de la cola operativa.

## BL Vacias y Reglas Por Confirmar

El ingreso actual de camion primero busca la BL; si no existe, el administrador
o asistente puede crear un expediente provisional. No copia informacion de otra
BL ni inventa NP, cantidades o bultos esperados. Cero bultos documentados significa
total desconocido, no carga terminada. Para habilitar EM el flujo existente exige
al menos un SKU encontrado y la FR correspondiente.

Quedan decisiones de negocio, no autorizadas automaticamente por este cambio:

- Permitir BL provisionales o exigir exclusivamente BL existentes en Importaciones.
- Revisar el transporte de las provisionales: actualmente nace como AEREO y puede
  requerir correccion antes de aplicar el SLA de una carga maritima.
- Confirmar si el SLA debe seguir siendo continuo sin domingos o contar turnos y
  feriados. Es tiempo de la carga, no productividad individual del trabajador.
- Definir quien concilia BL historicas sin fecha WMS o con atenciones cerradas y
  estado maestro abierto. La vista las senala; no las elimina ni cierra.

Los cambios se proponen por PR y solo se despliegan despues de aprobacion y merge,
por separado para manual y lector. Las pruebas usan datos ficticios.
