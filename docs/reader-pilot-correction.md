# Correccion Administrativa De Recepciones De Prueba

Alcance: lector. No se modifica ni despliega el programa manual.

## Control En La BL

El administrador abre la BL y despliega **Mas informacion y controles de la BL**.
**Corregir pruebas de esta BL** aparece solo cuando hay recepciones pendientes
de corregir y todas pertenecen a camiones cancelados, archivados expresamente
como pruebas, sin manifiestos activos ni lotes de inventario posteriores.
Un nombre SCAN no acredita una prueba. Recepciones sin procedencia comprobada
necesitan investigacion; esta opcion no las elimina ni fuerza sus estados.

Resultados disponibles:

- **Pendiente de llegada**: anula el trabajo ficticio y libera la BL para una
  nueva llegada real, sin SLA fisico iniciado.
- **Historica atendida: cerrar BL**: exige FR/EM completas para todas las IP;
  registra el cierre documental confirmado, sin inventar bultos o unidades.

Ambos requieren motivo, escritura de la BL completa y confirmacion. Una huella
del expediente rechaza cambios concurrentes; la transaccion vuelve a comprobar
proveniencia, inventario y documentos antes de modificarlo. El cierre historico
no es un atajo para omitir etapas de una recepcion real.

## Conservacion Y Auditoria

No se borran BL, IP, FR, EM, recibos, atenciones ni escaneos. Los recibos quedan
en cero y las atenciones anuladas, fuera del contexto de trabajo predeterminado.
Las ubicaciones y llegadas de prueba retiradas, cantidades y estado anterior se
conservan en un snapshot privado de reception_history con actor, fecha y motivo.
No se modifica stock ni kardex; con lotes posteriores se bloquea la operacion.
Las atenciones anuladas permanecen consultables y no pueden reabrirse como
trabajo real. Una nueva llegada crea su propia atencion con el saldo real.

La instalacion del codigo no corrige datos automaticamente. Cada BL necesita
la accion expresa del administrador. El servidor se actualiza tras aprobar y
fusionar el PR; no antes.

## EM Y Excel: Comportamiento Actual

El servidor consulta los Excel configurados por intervalos y aplica cambios
documentales; no mueve las etapas fisicas de una BL en curso. Una pantalla
abierta no recibe actualizaciones en vivo: el dato se ve al volver a consultar.

La etapa EM permite registrar en el WMS el numero existente en SAP por FR/IP
y atencion parcial. No crea documentos SAP ni escribe de vuelta a SharePoint.
Los numeros se acumulan: una correccion de EM en el Excel puede conservar el
numero anterior en el detalle del WMS. No hay arbitraje bidireccional ni
reemplazo automatico seguro implementado.

Recomendacion para una futura integracion: registro operativo en WMS, cola
de escritura confirmada por FR/IP en Excel y conflictos visibles si la celda
cambio mientras se trabajaba. No sobrescribir todo el libro ni considerar que
una EM documental prueba una recepcion fisica. La escritura requiere verificar
los permisos delegados de Microsoft y el acceso al archivo; no se habilita en
este cambio.

Referencia oficial: https://learn.microsoft.com/en-us/graph/api/range-update?view=graph-rest-1.0

## Verificacion

Pruebas sinteticas de permisos, elegibilidad, confirmacion, concurrencia,
rollback, preservacion documental, nuevos arribos y estado historico. Fixture
local desechable y navegador en escritorio/movil; sin Excel empresarial, correo,
credenciales reales ni correcciones en la base productiva.
