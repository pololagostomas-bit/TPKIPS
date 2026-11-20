# Picking por corte y fotografía de guías

Solo WMS original con lector. El administrador conserva los controles existentes.
Esta cola ordena la consulta; no asigna, reserva, inicia picking ni entrega por sí misma.

## Cliente interno

La identificación usa la misma regla del indicador de productividad. La fecha y hora
proceden de creación OV en el Excel SAP. La fecha de contabilización y la hora de carga
no sustituyen esos datos cuando existe la creación original.

- Pendientes del corte: creación después del corte anterior y hasta las16:00 del último corte completado, inclusive.
- Rezagadas: pendientes de cortes anteriores. Permanecen separadas del corte prioritario.
- Revisar fecha/hora: registros sin una creación válida con precisión horaria. Recargar o corregir la fuente; no inventar un horario.
- Las creaciones posteriores al corte aparecen cuando corresponda el siguiente corte.
- Los cierres SAP y las entregas completas no cuentan como pendientes. Un saldo parcial real puede continuar pendiente.

Calendario inicial: lunes a viernes, como el indicador de productividad.
El corte del viernes tiene entrega objetivo el lunes de08:00 a10:00.
Durante el lunes, antes de16:00 continúa el corte del viernes; desde16:00 se prioriza el corte del lunes,
para entregar el martes de08:00 a10:00. Guiado y entrega siguen habilitados fuera de ese horario.

## Cliente regular

La lista pide buscar la OV. Después se abre su atención mediante las confirmaciones,
responsables y permisos existentes. No se asigna una prioridad por corte a estos clientes.
Importar un documento no equivale a iniciar su trabajo físico. Las STS mantienen su cola separada.

## Contrato de pantalla

| Decisión | Comportamiento |
| --- | --- |
| Usuario y datos | Administrador, picker y guiador consultan únicamente el alcance autorizado por el servidor. |
| Navegación | Cliente interno/regular, corte/rezagadas y páginas de seis OV; las páginas cubren todos los resultados. |
| Densidad | OV, cliente, creación y estado. La cola ligera no calcula stock ni agrega reportes para cada fila. |
| Filtros | Corte/rezagadas sustituyen los filtros generales de fecha/origen en esta vista. El administrador conserva la vista general existente con Todos los clientes. |
| Permisos | La consulta no modifica etapas. Continúan las asignaciones y correcciones autorizadas con auditoría. |
| Celular/PC | Misma lógica, controles nativos y botones de al menos44px. Lista y detalle conservan el shell. |
| Refresco/error | Actualización cada minuto solo con la cola visible y sin expediente abierto; error y Reintentar no registran operaciones. |

## Foto de guía

Tomar foto con cámara abre la vista de captura en navegador HTTPS o localhost.
Adjuntar archivo continúa disponible si el equipo no tiene cámara o deniega el permiso.
La captura genera una imagen JPEG, con lado mayor de hasta2048px. El formulario muestra
la vista previa y conserva el límite de8MB. Guardar exige confirmar ambas firmas y los
permisos existentes. No se guarda automáticamente al capturar.

Cancelar conserva el archivo anterior. Cambiar de expediente, ocultar la pestaña o salir
libera la cámara. El mismo componente sirve para guías OV y recepción de STS en sucursal.
