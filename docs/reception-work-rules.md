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
horas continuas de lunes a sabado, excluyendo domingos y feriados nacionales de
Peru, en hora de Lima. El sabado cuenta completo por ahora; no se aplica aun el
turno 08:00-13:00. Cada atencion parcial usa su propio recibo
positivo; si falta, usa el primer arribo operativo valido de la BL.

La vista muestra inicio, fecha limite y tiempo restante. Al faltar 12 horas o
menos es amarillo; vencido es rojo. Sin inicio verificable no hay tiempo ficticio.
Una BL se cuenta una sola vez por indicador y por etapa. Si tiene varias
atenciones, su indicador de urgencia usa el peor SLA. Los trabajadores solo ven
sus atenciones; el administrador conserva las correcciones existentes con motivo
y auditoria. El resumen global no depende de las diez BL de la cola operativa.

El calendario usa `holidays==0.106` y la misma funcion para horas transcurridas,
limite e indicadores/reporteria. No traslada al lunes feriados que caen domingo.
Fuentes consultadas el 2026-10-11: [Estado Peruano](https://www.gob.pe/feriados)
y [calendario Peru de holidays](https://holidays.readthedocs.io/en/latest/auto_gen_docs/peru/).
No incluye automaticamente puentes compensables del sector publico. TI puede
agregar descansos internos mediante `WMS_SLA_EXTRA_HOLIDAYS`, una lista JSON de
fechas ISO, por ejemplo `["2026-10-09"]`; errores de calendario no se ignoran.

## Reglas Confirmadas: 2026-10-11

El propietario confirmo que la BL debe existir ANTES del ingreso o escaneo. Una
BL desconocida produce un aviso para actualizar el corte o solicitar su registro
administrativo, sin crear un expediente provisional. Se conserva el alta
administrativa y la importacion como medios separados de registrar una BL real.
Cero bultos esperados significa total desconocido, no cero pendiente ni carga
completa. Una BL conocida puede tener varios arribos, cada uno con su atencion,
cantidades, documentos e inicio SLA propios; no necesita manifiesto previo.

Cerrar una atencion NO cierra la BL si otra sigue abierta, hay un camion
confirmado por llegar, una llegada sin atencion, saldo de bultos/unidades o FR/EM
faltante para alguna IP. El estado maestro sigue la primera atencion abierta;
si todas terminan pero queda saldo, queda ARRIBADO con su motivo. Cuando todo
queda completo, el estado principal queda CERRADO. Registrar una EM no salta el
trabajo de ubicacion/validacion/transferencia de una atencion todavia abierta.

Los historicos documentales sin recepcion WMS no se cierran por consultar la
pantalla ni por una sincronizacion documental. En Trabajo en curso / Historial,
el administrador usa `Conciliar cierre`, confirma que es historico y escribe un
motivo. El servidor vuelve a validar todas las IP/FR/EM y la ausencia de trabajo
fisico pendiente bajo una transaccion. El cierre cambia el estado principal y
deja auditoria; no genera bultos, cantidades recibidas, fechas de arribo ni
atenciones ficticias. Para una llegada adicional tras el cierre definitivo,
el administrador debe reabrir el expediente con los controles existentes.

No hay cierre masivo automatico ni modificaciones de bases productivas en este
PR. Estas reglas sustituyen las dudas previas sobre provisionales, feriados y
conciliacion; el horario por turnos queda para una decision posterior.

Los cambios se proponen por PR y solo se despliegan despues de aprobacion y merge,
por separado para manual y lector. Las pruebas usan datos ficticios.
