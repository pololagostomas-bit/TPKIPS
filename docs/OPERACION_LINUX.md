# Operación de TRITON WMS en Linux

Esta guía cubre el piloto Docker de **una sola instancia**. SQLite no admite
varias réplicas de la aplicación escribiendo la misma base; no escale el
servicio `app` por encima de una instancia ni monte la base en NFS/Azure Files.

## Preparación

1. Instale Docker Engine con el complemento Compose.
2. Copie `.env.example` a `.env` en la raíz del proyecto.
3. Defina una contraseña larga y única en
   `TRITON_BOOTSTRAP_ADMIN_PASSWORD`. No existe una contraseña predeterminada.
4. Mantenga `TRITON_AUTH_MODE=local` y cambie el usuario bootstrap si procede.
5. Para acceso LAN, mantenga `TRITON_BIND_ADDRESS=0.0.0.0` y abra solamente
   `TRITON_HOST_PORT` (8080 por defecto) en el firewall para la red autorizada.

El servicio interno escucha en 8000. El puerto del host es parametrizable y no
obliga a cambiar la imagen.

### Conservar la base existente antes de actualizar

El volumen de datos es externo y obligatorio. Con TI, identifique el volumen
que monta el contenedor actual mediante `docker inspect NOMBRE_CONTENEDOR`
(sección Mounts). Escriba su nombre exacto en `TRITON_DATA_VOLUME` de `.env`.
No cree otro volumen para una actualización: parecería que desaparecieron los datos.
Realice una copia verificada antes de detener la versión anterior. Compruebe
que el usuario 10001 de la nueva imagen puede escribir en ese volumen.

Solo para una instalación completamente NUEVA y sin datos anteriores:

```bash
docker volume create triton-wms-production-data
```

Después configure `TRITON_DATA_VOLUME=triton-wms-production-data`. Compose
rechaza un nombre inexistente; no crea silenciosamente una base alternativa.

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml config --quiet
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
docker compose --env-file .env -f infrastructure/docker-compose.yml logs --tail=100 app backup
```

La imagen `triton-wms:v0.2.0` ejecuta `python -m backend.wsgi` con Waitress,
usuario no privilegiado UID/GID 10001 y healthcheck HTTP. El endpoint `/health`
debe comprobar también acceso a la base y espacio en disco; esa respuesta la
implementa la integración principal.

Los logs Docker rotan en cinco archivos de 10 MB por servicio. Cambie secretos
rotando `.env` y recreando el servicio; no incluya `.env` en la imagen ni en Git.

## Desarrollo aislado

El archivo de desarrollo usa otro nombre de proyecto, otro volumen y solo
publica en localhost:8081. El modo demo queda limitado a este entorno.

```bash
docker compose -f infrastructure/docker-compose.dev.yml up --build
```

Nunca combine ambos archivos Compose: son configuraciones independientes.

## Copias online

El servicio `backup` crea una copia inmediatamente al arrancar y luego cada
`TRITON_BACKUP_INTERVAL_SECONDS` (24 horas por defecto). Usa la API online de
SQLite, valida `PRAGMA quick_check`, publica el archivo de forma atómica y crea
un `.sha256`. La retención predeterminada conserva como máximo 30 copias y
elimina archivos de más de 30 días.

Crear o verificar una copia manualmente:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backup \
  python -m backend.maintenance backup
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backup \
  python -m backend.maintenance check /home/backups/triton-AAAAMMDDTHHMMSSffffffZ.db
```

El volumen `triton-wms-production-backups` está en el mismo host y **no basta
como recuperación ante pérdida del servidor**. Copie periódicamente los `.db`
y `.sha256` cerrados a almacenamiento externo cifrado e inmutable (por ejemplo,
un bucket con versionado o repositorio de backups). No copie `triton.db`, sus
archivos WAL/SHM ni un archivo `.partial`. Verifique hashes y haga un ensayo de
restauración fuera de producción al menos mensualmente.

## Restauración segura

Deshabilite el envío de correo antes de restaurar. La herramienta pone los
mensajes restaurados pendientes/en error/en proceso en `REVISAR ENVIO` para
evitar duplicados. Concílielos con el buzón de enviados antes de reintentarlos.
Una copia restaurada manualmente fuera de esta herramienta no aplica esa protección.

Por defecto la restauración nunca toca la base activa; crea
`/home/data/triton.restored.db` para inspección:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backup \
  python -m backend.maintenance restore /home/backups/triton-AAAAMMDDTHHMMSSffffffZ.db
```

Compruebe el archivo restaurado antes de una sustitución. Para reemplazar la
base activa hay que detener **app y backup**, ejecutar un contenedor puntual con
los dos indicadores explícitos y arrancar nuevamente:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml stop app backup
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm --no-deps backup \
  python -m backend.maintenance restore \
  /home/backups/triton-AAAAMMDDTHHMMSSffffffZ.db \
  --destination /home/data/triton.db --overwrite --app-stopped
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d app backup
```

`--app-stopped` es una declaración operativa: la herramienta no puede demostrar
que no exista otro proceso usando el volumen. Nunca use esos indicadores con la
aplicación activa.

## Actualización y recuperación

Antes de actualizar, cree una copia online y expórtela fuera del host. Mantenga
una sola versión de la aplicación activa, reconstruya la imagen y revise el
healthcheck y los logs. Si falla, detenga servicios, restaure una copia validada
y vuelva a la imagen anterior. No elimine los volúmenes durante un rollback.
