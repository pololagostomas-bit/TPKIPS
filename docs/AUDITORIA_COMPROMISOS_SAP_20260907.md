# Auditoría de compromisos de importación y SAP Business One

Fecha: 7 de septiembre de 2026. Alcance: código y SQLite locales del piloto. No se inspeccionó la configuración del servidor Linux ni se conectó a SAP. No se modificaron reglas operativas, inventario ni la base de trabajo. La mejora visual autorizada posteriormente es independiente de este diagnóstico.

## Conclusión

**El WMS tiene protección operativa de stock dentro de sus propios flujos, pero no garantiza que un repuesto destinado a una OV no se entregue a otro cliente en SAP.** Hay controles programados de reserva, consumo y saldo, sujetos a la integridad y antigüedad de los Excel. No hay una validación SAP integrada que cierre el acceso por otros canales.

No hace falta un almacén por OV ni introducir lotes/series para controlar cantidades comprometidas. Sí hace falta una asignación explícita por línea de OV, con cantidades y procedencia, y una validación aplicada también donde SAP registra la salida.

## Evidencia de la base local

Lectura mediante SQLite `mode=ro` y `PRAGMA query_only=ON`; `quick_check` devolvió `ok`.

| Tabla | Registros |
|---|---:|
| orders | 957 |
| order_lines | 6,325 |
| order_importation_refs | 7,855 |
| reception_shipments | 683 |
| reception_lines | 9,546 |
| reception_accounting_refs | 631 |
| inventory_stock | 2,172 |
| stock_allocations / stock_movements | 0 / 0 |

Las 913 atenciones están en PENDIENTE (712) o CERRADO SAP (201). Por tanto, esta base no contiene evidencia de ejecución de reservas/consumos en una jornada real. Esto no significa que no exista esa funcionalidad en código.

De las referencias de importación, 1,605 enlazan con 373 OVs presentes en `orders`. Las restantes pueden ser históricas o estar fuera del corte; no se puede considerarlas automáticamente pendientes ni terminadas.

Ejemplo real: OV 152617 → OC 81392 → IP260528 → BL 8468722054; la BL figura CERRADO con FR 296178 y EM 39853. Sus cuatro referencias de NP existen, pero la OV no está en `orders`. El cálculo de compromiso del NP 593524501 devuelve cero porque no encuentra cantidad pendiente de esa OV. Es una brecha si la OV quedó fuera del Excel por un filtro; podría ser correcto si efectivamente ya terminó en SAP. No se verificó su situación en SAP.

## Cobertura solicitada

| Requisito | Diagnóstico |
|---|---|
| 1. OV → SC → OC → EM | Parcial. Existe OV–NP–OC–IP–BL, y referencias FR/EM importadas. No se encontró el recorrido documental completo de SC ni claves SAP por cada enlace. |
| 2. Artículo, recibido, OV y cliente | Parcial. Recepción registra NP, OV y cantidades; el cliente se obtiene de la OV de despacho. Falta un enlace inequívoco de cada cantidad recibida con la línea SAP y su destino. |
| 3. Asignado, recibido, entregado y pendiente | Parcial. Existen campos repartidos entre recepción, atenciones y reservas. No forman todavía un registro único de asignación que concilie compra, recepción y entrega SAP. |
| 4. Libre y comprometido | Sí, cálculo operativo sobre el corte Excel, no disponibilidad SAP en tiempo real. |
| 5. Alertar uso de stock ajeno | Parcial. El saldo descuenta compromisos reconocidos para otras OVs; datos omitidos o mal relacionados pueden excluir una retención. |
| 6. Bloquear o exigir autorización | Bloqueos locales por saldo/tipo de atención. No se encontró autorización formal de transferencia de compromiso entre OVs ni bloqueo general en SAP. |
| 7. Reasignación entre OVs | No equivalente a lo requerido. Cambiar picker o retroceder una atención no es transferir una asignación de mercadería de una OV a otra. |
| 8. Evitar entrega directa en SAP | No cubierto por el código revisado. No se verificaron permisos o validaciones ya existentes en el SAP de la empresa. |
| 9. Entregas parciales | Cubiertas operativamente por atenciones y cantidades; falta enlazar cada salida con documento/línea de entrega SAP y sus cancelaciones/devoluciones. |
| 10. Consolidar OVs en OC | Las referencias conservan OV, OC y NP, pero falta una relación cuantificada muchos-a-muchos por línea documental para demostrar cómo se reparte una misma línea de compra. |

## Código que respalda el diagnóstico

- `backend/app.py:143`: referencias de importación; `:199`, `:212`: atenciones y cantidades; `:251`, `:265`, `:286`: saldo, reservas y movimientos.
- `backend/app.py:545`: identifica filas mediante número de línea, NP normalizado, almacén, condición pendiente y contador; no equivale a una clave documental SAP estable de extremo a extremo.
- `backend/app.py:1666`: cambio de estado con `BEGIN IMMEDIATE`; `:1944`: reserva y rechazo de atención completa sin saldo; `:2098`: consumo al finalizar picking y comprobación contra la reserva.
- `backend/app.py:1794`, `:1853`, `:2286`: retroceso, reinicio y cambio de responsable. No constituyen aprobación de reasignación comercial entre OVs.
- `backend/services/daily_operations.py:131`: compromisos derivados de referencias y pendiente de las OVs; `:179`: saldo operativo; `:215`: conciliación declarada por el administrador.
- `backend/services/reception.py:46`, `:81`, `:130`: BL, líneas y referencias contables. El cierre basado en FR/EM es una regla operativa/importada, no una consulta de transferencia efectiva IMP→01.
- `backend/services/sap_service_layer.py`: cliente básico con login, fetch y logout. La búsqueda de referencias en el backend no mostró su uso en el flujo operativo. Tener esta clase no demuestra integración activa.

## Brechas y riesgos principales

1. **Salida por fuera del WMS:** sin control SAP, una entrega directa puede ignorar las reservas de SQLite.
2. **OV omitida en el Excel:** un compromiso puede calcularse en cero por ausencia de pendiente, sin prueba explícita de cierre. Debe distinguirse “no incluida” de “cerrada”.
3. **EM no es liberación de IMP:** considerar SOLICITUD TRANSFERENCIA o CERRADO como disponibilidad no confirma que Contabilidad haya transferido al almacén 01. La existencia del corte ayuda, pero no demuestra la procedencia de esas unidades.
4. **Granularidad de recepción:** la liberación del compromiso toma cantidades de referencias y estado de la BL, no una aplicación exacta de cantidades recibidas por línea EM hacia cada OV. Riesgo con faltantes y consolidaciones.
5. **Stock disponible ambiguo:** hay que confirmar si la columna representa existencia física o disponibilidad ya neta de compromisos SAP. Restar de nuevo reservas puede duplicar descuentos; asumir existencia física cuando incluye compras futuras también sería incorrecto.
6. **NP y filas:** la normalización elimina puntuación; se encontraron representaciones con/sin puntos para la misma clave. Pueden ser equivalencias válidas, pero deben validarse contra el maestro SAP. Hay 24 grupos OV–NP–almacén con más de una línea pendiente: no basta unir solo por NP.
7. **Cortes y correcciones:** la conciliación depende de una confirmación manual de qué entregas ya incluye SAP. Retroceder trabajo local no demuestra que SAP haya anulado o devuelto la mercadería. Debe evitarse reponer saldo disponible sin esa evidencia.

## Flujo recomendado

1. Importar OV/líneas y stock con fecha de corte; distinguir faltantes de datos de cierres confirmados.
2. Importar OC–IP–BL–NP–OV. Para la etapa 1, SC puede quedar como referencia opcional: no inventar relaciones ausentes.
3. Crear una asignación cuantificada por línea de OV y origen de compra. Si una OC abastece dos OVs, registrar dos aplicaciones de cantidad, no dos copias del total.
4. Registrar arribos y revisión de BL. Esto no suma stock de picking en la etapa 1.
5. Vincular FR/EM y sus líneas; separar cantidad esperada, recibida y habilitada. Mientras no exista integración, mostrar la evidencia documental y las verificaciones manuales.
6. Confirmar liberación/transferencia IMP→01 antes de habilitar cantidades comprometidas para salida. “Correo enviado” no equivale a transferencia ejecutada.
7. Reservar picking contra stock libre o asignación propia. Aplicar transacción atómica y cantidades en unidad de inventario.
8. Registrar parcial y consumo con referencia a la entrega SAP. No confundir picking finalizado con salida contable definitiva.
9. Reasignar solo mediante solicitud con OV origen/destino, cantidad, motivo, aprobador y fecha; conservar el historial sin borrar la asignación anterior.
10. Conciliar cada corte y reportar diferencias. En integración, validar también las operaciones directas en SAP.

## Tablas/campos a incorporar o fortalecer

Son propuestas; no se crearon en esta revisión. Reutilizar las tablas existentes cuando corresponda.

| Entidad | Campos mínimos |
|---|---|
| Documento/línea SAP | Sociedad, tipo de objeto, DocEntry, DocNum visible, LineNum, ItemCode exacto, CardCode, cantidad, unidad y factor de conversión, almacén, estado y fecha de actualización. |
| Relación documental por línea | Documento/línea origen y destino, tipo de relación, cantidad aplicada; SC opcional, OC, FR, EM y entrega según los documentos reales. |
| Embarque | ID, BL/AWB, vía normalizada, IP, fechas previstas/reales; relación de sus líneas con las OC. |
| Asignación comercial | ID, OV/línea, cliente, OC/línea, BL/IP, NP, cantidad asignada, recibida, liberada, reservada para picking, entregada, cancelada y pendiente; estado y versión. |
| Aplicación de recepción | Asignación, EM/línea, cantidad aplicada. Permite repartir una EM entre destinos sin duplicarla. |
| Aplicación de salida | Asignación, atención, entrega SAP/línea, cantidad, fecha, usuario, reversión; clave de idempotencia. |
| Reasignación y aprobación | Asignación origen/destino, cantidad, motivo, solicitante, aprobador, decisión y fechas. |
| Corte y movimientos | Fuente, fecha real, huella de archivo, usuario; movimientos inmutables y referencias a reversión. |

La cantidad comprada o asignada todavía por llegar no es existencia física. Separar compromiso futuro de stock físico ya recibido y comprometido. Sobre una misma base y momento: stock físico habilitado = libre + retenido para OVs + otras retenciones, sin contar dos veces una reserva de picking contenida dentro de una asignación.

## Elección de herramientas SAP

| Alternativa | Recomendación |
|---|---|
| Almacén lógico comprometido | Opcional para segregación operativa. No identifica por sí solo a qué OV pertenece cada cantidad. Mantener IMP y 01; no crear almacenes por OV. |
| Ubicaciones/bin | Útiles para localización física en etapa 3; no sustituyen la asignación comercial. Activarlos tiene impacto en todos los ingresos/salidas del almacén. |
| Pick list | Útil para ejecutar y documentar picking por línea. No asumir que sola impide todas las otras vías de salida. |
| Campos de usuario | Usarlos para IDs de asignación y referencias estructuradas, no para meter múltiples destinos en comentarios. |
| Tabla de asignación por OV | Necesaria para el control propuesto, con reparto por línea y cantidades. |
| Service Layer / SDK | Canales para leer y registrar documentos mediante interfaces SAP soportadas. No son por sí solos una regla de exclusividad. |
| Add-on | Puede facilitar trabajo dentro del cliente SAP, pero un bloqueo solo visual no cubre otros canales. |
| SBO_SP_TransactionNotification | Candidato para rechazar transacciones incompatibles en SAP HANA. Diseñar con el partner/TI, probar concurrencia y mantener disponibles para SAP las asignaciones autorizadas. No depender de una consulta HTTP a SQLite durante cada transacción. |
| SAP como fuente principal | Sí para documentos, maestros, stock y salidas. El WMS mantiene tiempos operativos y trazabilidad complementaria. |

SAP señala expresamente que el asistente de aprovisionamiento permite consolidar OVs en OC, pero no garantiza el cumplimiento de la OV mediante una reserva de almacén: [Procurement Confirmation Wizard](https://help.sap.com/docs/PRODUCT_ID/68a2e87fb29941b5bf959a184d9c6727/95adcf102d2e486797b85c6123775f43.html?locale=en-US&state=PRODUCTION&version=9.3).

Referencias técnicas: [UDF en Service Layer](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/cc76b716c1ef484183f116652fa5852b.html?version=10.0), [tablas de usuario](https://help.sap.com/docs/SAP_BUSINESS_ONE/f110a154dd0f4c20bf7f3ebca9eeb794/39b128e787414a4e8323e55f5f4d1ac1.html), [bin en picking](https://help.sap.com/docs/SAP_BUSINESS_ONE/68a2e87fb29941b5bf959a184d9c6727/05c2cf5e2c564c33aed9fb613c72e492.html), [validación TransactionNotification en HANA, SAP](https://community.sap.com/t5/enterprise-resource-planning-blog-posts-by-sap/implementing-sbo-sp-transaction-notification-of-sap-business-one-version/ba-p/13253901). Confirmar compatibilidad con la versión instalada.

## Validaciones y pruebas de aceptación

| Caso | Resultado exigido |
|---|---|
| 10 unidades habilitadas, todas para OV A; OV B pide 5 | Libre para B = 0; rechazo sin aprobación, tanto WMS como SAP. |
| 10 para A y 5 libres | B puede usar hasta 5, sin consumir la asignación de A. |
| OC de 15 repartida A=10/B=5 | Aplicaciones suman 15, nunca 30 por repetir la OC. |
| Una OV tiene dos líneas del mismo NP | Reservas, parciales e historial permanecen ligados a su línea correcta. |
| Llegan 6 de 10 | No habilitar 10 por haber marcado la BL como arribada; respetar además la regla operativa de espera hasta completarla. |
| EM en IMP sin transferencia a 01 | No habilitar esas unidades como despachables desde 01. |
| OV desaparece del nuevo Excel sin cierre explícito | Mantener/poner en revisión su compromiso; no liberarlo silenciosamente. |
| Entregar 4 de 10 | Quedan 6 de compromiso; repetir la petición no duplica consumo. |
| Dos usuarios toman el último saldo | Solo la cantidad disponible se reserva; no sobrevender por concurrencia. |
| Reasignación A→B | Exigir aprobador autorizado; conservar motivo y cantidades antes/después. |
| Cancelación/devolución SAP | Aplicar reversión una vez y con referencia al documento real. |
| Reimportar mismo corte o corte viejo | No duplicar ni reponer stock; rechazar retroceso no autorizado. |
| Entrega directa, factura con movimiento, salida o traslado en SAP | Aplicar la regla donde corresponda al movimiento, no solo en la pantalla de entrega. |
| Cambio de NP por reemplazo / unidad de medida | Validar equivalencia autorizada y conversión; no deducirla de texto parecido. |

Existen pruebas locales en `tests/test_global_stock.py` y `tests/test_daily_operations.py` sobre saldo compartido, compromisos arribados, parciales, cortes y persistencia. Se inspeccionó su código; no se ejecutaron contra la base de trabajo ni se realizaron pruebas transaccionales en SAP. La verificación de interfaz posterior utilizó datos ficticios separados.

## Datos que debe confirmar TI/SAP antes de implementar la siguiente fase

- Qué objeto SAP llaman EM: recepción de compra u otra entrada de inventario; y qué tipo de factura de reserva interviene.
- Definición exacta de StockDisponible en el query y claves de documento/línea exportables.
- Cómo recuperan la relación de líneas OV–OC cuando consolidan; no asumir que el comentario conserva cantidades.
- Dónde queda registrada la transferencia IMP→01 y su confirmación.
- Permisos de entrega directa y procedimiento de validación existente, si lo hay.

**Prioridad:** cerrar primero las brechas OV ausente, asignación cuantificada y liberación IMP→01. Después integrar la validación en SAP. Cambiar la interfaz, usar APK o añadir un dominio no resuelve por sí mismo la exclusividad del stock.
