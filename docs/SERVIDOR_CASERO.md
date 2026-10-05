# Servidor casero WMS v0.3

Este despliegue parte de `wms-v0.3-clean`, commit
`11bebfb513bf2197a34bf36cb23c074e8c419c67`. No cambia la logica de negocio.
Es un piloto nuevo: los datos de la otra PC NO estan incluidos.

## Componentes

- Ubuntu WSL2 y Docker Engine ya instalados en la laptop.
- `infrastructure/docker-compose.home.yml`, separado de produccion y desarrollo.
- Aplicacion Waitress con autenticacion local y cookies Secure/HttpOnly.
- Puerto 8086 publicado solamente en 127.0.0.1, sin abrir puertos del router.
- Volumen `triton-wms-home-data` para SQLite y usuarios.
- Volumen `triton-wms-home-backups` para copias online verificadas cada 24 horas.
- Correo y conexiones a SAP/Graph sin configurar; no se envian correos empresariales.
- Cloudflare Quick Tunnel protegido por PIN enviado a un correo autorizado.

El tunel no exige comprar un dominio ni un plan de alojamiento. La electricidad
y conexion a Internet siguen dependiendo de la laptop. No es un servicio 24/7:
se corta al apagar, suspender o desconectar el equipo, y el enlace cambia cuando
se reinicia el tunel. Para produccion se requiere otro esquema de continuidad.
La copia en el mismo equipo no protege frente a perdida de la laptop.

## Arranque inicial en Ubuntu

Desde la raiz del repositorio, sustituir el correo por el propio:

```bash
python3 infrastructure/deployment/init-home.py \
  --email usuario@example.com \
  --destination "$HOME/.config/triton-wms-home/.env"
docker compose --env-file "$HOME/.config/triton-wms-home/.env" \
  -f infrastructure/docker-compose.home.yml build app
docker compose --env-file "$HOME/.config/triton-wms-home/.env" \
  -f infrastructure/docker-compose.home.yml --profile remote up -d --wait
docker compose --env-file "$HOME/.config/triton-wms-home/.env" \
  -f infrastructure/docker-compose.home.yml logs --tail=100 tunnel
```

El generador no sobrescribe configuraciones existentes. La clave aleatoria
queda en el archivo privado, fuera del repositorio. Nunca se debe publicar ese
archivo, la base de datos, los Excel operativos ni los backups.

En Windows, WSL necesita permanecer activo; un proceso oculto
`wsl.exe -d Ubuntu --exec /bin/sleep infinity` mantiene esta sesion.
El archivo local `INICIAR_WMS.ps1` facilita el arranque tras reiniciar Windows.
No se instala una tarea de inicio ni se cambia la suspension de Windows.

## Flujo GitHub pendiente de habilitar

1. Crear `main` desde el commit v0.3 indicado arriba, sin modificar las ramas anteriores.
2. Publicar estos cambios en una rama separada y abrir PR hacia `main`.
3. Revisar y fusionar ese PR manualmente. No activar auto-merge.
4. En GitHub, Settings > Actions > General > Workflow permissions, permitir
   que GitHub Actions cree pull requests. El workflow pide solo lectura de
   contenido y escritura de PR; no necesita secretos de la laptop.
5. Crear las siguientes ramas de trabajo desde `main` actualizado para que
   contengan `.github/workflows/auto-pr.yml`. Cada push abre un PR si no existe;
   siguientes pushes actualizan ese mismo PR.
6. Para exigir revisiones independientes, configurar reglas de rama y un
   segundo revisor. El propietario no puede aprobar su propio PR: en el piloto,
   su fusion manual constituye la autorizacion de despliegue.

El workflow no fusiona ni despliega. No ejecuta scripts de la rama entrante.
Un PR creado por `GITHUB_TOKEN` puede no disparar otros workflows; no debe
suponerse que eso equivale a pruebas CI aprobadas.

## Actualizacion del servidor tras fusionar

`infrastructure/deployment/deploy-home.py` es un agente para un repositorio
PUBLICO. No guarda tokens. Para un repositorio privado hay que adaptar la
autenticacion con acceso de lectura limitado; no hacerlo publico para evitar
configurar credenciales.

Se ejecuta desde una copia local revisada, nunca desde una rama que llegue
por PR. Recibe un Compose fijo y no adopta automaticamente cambios de Compose,
Docker mounts, permisos o del propio agente.

Ejemplo de inicializacion (solo registra la version que YA esta funcionando):

```bash
python3 infrastructure/deployment/deploy-home.py \
  --repository pololagostomas-bit/TPKIPS --base main \
  --state-dir "$HOME/.local/state/triton-wms-home" \
  --env-file "$HOME/.config/triton-wms-home/.env" \
  --compose-file "$PWD/infrastructure/docker-compose.home.yml" \
  --initialize-sha 11bebfb513bf2197a34bf36cb23c074e8c419c67
```

Tras verificar GitHub y sus permisos, ejecutar la misma orden reemplazando
`--initialize-sha ...` por `--watch`. Consulta cada cinco minutos. Por ahora
NO se instala ni ejecuta este agente: falta publicar y fusionar el PR.

Antes de tocar contenedores, el agente exige:

- El commit debe ser la punta exacta de `main`.
- GitHub debe asociarlo a un PR cerrado y fusionado sobre ese mismo repositorio/base.
- La fusion debe haberla realizado el propietario del repositorio.
- El commit debe descender de la version anterior, sin reescritura de historia.
- La imagen nueva debe compilar y la copia de seguridad debe completarse.

Luego recrea app/backup y exige salud HTTP. Si falla, detiene la version nueva
y bloquea futuras actualizaciones. No borra volumenes ni restaura bases de
datos automaticamente. Revisar logs y una copia validada antes de recuperar;
ver `OPERACION_LINUX.md`. El bloqueo en `state.json` solo se retira despues
de una recuperacion comprobada. Conservar las imagenes y releases anteriores.

No usar `git pull` ni `docker compose up --build` sobre codigo sin revisar
como sustituto de este control. No ejecutar `down -v`.

## Comprobaciones

```bash
python3 -m unittest tests.test_home_setup tests.test_home_deploy -v
docker compose --env-file "$HOME/.config/triton-wms-home/.env" \
  -f infrastructure/docker-compose.home.yml ps
```

Las pruebas de identidad originales son `tests.test_local_identity`; requieren
las dependencias de `requirements.txt` y se ejecutan contra bases temporales,
nunca contra la base del servidor. Antes de un uso real hay que probar desde
Android con datos moviles, cargar un Excel de prueba y validar ambos modulos.

Fuentes oficiales:
- https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
- https://docs.github.com/en/actions/tutorials/authenticate-with-github_token
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository
