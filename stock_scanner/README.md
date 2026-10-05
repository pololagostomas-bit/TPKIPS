# Consulta de stock por NP

Módulo independiente, de solo lectura, que consulta el corte `STOCK2109.xlsx` y permite buscar el NP manualmente o escanearlo con la cámara del teléfono.

Al encontrar un NP muestra descripción, unidad, stock en almacén, comprometido, disponible y ubicaciones con existencia. Si el artículo está en más de una ubicación, aparecen todas. El lector usa `html5-qrcode` desde un CDN; se requiere conexión a internet para descargar la librería. La cámara funciona en `localhost` o en un sitio servido con HTTPS y permiso del navegador.

## Ejecutar en Windows

Desde la raíz del proyecto, en la terminal integrada de VS Code, inicia el servidor. La terminal te pedirá un usuario y una contraseña; la contraseña no se mostrará mientras la escribes.

```powershell
.\.venv\Scripts\python.exe .\stock_scanner\server.py
```

Abrir <http://127.0.0.1:8765>. Detener con `Ctrl+C`.

## Usarlo desde un celular

El servidor exige usuario y contraseña mediante el diálogo del navegador. Para uso entre redes distintas, se puede crear un enlace HTTPS temporal con Cloudflare Tunnel. Instala `cloudflared` y mantén abierta una segunda terminal:

```powershell
cloudflared tunnel --url http://localhost:8765
```

Abre en el celular la dirección `https://…trycloudflare.com` que aparezca en esa segunda terminal e ingresa las credenciales configuradas arriba. Mantén abiertas ambas terminales y la PC encendida. Los túneles rápidos son para pruebas y la URL cambia al reiniciar el túnel.

El celular y la PC deben estar en la misma red para usar la IP local; para redes distintas, usa el enlace HTTPS del túnel. La cámara requiere HTTPS en el celular.

Alternativamente, con un certificado TLS emitido para el nombre de la PC (por ejemplo, por TI), inicia desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe .\stock_scanner\server.py --host 0.0.0.0 --port 8765 --cert 'C:\certificados\almacen.crt' --key 'C:\certificados\almacen.key'
```

En el celular abre `https://NOMBRE-DE-LA-PC:8765`. Permite el acceso a la cámara. El nombre debe coincidir con el certificado y resolver dentro de la red. También se debe permitir el puerto 8765 en el firewall de Windows para la red privada. No publiques este servidor directamente en internet.

El Excel predeterminado es el archivo `STOCK2109.xlsx` entregado para este módulo. Para usar un corte actualizado, configúralo al iniciar:

```powershell
$env:TRITON_STOCK_FILE = 'C:\ruta\al\stock_actual.xlsx'
.\.venv\Scripts\python.exe .\stock_scanner\server.py
```

Por defecto el servidor solo escucha en el mismo equipo (`127.0.0.1`) y no modifica el Excel ni la base del WMS. Para consultar un código, el lector de barras debe contener el NP (Número de artículo) del reporte.
