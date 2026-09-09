# Compartir Triton Picking con Docker

Usa el archivo ZIP de distribución. No contiene el Excel ni la base de pruebas;
cada equipo inicia con su propia base vacía y la carga desde **Cargar Excel**.

## Requisito único

Instalar [Docker Desktop](https://www.docker.com/products/docker-desktop/) y
abrirlo hasta que indique que está en ejecución.

## Iniciar la aplicación

1. Descomprime el ZIP en una carpeta, por ejemplo `C:\Triton-Picking`.
2. Abre PowerShell dentro de esa carpeta.
3. Ejecuta:

   ```powershell
   docker compose up -d --build
   ```

4. Espera el mensaje de creación y entra a `http://127.0.0.1:8000`.
5. Ingresa como `ADMINISTRADOR` y usa **Cargar Excel** para cargar la última
   exportación de SAP.

La base operativa se guarda en el volumen `triton-picking-data`; no se pierde
al apagar o actualizar el contenedor.

## Detener e iniciar después

```powershell
docker compose stop       # detener
docker compose start      # iniciar nuevamente
```

## Actualizar el programa sin borrar datos

Reemplaza los archivos del ZIP por la versión nueva y ejecuta:

```powershell
docker compose up -d --build
```

No ejecutes `docker compose down -v` salvo que quieras borrar por completo la
base, historial y atenciones de ese equipo.

## Copia de seguridad antes de actualizar

```powershell
docker compose cp triton-picking:/data/triton.db .\triton-respaldo.db
```

Este modo es para piloto local o una sola PC. Para acceso simultáneo desde más
de un equipo se usa la publicación en Azure y PostgreSQL.
