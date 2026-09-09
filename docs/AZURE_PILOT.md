# Publicar el piloto en Azure

Este procedimiento publica la app para prueba interna. Usa Azure App Service,
Azure Container Registry y una única instancia. No es aún el despliegue
productivo: la versión actual usa SQLite, que no debe compartirse entre varias
instancias ni ubicarse en Azure Files.

## Antes de ejecutar

1. Instala Azure CLI y entra con la cuenta autorizada: `az login`.
2. Pide a TI una suscripción, región y un nombre globalmente único para la web.
   La cuenta debe tener `Contributor` para crear recursos y, además, `Owner`,
   `User Access Administrator` o `Role Based Access Control Administrator`
   sobre el grupo/suscripción para asignar el permiso `AcrPull` a la Web App.
3. Elige nombres nuevos, por ejemplo:
   - grupo: `rg-triton-picking-piloto`
   - web: `triton-picking-piloto-empresa`
   - registro: `tritonpickingpiloto` (sin guiones)
4. Abre PowerShell en esta carpeta. El script construye la imagen en Azure; no
   requiere instalar Docker en el equipo.

## Ejecutar el piloto

```powershell
Set-Location -LiteralPath "C:\ruta\triton-picking"
.\deploy-azure-pilot.ps1 `
  -SubscriptionId "00000000-0000-0000-0000-000000000000" `
  -ResourceGroup "rg-triton-picking-piloto" `
  -Location "eastus" `
  -AppName "triton-picking-piloto-empresa" `
  -RegistryName "tritonpickingpiloto"
```

Al terminar, el script muestra una URL `https://...azurewebsites.net`. En esta
primera publicación la app queda en `demo`, únicamente para validar la carga,
los roles simulados y el flujo completo. Ingresa como `ADMINISTRADOR` y usa
**Cargar Excel** para actualizar las OVs. La carga no borra atenciones ni su
historial; actualiza las líneas fuente y crea la Atención 1 solo para nuevas OVs.

## Activar usuarios reales (Microsoft Entra)

Antes de entregar la URL a operación:

1. En la Web App, abre **Authentication** y agrega el proveedor **Microsoft**.
2. Configura que se requiera autenticación para todas las solicitudes.
3. Registra o selecciona la aplicación en Microsoft Entra y agrega los roles de
   aplicación `ADMINISTRADOR`, `PICKER` y `GUIADOR`.
4. Asigna cada usuario o grupo al rol correspondiente.
5. Vuelve a ejecutar el script con `-AuthMode entra` o cambia el ajuste de
   aplicación `TRITON_AUTH_MODE` a `entra` y reinicia la Web App.
6. Prueba con un usuario de cada rol. Sin una identidad validada, la aplicación
   debe rechazar la solicitud.

La app lee la identidad y roles que App Service entrega mediante
`X-MS-CLIENT-PRINCIPAL`; no usa contraseñas ni secretos en el código.

## Límites deliberados del piloto

- Mantener una sola instancia y no activar escalado horizontal.
- No usar Azure Files como base SQLite. Azure lo desaconseja específicamente
  porque SQLite depende de bloqueos de archivos.
- Hacer una copia de `triton.db` antes de una actualización relevante.
- Para producción: migrar a Azure Database for PostgreSQL, usar Key Vault para
  SAP y habilitar la conexión SAP de solo lectura.

Referencias: [contenedor en App Service](https://learn.microsoft.com/en-us/azure/app-service/quickstart-custom-container), [almacenamiento persistente](https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container), [identidad del usuario](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-user-identities).
