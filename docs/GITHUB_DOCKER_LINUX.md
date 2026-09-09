# Publicación desde GitHub a Linux con Docker

Este paquete se sube completo a un repositorio privado de GitHub. Incluye el
backend, la interfaz, Docker Compose, pruebas y documentación. No incluye la
base SQLite, archivos Excel, `.env`, contraseñas ni copias de seguridad.

## Antes del primer despliegue

1. Cree un repositorio privado en GitHub, por ejemplo `triton-wms-piloto`.
2. Suba el contenido descomprimido del paquete. Mantenga la carpeta
   `infrastructure/` en la raíz del repositorio.
3. En el servidor Linux, clone el repositorio y entre a su carpeta:

   ```bash
   git clone <URL-DEL-REPOSITORIO> triton-wms
   cd triton-wms
   ```

4. Cree el volumen persistente una sola vez. No lo elimine al actualizar:

   ```bash
   docker volume create triton-wms-production-data
   ```

5. Copie el archivo de variables y complete una contraseña inicial segura:

   ```bash
   cp .env.example .env
   nano .env
   ```

   Defina como mínimo:

   ```dotenv
   TRITON_DATA_VOLUME=triton-wms-production-data
   TRITON_BOOTSTRAP_ADMIN_USERNAME=admin.almacen
   TRITON_BOOTSTRAP_ADMIN_PASSWORD=<CONTRASEÑA-SEGURA>
   TRITON_HOST_PORT=8080
   TRITON_BIND_ADDRESS=0.0.0.0
   ```

## Arranque y validación

```bash
docker compose -f infrastructure/docker-compose.yml up -d --build
docker compose -f infrastructure/docker-compose.yml ps
curl http://127.0.0.1:8080/health
```

El resultado esperado de salud contiene `"status":"ok"`. En la red interna,
los equipos acceden a `http://IP-DEL-SERVIDOR:8080/`.

## Actualización sin perder información

```bash
git pull
docker compose -f infrastructure/docker-compose.yml up -d --build
```

El volumen `triton-wms-production-data` conserva `triton.db`, usuarios,
atenciones e historial. Nunca ejecute `docker compose down -v` en producción:
ese comando sí elimina volúmenes.

## APK Android

El APK actual carga el WMS mediante WebView desde
`http://192.168.0.243:8080/`. Una actualización del contenedor se ve de forma
automática en el celular. Solo recompilar el APK si cambia la IP/puerto, se
publica un dominio HTTPS o se modifica la aplicación Android nativa.
