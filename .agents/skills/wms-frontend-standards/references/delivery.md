# Flujo De Creacion Y Entrega

## Antes De Editar

1. Resolver el checkout y variante actuales; revisar status/diff y la memoria del
   tema si esta disponible. No rehacer una investigacion ya documentada sin comparar
   con el codigo actual. No editar la aplicacion manual separada.
2. Definir rol, entidad, tarea y accion principal. Para un flujo nuevo o un cambio
   material de interaccion, completar el contrato de pantalla enlazado desde la
   skill; para una correccion pequena basta describir la diferencia y su prueba.
3. Localizar la pantalla hermana, helper API, permisos backend y CSS efectivo.
   Elegir el componente existente que resuelve el problema antes de crear otro.
4. Consultar solo el dominio relevante de ui-ux-pro-max. Validar su ajuste al WMS;
   las fuentes externas no reemplazan el MASTER ni autorizan dependencias.

## Implementacion

Trabajar una seccion vertical completa: lectura, accion, guardado, error, retorno
y permiso, con el mismo contrato en celular y PC. Mantener semantica nativa,
contexto BL/atencion y filtros. Un cambio visual no cambia una regla de negocio.

En estilos, reutilizar tokens/componentes y mantener el alcance del modulo. No
anadir un override !important a otra hoja solo para ganar especificidad; localizar
primero la regla responsable. Si se cambia un helper o el shell, ampliar pruebas
a sus consumidores. No migrar toda la CSS ni todos los modulos por una correccion.

## Matriz Minima

El ancho es de viewport CSS, no resolucion fisica del telefono. Honor X8 es una
referencia de uso, no un dispositivo emulado/certificado por esta matriz.

| Caso | Viewport de referencia | Objetivo |
| --- | --- | --- |
| Celular estrecho | 320x640 | Reflow sin perder acciones ni texto esencial. |
| Celular pequeno | 375x812 | Objetivos tactiles y formularios apilados. |
| Celular habitual | 393x873 | Flujo principal, lector, foco y CTA. |
| Tableta / ancho intermedio | 768x1024 | Nada depende de tener sidebar de PC. |
| Umbral del shell | 820x900 y 821x900 | Lista/detalle y navegacion no quedan duplicadas ni inaccesibles. |
| Laptop | 1366x768 | Teclado, raton, tablas y navegacion de retorno. |
| PC amplia | 1440x900 | Densidad y limites de contenido. |
| Celular horizontal | 873x393 | Poca altura y acceso al campo/accion final. |

Para un cambio de componente probar 320px, 393px, laptop y horizontal; agregar
375px cuando cambien objetivos tactiles. Para shell, tokens o navegacion usar la
matriz completa, incluidos los dos lados del breakpoint. No duplicar todas las
combinaciones si no aportan cobertura del riesgo concreto.

Cuando se toquen texto/layout, probar ampliacion de texto al 200% y reflow a
320 CSS px. Simular menos altura es una prueba adicional, no un teclado Android
real. Cuando se toquen acciones fijas/camara/escaneo, comprobar teclado visible,
modo sin teclado del lector HID, Enter y rotacion en hardware si esta disponible.
Registrar lo que no pudo probarse. Verificar reduced-motion cuando haya movimiento.
Solo probar temas que la app soporte; no inventar soporte oscuro por una media query.

## Criterios De Aceptacion

- No overflow horizontal de pagina, texto cortado ni controles solapados.
- Los contenedores de tabla justificados pueden desplazarse sin ensanchar la pagina.
- El foco y los controles criticos siguen alcanzables; los overlays no los tapan.
- Botones/objetivos de toque cumplen el MASTER, tienen nombre y estado accesibles.
- Navegar no revierte ni envia correos; guardar dos veces no duplica movimientos.
- Error de API conserva borradores; reintento mantiene guia, BL, atencion y codigo.
- Lecturas tardias no reemplazan la pantalla nueva. Sin conexion no hay exito falso
  ni una version antigua operable desde cache.
- Rol no autorizado no puede ejecutar el cambio ni invocando directamente la API.
- La preferencia de ayudas no oculta errores, requisitos ni correcciones del admin.
- Atras a lista/camion conserva el contexto. Modal restaura foco y tiene salida.

No basta comprobar que un elemento exista en el DOM. Usar Playwright para su
accion real, geometria, foco, errores de consola y capturas desktop/mobile. Las
capturas son evidencia local privada con datos ficticios, no activos del frontend.

## Pruebas Existentes

Elegir suites por el cambio, leyendo sus precondiciones antes de ejecutarlas.

| Cambio | Pruebas de referencia |
| --- | --- |
| Camion / progreso / marcas | test_reception_barcode_scanning.py, test_reception_scan_ui.py, test_truck_controls.py, truck_progress_browser.cjs |
| BL / NP / conteo / ubicacion | test_reception_np_scan_ui.py, reception_np_concise_browser.cjs, reception_items_browser.cjs |
| Navegacion / viewport | reader_ui_browser.cjs, truck_return_browser.cjs, truck_locations_browser.cjs |
| Preferencias de informacion | reader_guidance_browser.cjs |
| Conexion / cache / carga | reader_pwa_browser.cjs, reader_performance_browser.cjs |
| Correos de transferencia | test_reception_transfer.py, transfer_browser.cjs |
| Etiquetas | em_labels_browser.cjs, label_layout_browser.cjs, verify_label_pdf.py y lectura independiente del Data Matrix |

Ejemplo ya usado para camion (dos terminales, entorno QA con dependencias
disponibles, puerto libre; nunca apuntar a la URL productiva):

```text
python -u tests/support_dhl_server.py 50655 progress
node tests/truck_progress_browser.cjs http://127.0.0.1:50655
```

El fixture crea SQLite temporal y respuestas DHL ficticias; no sustituirlo por
la base real. transfer_browser.cjs usa support_transfer_server.py, que desactiva
workers externos y simula la autorizacion de correo. No instalar dependencias en
produccion para ejecutar QA; resolver el Python/Node de pruebas ya disponible.
Al terminar, detener solo los fixtures creados por la tarea.

Cambios de estado, permisos, persistencia o helpers compartidos requieren sus
pruebas backend y, cuando su alcance lo justifique, la suite general:

```text
python -m unittest discover -s tests -q
git diff --check
```

Una modificacion solo de documentacion/skill requiere validacion de la skill,
enlaces/rutas, consistencia y diff; no reportar que se verifico nuevamente toda la
app por haber escrito estas reglas. Las metricas de velocidad necesitan baseline,
misma maquina/red/datos y numero de requests antes/despues, no solo una captura.

## Cierre Y PR

Explicar cambios visibles y pruebas ejecutadas, con limites pendientes de hardware
o correo real. Separar: implementado, probado, subido a PR, aprobado, instalado.
Actualizar el PR abierto adecuado sin duplicarlo; si ya esta fusionado, crear una
rama nueva desde la base vigente. No fusionar/desplegar por haber terminado QA.

El PR resume el contrato cambiado, movil/PC, estados y permisos, pruebas y riesgos.
Tokens/reglas nuevas se actualizan en MASTER; los hechos verificados se guardan en
memoria enfocada, no copiando todo el historial. No publicar bases, capturas
operativas, Excel, logos privados, destinatarios configurados o credenciales.
