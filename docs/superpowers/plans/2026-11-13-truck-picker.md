# Camiones: cabecera fija y selector con búsqueda

Base main e288a7b28f51ec834571c4aa55e9c51959566af4. PR67 sigue independiente.
Solo lector; sin instalación, servicios, datos operativos ni aplicación manual.

Contrato: administrador/asistente, cola de camiones. Una cabecera conserva
búsqueda/selector, Nuevo camión, historial y paginación. Solo las filas se
desplazan. Un combobox con lupa filtra resultados del servidor por guía o sus
referencias existentes. Seleccionar usa la clave interna y las guardas actuales.
Escribir no cambia el camión de trabajo. Teclado/ratón/táctil, Escape, vacío,
error y respuesta tardía conservan el contexto; sin nuevas dependencias.

- [x] Reproducir y fijar pruebas de selección conservada/respuesta tardía.
- [x] Integrar combobox sobre búsqueda/select existentes y dar scroll solo a filas.
- [x] Probar móvil/PC/altura corta, filtros/páginas, teclado y rechazo de cambio de contexto.
- [x] Ejecutar suite: 1279 pruebas, 13 omitidas en Windows; sin fallos.

Navegador: cinco tamaños entre 320 y 1366 px, incluyendo horizontal de 384 px
de alto. Búsqueda vacía, error 503, reintento, selección con teclado/ratón,
Escape/Tab, contexto conservado y controles inmóviles tras desplazar filas.
Asistente conserva acceso; auxiliar conserva su restricción de camiones.
Sin prueba en un dispositivo Android físico ni certificación WCAG completa.
El detector estático no resuelve las rutas /assets del servidor y muestra
avisos de estilos existentes; se contrastó el resultado real en navegador.

La revisión externa, publicación y CI se registran en la evidencia local
outputs/WMS_TRUCK_PICKER_20261113, fuera del código operativo.
