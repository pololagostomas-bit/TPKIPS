# Mantenimiento de seguridad del WMS con lector

## Cambios de esta versión

Se conserva Python3.12 y se aplica3.12.16, incluida la protección de certificados
eMudhra y Expat2.9.0. La imagen Python y cloudflared se fijan por versión y digest;
no se obtiene un `latest` diferente en cada instalación.

MSAL1.39.0 permite cryptography50.0.2; el MSAL anterior limitaba cryptography<46.
Se actualizan juntos, además de requests2.34.2, certifi2026.10.23 y pip26.2.2.
Openpyxl3.1.5 y waitress3.0.2 se conservan. Defusedxml0.7.1 protege el XML que lee
openpyxl; no desactivar `OPENPYXL_DEFUSEDXML` en el servidor.

El lector común `safe_excel.load_workbook` limita el archivo comprimido a50MiB,
el total declarado descomprimido a512MiB, cada entrada a128MiB y10000entradas.
Rechaza ZIP inválido o cifrado y conserva las opciones de fórmulas/sololectura.
El maestro de ubicaciones mantiene además sus límites más estrictos. El rechazo
de una importación no elimina cortes válidos ni avances de recepción.

No cambian cuentas, permisos, configuración privada, datos ni formatos de
Microsoft. El caché existente se conserva. La actualización no implica volver
a conectar Excel/Mail.Send/Power BI por defecto.

## Dependencias reproducibles

- `requirements.in` declara las versiones directas y las restricciones de
  seguridad. `requirements.txt` es el lock generado en Linux/Python3.12.16,
  con todas las dependencias transitivas y hashes de artefactos.
- `requirements-build.txt` fija el wheel de pip usado al construir.
- Docker instala únicamente wheels con hashes y ejecuta `pip check`.
  Las instalaciones locales también deben usar `pip install --require-hashes
  --only-binary=:all: -r requirements.txt`.

Para regenerar el lock, desde Linux en la raíz del repositorio:

```sh
lock_dir=$(mktemp -d)
docker run --rm \
  --mount "type=bind,source=$PWD/requirements.in,target=/src/requirements.in,readonly" \
  --mount "type=bind,source=$lock_dir,target=/out" \
  python:3.12.16-slim-trixie@sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e \
  sh -ec '
    python -m venv /tmp/lockenv
    /tmp/lockenv/bin/python -m pip install --index-url https://pypi.org/simple pip==26.2.2 pip-tools==7.6.2
    /tmp/lockenv/bin/pip-compile --generate-hashes --allow-unsafe \
      --no-emit-index-url --no-emit-trusted-host \
      --output-file /out/requirements.txt \
      --pip-args "--only-binary=:all: --index-url https://pypi.org/simple" /src/requirements.in
  '
cp "$lock_dir/requirements.txt" requirements.txt
```

Revisar el diff generado y las versiones publicadas antes de subirlo. Un hash
valida el artefacto aprobado; no sustituye la evaluación de una versión nueva.
Al actualizar pip, regenerar también su hash desde el wheel oficial de PyPI.

## Verificación y aprobación

El workflow `WMS security and Linux tests` construye la imagen, comprueba
consistencia/parser, audita TODOS los paquetes Python instalados e incluye pip,
y ejecuta los tests sintéticos con red externa deshabilitada. `Dockerfile.test`
añade Node24.22.1 únicamente a la imagen de QA para los tests de JavaScript;
la imagen productiva sigue sin Node ni herramientas de pruebas. No recibe secretos
de producción, no autoriza cuentas, envía correos, fusiona PR ni despliega.
Un resultado sin avisos de pip-audit no es un escaneo exhaustivo del SO ni prueba
ausencia de cualquier vulnerabilidad. Revisar también avisos de la imagen base.

La suite completa debe pasar junto con pruebas de Excel, Microsoft, recepción,
etiquetas y reportes. Probar con fixtures o una copia autorizada; no dar por hecha
una validación en Android físico a partir de tests de servidor.

Después de revisión y fusión, el responsable aplica el procedimiento existente
de respaldo/instalación del lector. App y backup deben usar la misma imagen
aprobada. Comprobar Python/Expat/librerías reales, `/health`, login y los cortes;
conservar la imagen anterior para volver atrás si falla. No ejecutar `pip
install --upgrade` dentro del contenedor activo como sustituto del despliegue.

El overlay legado de Microsoft copia el lector Excel común y exige una base con
el parser protegido; falla durante build si la base es antigua. El lector actual
se construye completo. Esto no actualiza ni reconstruye automáticamente la
versión manual congelada.

## Mantenimiento separado del host

El pin cloudflared2026.10.4 se aplica al recrear el túnel lector en una ventana
aprobada; no reiniciar un túnel funcional solo porque se publicó este PR.
Docker Engine29.9.2 es una actualización del host, no de la imagen WMS. Su
instalación puede interrumpir otros contenedores y se coordina por separado.
El parche de la versión manual también requiere una autorización específica.
Nada de esto autoriza reiniciar Windows o WSL.

## Referencias

- [Python3.12.16](https://www.python.org/downloads/release/python-31216/)
- [Cryptography/OpenSSL](https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf)
- [MSAL1.39.0](https://github.com/AzureAD/microsoft-authentication-library-for-python/releases/tag/1.39.0)
- [Openpyxl: XML](https://openpyxl.readthedocs.io/en/stable/#security)
- [Docker29.9.2](https://github.com/moby/moby/releases/tag/docker-v29.9.2)
