# Aprobacion antes de desplegar

Regla reiterada por el propietario el 2026-10-09, para ambos WMS:

1. Preparar codigo y pruebas en una rama distinta de `main`.
2. Subir esa rama y abrir un pull request dirigido a `main`.
3. Esperar revision y aprobacion/fusion expresa del propietario.
4. Desplegar la revision fusionada mediante el proceso revisado del servidor.

Un push, un pedido de implementar o la ejecucion correcta de pruebas no
autorizan por si solos un despliegue. No fusionar ni habilitar auto-merge por
cuenta del agente. Una excepcion debe autorizarse expresamente para ese cambio.
Esta norma no implica que GitHub tenga protecciones de rama ya verificadas.

Los enlaces privados, contrasenas, tokens OAuth y bases operativas permanecen
fuera de Git. La configuracion privada requiere autorizacion del propietario,
pero no se publica en un PR con secretos.

## Regularizacion Microsoft/Excel

El conector fue instalado directamente en Docker antes de crear su PR. Eso
omitia el flujo acordado. Este PR versiona el codigo para revision posterior;
no convierte el despliegue anterior en uno aprobado. No se reinicia el servidor
ni se cambian usuarios, claves, bases, enlaces publicos o autorizacion Microsoft
al publicar esta rama.

La rama contiene los modulos comunes, panel, pruebas y guards documentales.
Incluye la correccion solicitada durante la regularizacion: el boton
`Conectar con Microsoft` debe mostrarse dentro de `Cargar cortes diarios`,
antes de sincronizar, y solo para el administrador; no como boton suelto en
la barra principal. Este ajuste aun requiere aprobacion antes de desplegarse.
Tambien incluye la politica de cambio obligatorio de clave ya montada en los
pilotos, necesaria para proteger el nuevo panel. No incorpora los ajustes
locales separados de identity, notifications, WSGI o recuperacion por correo.
La recuperacion es opcional en la politica; publicar este PR no configura ni
certifica envios de correo.

La publicacion elimina los correos internos del archivo de ejemplo y los dos
destinatarios predeterminados de Recepcion. En instalaciones nuevas, configurar
privadamente `TRITON_IMPORTACIONES_EMAILS` y `TRITON_CONTABILIDAD_EMAILS` antes de
habilitar notificaciones operativas; sin destinatario no se encola un correo.
No se altera la configuracion privada ni se habilita correo en este servidor.
Se retiran tambien constantes de identificadores Microsoft que ya no se usaban;
la cuenta/aplicacion sigue configurandose solo desde el entorno/panel privado.

## Dos variantes

La imagen completa del lector se construye con `infrastructure/Dockerfile`.
La variante manual conserva su app y base independientes: el paquete
`infrastructure/cloud-overlay/Dockerfile` aplica solo los modulos y guards
compartidos sobre su imagen base aprobada. No copiar `backend/app.py` ni toda
la implementacion del lector sobre la manual. El paquete rechaza bases con
puntos de importacion/barra cambiados, y es idempotente en bases ya parcheadas.

Solo despues de aprobacion/fusion, una construccion revisada usa:

```sh
docker build --build-arg BASE_IMAGE=<imagen-base-aprobada> \
  -f infrastructure/cloud-overlay/Dockerfile -t <imagen-candidata> .
```

Este comando construye, no despliega. Elegir por separado la base y el tag de
cada variante. Probar la imagen aislada antes de modificar Compose. El agente
existente actualiza el lector; este PR no agrega despliegue automatico manual.

`infrastructure/docker-compose.microsoft.yml` documenta las variables y el
volumen OAuth compartido externo existente. Si se instala en un host nuevo,
crear y proteger previamente ese volumen para UID/GID 10001 (directorio 0700).
Los Compose fijos revisados de esta laptop ya poseen esa configuracion: no
reemplazarlos ni aplicar otra vez el override por publicar el PR.

## Limites

Microsoft aun necesita autorizacion real del administrador y permisos de TI.
OV permanece manual. El stock de Power BI sigue pendiente; su enlace no se
trata como Excel y el filtro almacen 01 no se declara validado. Las pruebas
de OAuth/Excel usan datos sinteticos, no archivos corporativos.
