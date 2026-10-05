# Recepción simplificada — Con Camión v.2

Actualización local: 2 de octubre de 2026. No modifica Con Camión v.1 ni publica en GitHub.

## Flujo

1. En Tránsito, crear **Nuevo camión** para recibir mediante escáner.
2. Leer o escribir la BL y pulsar Enter. Queda una sola BL activa.
3. Leer sucesivamente el código único de cada paquete. Cada lectura se guarda en el servidor y actualiza el contador sin recargar el formulario. Las lecturas rápidas se procesan en orden.
4. **Cambiar BL** permite pasar a otra BL sin perder los paquetes anteriores. No se puede cambiar el contexto ni terminar la llegada mientras se guardan lecturas.
5. Un código ya registrado no suma. Si pertenece a otra BL/guía registrada, se identifica su origen y se rechaza su reasignación. Un código nunca visto no permite deducir su BL: el operario debe seleccionar la BL correcta.
6. **Terminar llegada** abre las ubicaciones temporales por BL, con las cantidades escaneadas prellenadas. Se conserva la distribución entre varias ubicaciones y su conciliación.
7. **Guardar y finalizar camión** permite continuar individualmente por BL. No cierra automáticamente su conteo, EM o ubicación definitiva.
8. En **Inicio de conteo**, escanear el NP y escribir manualmente su cantidad entera. Solo se guarda la línea elegida y su atención. Si el NP aparece en varias líneas, seleccionar la OV/IP correspondiente.
9. El listado completo y su guardado global siguen disponibles, cerrados por defecto. EM, ubicación definitiva, validación y transferencia conservan sus controles anteriores.

## Interfaz

- Una BL activa, un campo para paquetes y un contador; el detalle del camión se consulta bajo demanda.
- Conteo por NP como tarea principal, sin stock visible permanentemente.
- Etapas previas, atenciones, referencias y controles administrativos en desplegables. Los permisos no cambian.
- Avance al final de la tarea.
- Celular: marca y módulo en un encabezado compacto; nombre/rol y franja de cortes fuera de la tarea. Mi perfil y navegación inferior disponibles.
- Se respeta la preferencia de ayudas informativas; los errores operativos necesarios siguen visibles.

## Referencias de diseño

Se adaptan patrones, no se reproduce un producto completo:

- [Oracle WMS — Mobile Receive Single SKU](https://docs.oracle.com/en/cloud/saas/warehouse-management/26b/owmol/rf-receive-single-sku.html): conservar el contexto y reducir reingresos entre lecturas.
- [Microsoft Dynamics 365 — Warehouse app detours](https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/warehouse-app-detours): separar consultas auxiliares sin perder la tarea principal.

## Verificación

207 pruebas automáticas aprobadas, incluyendo cola secuencial, duplicados, fallos de guardado, cantidades manuales, contexto de atención y rutas HTTP de los nuevos archivos.

Prueba por navegador con base temporal separada: crear camión, dos BL, tres paquetes, rechazo de duplicado cruzado, zonas TEMP-A/TEMP-B, cierre de camión e inicio de conteo.

NP repetido en dos OVs: elección explícita, decimal rechazado, segunda línea guardada con 1 y primera preservada con 8; persistencia comprobada tras recargar. Vista móvil revisada sin desbordamiento horizontal del documento.

La entrada se comprobó con teclado/Enter, equivalente a la entrada de un lector HID. Falta validar el dispositivo físico y etiquetas reales. Se conserva la cámara html5-qrcode existente; en celular requiere HTTPS y permiso de cámara. No se habilitó acceso nuevo a internet ni se cambiaron credenciales.

`tests/support_scan_server.py` crea una base nueva y sirve solo en 127.0.0.1:9012 para QA; no utilizar sus datos como base operativa.
