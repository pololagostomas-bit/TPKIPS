# Inventario: Etiqueta Generica De SKU

Aplica solo al lector mantenido. La etiqueta de Inventario identifica el
producto, no una recepcion, cliente, pedido ni atencion. No cambia movimientos,
stock, aprobaciones NPS ni el despliegue manual.

## Contrato De Pantalla

| Punto | Regla |
| --- | --- |
| Usuario / tarea | Los roles existentes de Inventario consultan un material e imprimen su etiqueta. |
| Contexto | Capturar el NP exacto del boton seleccionado, aunque se consulte otro material durante la preparacion. |
| Autoridad | GET /api/inventory/label?item_code=... verifica de nuevo el material exacto en el catalogo; no acepta contenido de etiqueta enviado por el navegador. |
| Contenido | Marca disponible, logo privado, Triton pequeno, NP, descripcion, Data Matrix y ubicacion por defecto. Sin OV, cliente ni BL, ni recuadros vacios para esos campos. |
| Ubicacion | Del corte SAP cuando stock_qty es positivo. Sin stock, dejar el recuadro en blanco, incluso si el corte conserva una ubicacion anterior. No es una ubicacion de conteo. |
| Accion | Imprimir etiqueta abre una vista previa. No imprime automaticamente ni crea un alias o movimiento. Deshabilitar el boton durante la preparacion. |
| Error | Cerrar la vista incompleta, mostrar el error y permitir reintentar. No sustituir una respuesta fallida con una etiqueta vieja. |
| Movil / PC | Mismo flujo y datos; tabla comparativa desplazable dentro de su contenedor, boton de 48px y vista previa que cabe en el ancho disponible. |
| Permisos | La API comprueba el rol de Inventario. Los logos usan una ruta autenticada independiente; no amplia acceso a operaciones de Recepcion. |

## Impresion Y Codigos

Reutiliza reception-labels.js/css y bwip-js local, con un perfil exclusivo de
Inventario. El perfil de conteo/EM conserva OV, cliente, BL, ubicacion y su
distribucion. La carga del motor Data Matrix ocurre al imprimir; la biblioteca
de camara ya existente se carga solo al abrir la camara, sin nueva dependencia.

Formato predeterminado confirmado: TSC TE200, 4 x 3 pulgadas (101.6 x 76.2 mm),
horizontal, con los mismos controles y preferencias de papel. El NP ocupa todo
el ancho; la ubicacion queda al lado del Data Matrix de 22mm. Marca y descripcion
aprovechan el espacio sin introducir campos de documentos de recepcion.

El Data Matrix ECC200 contiene solamente el NP canonico, conservando signos y
minusculas. No usa GS1, URL ni prefijo WMS. Los alias antiguos siguen consultables;
no se borran ni migran. La API antigua de generacion de alias permanece compatible,
pero no selecciona el contenido de las nuevas etiquetas ni requiere un boton
adicional antes de imprimir.

La busqueda admite el identificador AIM ]d1 cuando no existe una coincidencia
literal; un SKU que realmente contiene ese prefijo tiene prioridad. La camara
usa area cuadrada y evita tramitar dos veces el mismo resultado durante el cierre.
La biblioteca soporta Data Matrix segun su
[documentacion oficial](https://scanapp.org/html5-qrcode-docs/docs/supported_code_formats).
Esto no certifica el hardware, permisos de Android o enfoque real de una camara.

La marca se obtiene de registros existentes del mismo NP exacto. Normalizar
regiones solo para mostrar, nunca reescribir el origen ni deducir marca del NP.
Con varias marcas, mostrar sus nombres y no elegir arbitrariamente un logo.
Sin marca conocida, no inventarla. Imagenes permanecen privadas en el servidor.

## Verificacion

- unittest discover: 599 pruebas, OK, dos skips esperados.
- inventory_labels_browser.cjs con support_inventory_labels_server.py:
  1366x900, 393x873, 320x640 y 873x393; rol PICKER, codigos exactos,
  logos privados, ubicacion vacia sin stock, campos omitidos, popup bloqueado,
  error 403, no autoimpresion y limites de pagina. Callbacks de camara simulados,
  busqueda AIM, area cuadrada, Escape y bloqueo de resultado duplicado.
- Ocho paginas PDF de Inventario, horizontal/vertical: dimensiones fisicas,
  descripcion larga completa y decodificacion independiente de cada Data Matrix
  a 203 dpi con zxing-cpp. Inspeccion visual de PNGs rasterizados.
- Regresion em_labels_browser.cjs: cinco viewports y perfiles existentes de
  recepcion conservados; PDF de recepcion y catalogo de diez marcas decodificados.
- Sin instalacion, fusion, correos reales ni cambios de datos productivos.
  Quedan pendientes aprobacion/instalacion y prueba fisica en TSC TE200/lector.

Evidencia local privada en qa/inventory-labels y qa/em-labels; no publicar
capturas, PDFs, logos, Excel ni SQLite junto con el codigo.
