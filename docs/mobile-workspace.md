# Workspace movil: Despacho, Recepcion e Inventario

La interfaz sigue siendo Python en el servidor y HTML/CSS/JavaScript en el
cliente. No requiere una app Android instalada ni dependencias nuevas de
produccion. La misma capa de presentacion se aplica a la variante manual y a
la variante con lector; sus reglas de recepcion siguen siendo independientes.

## Ajustes

- Controles tactiles de al menos 44 px, campos de 16 px y titulos compactos.
- Selector de etapas en movil; pestanas originales en escritorio.
- Tablas convertidas en registros verticales en movil, con sus mismos campos,
  botones y ordenamiento. No se clonan acciones de negocio.
- Panel visible "Modificar estados" para los controles originales del
  administrador, conservando permisos, motivos, confirmaciones y auditoria.
- Ventanas limitadas a la altura visible, incluido el ajuste visualViewport.
- Filas de ubicacion del camion sin desbordamiento, incluso a 320 px.
- Inventario sin contenido provisional; solicitudes protegidas contra doble
  envio y contra descarte inadvertido al navegar.
- Transferencias de Recepcion muestra las BL reales pendientes de transferencia.
- Las respuestas tardias de carga inicial/trabajo no reemplazan otra vista que
  el usuario ya haya abierto.
- Los selectores de navegacion no generan falsos cambios sin guardar.

## Verificacion reproducible

Ejecutar la regresion con Python y Node.js disponibles:

```text
python -m unittest discover -s tests -q
```

Las pruebas DOM usan jsdom 26.1.0 como dependencia EXCLUSIVA de QA. Instalarlo
fuera de las dependencias de produccion, por ejemplo en qa/runtime/mobile-tests,
y configurar NODE_PATH al directorio node_modules correspondiente.

Iniciar una base desechable y escuchar solo en loopback:

```text
python tests/support_mobile_server.py 8098
node tests/mobile_workspace_dom.cjs http://127.0.0.1:8098
node tests/mobile_truck_dom.cjs http://127.0.0.1:8098
```

Reiniciar el servidor fixture antes de repetir la secuencia: los tests cambian
estados y registran una llegada SOLO en la base temporal. No apuntarlos al
servidor real. En la variante manual usar otra instancia/puerto (por ejemplo
8099). Las capturas DOM quedan en qa/runtime/mobile-views y se pueden revisar
en /qa/mobile/<nombre>.html; esa ruta existe solo en el servidor fixture.

Se verificaron 27 vistas por variante en 320x640, 360x780, 393x873, 412x915,
393x480 y 1366x900. La revision visual del navegador usa estados DOM congelados;
las acciones se verifican separadamente en la integracion DOM y el backend.
El tamano 393x873 es aproximado, no una certificacion de un modelo Honor.
El escaneo se probo con codigos introducidos por texto, no con camara ni lector
fisico. El comportamiento del teclado virtual requiere validacion en Android.

## Publicacion

La variante con lector requiere revision y fusion del PR por el propietario;
el agente existente despliega main despues de esa aprobacion. No fusionar el
PR ni reiniciar el tunel para esta actualizacion.

La variante manual se actualiza separadamente, con copia de seguridad y
reversion de imagen. Las bases y la politica de autenticacion no se sustituyen.
