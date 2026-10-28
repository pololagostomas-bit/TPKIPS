# Seguimiento de BL para Repuestos

Vista de consulta adaptable a celular y PC: una BL por registro, camiones con llegada real, estado sencillo y fechas de llegada, inicio de trabajo, EM, costeo y disponibilidad. Búsqueda por BL/camión, filtros de estado/fecha/transporte y contadores calculados sobre todo el resultado filtrado antes de paginar. Por defecto muestra BL con llegada física; los históricos sin evidencia física y los planes de camión no se presentan como llegados. Las entregas parciales conservan su detalle y sus camiones, sin cerrar pendientes de otra entrega.

## Estados

| Estado | Evidencia |
| --- | --- |
| Zona de recepción | Llegada positiva registrada; conteo aún sin iniciar. |
| Trabajo en almacén | Conteo, EM, ubicación o validación en curso; también una BL con saldo físico/NP pendiente. |
| Costeo | Entrega en paso5, pendiente de fecha de costeo del Excel. |
| Disponible | Trabajo físico finalizado y entrega(s) costeada(s), sin atención/saldo pendiente. |

Fechas ausentes se muestran como «—»; no se inventan a partir de la fecha de importación. La fecha EM documental se distingue del paso de etiquetas. En una BL con varias fechas/EM se conserva el detalle, y el resumen usa la última fecha completa del hito. Estado y texto acompañan los colores; sin leyendas operativas largas.

## Regla confirmada por el propietario

FECHA DE COSTEO viene automáticamente del Excel de Facturas. Cuando está cubierta la documentación de una atención en SOLICITUD TRANSFERENCIA, se cierra automáticamente el paso5 de ESA atención con la fecha de costeo. No se escribe en Excel, no se inventa una transferencia ejecutada en SAP ni se marca su check por este hecho. Se conserva el historial de cierre y la fecha documental separada de la hora de sincronización.

No cerrar por una fecha agregada de otra IP: cada IP recibida de la atención debe tener referencia FR/EM y fecha de costeo válida, no futura ni anterior a la llegada. Si una IP aparece en varias entregas, se necesita EM asociada inequívocamente a esa atención. Una referencia ambigua, falta de FR/EM, conflicto o fecha incompleta mantiene Costeo. Los pasos físicos anteriores nunca se saltan. La sincronización no reabre automáticamente cerrados ni deshace lecturas/ubicaciones.

Si el Excel corrige la fecha de costeo después del cierre, se actualiza la fecha informativa y se audita sin cambiar la hora del cierre. Si la fecha desaparece o deja de ser válida, el seguimiento vuelve a «Costeo», conservando el cierre e historial operativo; solo vuelve a «Disponible» cuando la fuente está completa otra vez. Una fecha anterior a la EM conocida tampoco confirma costeo.

## Permisos y pantalla

Un rol de consulta de Repuestos permite únicamente este seguimiento y su cuenta/cambio de clave/salida. El administrador asigna ese rol mediante la administración de usuarios existente; no se crean cuentas ni contraseñas por esta entrega. Las APIs operativas continúan rechazando al rol de consulta. Admin también puede consultar la pantalla y conserva sus funciones habituales.

En PC, tabla compacta con BL, estado, camiones y fechas; en celular registros apilados que preservan las asociaciones. Filtros persistentes durante paginación, carga/error/vacío visibles, búsqueda con espera breve y protección contra respuestas obsoletas. Solo datos necesarios para seguimiento; sin controles de escaneo, edición de cantidades ni correos automáticos nuevos.

## Entrega

Código y pruebas en un PR nuevo del lector; no modificar la versión manual ni instalar en producción antes de aprobación/fusión. Probar cierres parciales, datos contables ajenos, fechas inválidas, repetición idempotente, roles, filtros antes de paginación y navegador320/393/1366px.
