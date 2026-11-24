# Triton Tracking: consulta interna por OV y OC

Extensión del WMS QR en el mismo repositorio. No depende de Odoo ni del laboratorio local. La ruta es `/tracking`.

## Acceso

El administrador asigna el perfil **Consulta Tracking** a una cuenta personal desde la administración de usuarios existente. Ninguna cuenta existente recibe acceso automáticamente. El perfil es exclusivamente de consulta: no permite abrir operaciones, cuentas, usuarios ni modificar datos del WMS. Quien necesite conservar un perfil operativo debe usar una cuenta personal de consulta separada; no compartir credenciales.

El inicio de sesión, las claves temporales, el cambio obligatorio de contraseña, los bloqueos y la revocación de sesiones usan la política original. Solo funciona con `TRITON_AUTH_MODE=local`; no hay autenticación de demostración por cabeceras.

## Fuente y primer corte

El importador de Recepción conserva una proyección de seguimiento cuando recibe el mismo Excel de Importaciones. Incluye filas sin BL y referencias COT/PRE, fechas separadas y cantidades. No agrega una descarga de nube ni otro trabajador. La carga diaria pasa la fecha del corte; una carga directa sin fecha no inventa ese dato.

Después de instalar, hace falta un primer corte válido para poblar esa proyección. Si el archivo no cambió y el sincronizador lo omite por hash, el administrador puede utilizar una única actualización forzada existente. Antes de ese primer corte se informa la limitación; las OV conocidas pueden mostrar su detalle disponible sin inventar OC/BL. No se consulta Microsoft, DHL ni IA al buscar.

Un corte inválido, vacío o con hojas faltantes conserva la última proyección válida. Las filas que desaparecen no se declaran canceladas. Una búsqueda OV prefiere las referencias vigentes y evita duplicar una revisión PRE→OC. La falta de cobertura entre OV e Importaciones se avisa y no acredita una OV totalmente atendida.

## Qué muestra

- Búsqueda exacta por tipo OV/OC; compras para stock sin exigir OV. BL y repuestos relacionados dentro del resultado.
- Cantidades solicitadas, pendientes de origen, recibidas y estados parciales; hasta100 líneas por página, máximo2000 por documento. El exceso requiere revisión de Importaciones y no devuelve una muestra como si fuera todo.
- Fechas del origen: solicitud, pedido, factura, recojo, Callao, estimada/confirmada Triton y costeo. La confirmada tiene prioridad como previsión, no demuestra recepción física.
- Evidencia de recepción/ubicación y transferencia con vínculos documentales exactos. Un NP compartido o un cierre administrativo no certifica una atención completa.
- SLA existente por atención, en calendario del WMS. No inicia antes de una recepción real. Estado de la fuente y marcas de actualización separados del momento de consulta.
- OC registrada no equivale a OC aprobada: el Excel observado no contiene una aprobación explícita. No hay GPS, confirmación de proveedor inventada ni entrega final al cliente.

No se devuelven precios, márgenes, credenciales, correos privados ni payloads administrativos.

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
