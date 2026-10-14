# Contrato De Pantalla

Usar este formato breve en la descripcion del PR o documento del modulo para
un flujo nuevo o un cambio material. No crear un documento por cada boton.
Los puntos que no aplican se omiten con una razon; no son campos de la app.

| Decision | Contenido que debe quedar resuelto |
| --- | --- |
| Tarea y usuario | Que debe terminar el operador/admin y cual es el resultado observable. |
| Entidad y contexto | Camion, BL, atencion, NP u otra; IDs/filtros que deben preservarse. |
| Datos y autoridad | Endpoint/helper existente, que viene del servidor y que es borrador. |
| Contenido principal | Solo los datos necesarios; que queda en detalles por preferencia. |
| Accion principal | Una por tarea; cuando se habilita, que valida y como confirma guardado. |
| Acciones secundarias | Volver, consultar, imprimir o correccion; sin efectos ambiguos. |
| Permisos | Acceso/lectura/escritura, correccion administrativa y rechazo backend. |
| Celular / PC | Que se apila o redistribuye; posicion de accion final, teclado y lista/detalle. |
| Estados | Cargando, vacio, error, sin conexion, guardando, exito y sesion vencida. |
| Error y retorno | Conservacion de borrador, destino de foco y contexto al reintentar o volver. |
| Pruebas | Fixture, roles, viewports y criterio observable de aceptacion. |

## Ejemplo: Recibir Bultos

El asistente recibe codigos unicos en un camion activo. El servidor resuelve la
BL desde el cache DHL; si se ingresa por BL, el contexto se elige explicitamente.
La pantalla muestra codigo, BL, marca y recibidos/esperados. Registrar bulto es
la accion principal de lectura; Terminar llegada es la accion de la fase.

En celular, campo y resumen en una columna; la accion de fase queda fuera del
contenido desplazable sin tapar el foco. En PC se conserva la misma secuencia.
Revisar otra BL no cambia el destino de una lectura pendiente. Una relectura
mantiene el contador; error conserva el codigo. Solo el administrador reabre una
llegada guardada con motivo. Prueba: 8/10 a10/10, relectura sin aumento, cuatro
BL con marcas y retorno al mismo camion, incluyendo 320px y horizontal.
