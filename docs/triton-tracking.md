# Triton Tracking: consulta interna por OV y OC

Extensión del WMS QR en el mismo repositorio. No depende de Odoo ni del laboratorio local. La ruta es `/tracking`.

## Acceso

El administrador asigna uno de dos perfiles a una cuenta personal desde **Usuarios y accesos**:

- **Tracking · Comercial** busca por OV u OC y ve estado general y conteos de recepción. El perfil anterior `CONSULTA_TRACKING` conserva acceso con esta vista reducida.
- **Tracking · Analista de Repuestos** busca por OV, OC, IP (Pedido Triton) o BL (guía), y ve repuestos, fechas, referencias, aprobación según formato y evidencia de almacén.

Ambos perfiles son de solo consulta. Quien necesite conservar un perfil operativo debe usar una cuenta personal de consulta separada.

El inicio de sesión, las claves temporales, el cambio obligatorio de contraseña, los bloqueos y la revocación de sesiones usan la política original. Solo funciona con `TRITON_AUTH_MODE=local`; no hay autenticación de demostración por cabeceras.

## Fuente y primer corte

El importador de Recepción conserva una proyección de seguimiento cuando recibe el mismo Excel de Importaciones. Incluye filas sin BL y referencias COT/PRE, fechas separadas y cantidades. No agrega una descarga de nube ni otro trabajador. La carga diaria pasa la fecha del corte; una carga directa sin fecha no inventa ese dato.

Después de instalar, hace falta un primer corte válido para poblar esa proyección. Si el archivo no cambió y el sincronizador lo omite por hash, el administrador puede utilizar una única actualización forzada existente. Antes de ese primer corte se informa la limitación; las OV conocidas pueden mostrar su detalle disponible sin inventar OC/BL. No se consulta Microsoft, DHL ni IA al buscar.

Un corte inválido, vacío o con hojas faltantes conserva la última proyección válida. Las filas que desaparecen no se declaran canceladas. Una búsqueda OV prefiere las referencias vigentes y evita duplicar una revisión PRE→OC. La falta de cobertura entre OV e Importaciones se avisa y no acredita una OV totalmente atendida.

## Qué muestra

- Búsqueda por referencia exacta. Las compras para stock no requieren OV. Los analistas pueden buscar el valor completo de la IP o de la BL.
- Cantidades solicitadas, pendientes de origen, recibidas y estados parciales; hasta100 líneas por página, máximo2000 por documento. El exceso requiere revisión de Importaciones y no devuelve una muestra como si fuera todo.
- Fechas del origen: solicitud, pedido, factura, recojo, Callao, estimada/confirmada Triton y costeo. La confirmada tiene prioridad como previsión, no demuestra recepción física.
- Evidencia de recepción/ubicación y transferencia con vínculos documentales exactos. Un NP compartido o un cierre administrativo no certifica una atención completa.
- SLA existente por atención, en calendario del WMS. No inicia antes de una recepción real. Estado de la fuente y marcas de actualización separados del momento de consulta.
- Criterio de Alertas: `PRE` o más de cinco dígitos totales indica preliminar por regularizar. Exactamente cinco dígitos sin `PRE` muestra «Aprobada según formato». Esta clasificación no verifica SAP.

No se devuelven precios, márgenes, credenciales, correos privados ni payloads administrativos.

## Estado de una OV con códigos numéricos formateados

El corte de OV puede perder ceros iniciales de un NP numérico. Tracking reconoce esa variante solo dentro de la misma OV, si existe un único código de Importaciones en el catálogo BI vigente, con igual descripción y cantidad total. Si ambas variantes existen como códigos BI, hay más candidatos o la OV incluye ambas, conserva las líneas y la advertencia de cobertura. No cambia los códigos guardados ni las reglas de identidad de Inventario o picking.

«Ingresado y costeado» exige recepción completa y cantidades verificadas en atenciones cerradas con costeo vigente. Una fecha del Excel de Importaciones por sí sola no basta. Se aplica también a una OC y respeta entregas parciales, anulaciones y cierres administrativos. El check manual de transferencia conserva su significado independiente. Costeo no certifica stock libre, una reserva, una transferencia SAP o entrega al cliente; esos hechos requieren su evidencia específica.

## Túnel independiente: preparación, sin activación

`infrastructure/tracking-gateway.conf` es una plantilla Nginx para Linux. Nginx ya se usa en esta infraestructura, pero esta plantilla no instala ni inicia servicios.

1. Fusionar/instalar primero la versión revisada mediante el procedimiento habitual y con respaldo. No montar el checkout sobre producción para probar.
2. Ejecutar el gateway separado en la red del host Linux o con el upstream adaptado explícitamente al backend. La plantilla presupone acceso al WMS en127.0.0.1:8086 y escucha solo en127.0.0.1:18773. Si se usa un contenedor, su propio localhost no es el host: necesita red host Linux o una dirección/nombre interno verificado.
3. Sustituir `tracking.example.invalid` por el hostname exacto autorizado. Un hostname distinto y las rutas fuera de `/tracking` se rechazan. No enviar el túnel directamente al8086: eso publicaría las demás rutas del WMS.
4. Apuntar un proceso de túnel propio al18773. Publicar su URL con sufijo `/tracking`. No reutilizar ni reiniciar el túnel QR.
5. Para HTTPS público usar `TRITON_COOKIE_SECURE=1`. La comprobación de origen sigue esa configuración del servidor y no confía en X-Forwarded-Proto del cliente. Para pruebas HTTP locales aisladas, usar0.
6. Validar que login y búsqueda funcionan y `/api/users`, `/api/orders`, `/reception`, traversal y hosts ajenos quedan bloqueados. No activar el acceso sin esa comprobación.

Un túnel temporal puede cambiar de URL y no garantiza disponibilidad. El despliegue, la URL real y el proceso de supervisión quedan fuera del PR; no se activan automáticamente. No hay rutas nuevas de escritura de negocio.

## Verificación

Datos de prueba exclusivamente sintéticos. `tests/test_tracking.py` cubre vínculos exactos, fechas, parciales, cortes y límites. `tests/test_tracking_portal.py` cubre sesiones, perfil, cabeceras falsas, claves temporales, CSRF, revocación, modo demo y terminación TLS.

Fixture de navegador aislada: `python tests/support_tracking_server.py --synthetic --port 50737`. Usa SQLite temporal y no accede a fuentes corporativas. No ejecutar una fixture apuntando a una base operativa.
