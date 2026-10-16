# Ubicaciones Y Capacidad

Solo para el lector mantenido. Modulo /locations, accesible desde Inventario,
el selector de modulo y Perfil > Herramientas y opciones. La app manual y los
servicios actuales no se modifican por esta entrega.

## Contrato

| Aspecto | Regla |
| --- | --- |
| Usuarios | Roles actuales de Inventario consultan y etiquetan. Solo ADMINISTRADOR carga/corrige el maestro y consulta historial. |
| Entidad | Posicion fisica por codigo inmutable y revision del maestro; no modifica BL, camion, atencion ni stock. |
| Accion principal | Admin revisa el archivo y confirma Guardar en servidor con motivo; el operador consulta/selecciona e imprime solo tras preparar una vista previa valida. |
| Fuente de capacidad | Maestro fisico cargado por el usuario, no ubicaciones deducidas del stock ni generadas por rango. Sin maestro, no inventar capacidad. |
| Fuente de ocupacion | Ubicacion por defecto de filas positivas del corte vigente SAP, almacen 01. No es inventario detallado por bin ni medicion fisica. |
| Accion admin | Revisar carga y Guardar en servidor son pasos separados. Motivo, digest del contenido normalizado y revision protegen la confirmacion. |
| Correccion | Edicion de zona/pasillo/rack/nivel/caja/estado con motivo, control de revision e historial anterior/nuevo/actor/fecha. No altera mercaderia ni movimientos. |
| Impresion | Seleccion de ubicaciones registradas no dadas de baja, codigos exactos, copias y vista previa manual. No autoimprimir. |
| Movil / PC | Una fuente de datos y permisos. En celular, registros apilados; filtros/seleccion/paginacion antes de la lista. Controles de 48px. |
| Errores | Sin datos actuales se retiran indicadores anteriores; se permite consultar nuevamente. Nunca mostrar informacion vieja como vigente. |
| Retorno | El selector conserva acceso a los modulos autorizados; salir con un archivo o motivo sin guardar exige confirmacion. La consulta fallida conserva filtros, pero no habilita impresion con datos viejos. |

## Carga En El Servidor

El administrador elige Excel .xlsx o CSV UTF-8 desde el app. Columna requerida:
Ubicacion o Posicion de ubicacion (con o sin tildes), en las primeras20 filas.
Opcionales: Almacen, Pasillo, Rack, Nivel, Caja, Zona y Estado. Se conserva el
codigo completo sin reconstruirlo desde las columnas; cajas vacias no se
inventan. Las dimensiones numericas mantienen al menos dos digitos. El modulo
corresponde al almacen01 y rechaza otros almacenes en una carga.

Puede indicar la hoja Excel o pegar codigos uno por linea. Sin hoja explicita,
busca un unico maestro por su encabezado, no toma la pestaña activa de etiquetas
o las auxiliares de impresion. Si hay varios candidatos, pide elegir la hoja.
Hasta4MB y100000 ubicaciones por carga; Excel acotado a30 columnas y24MB de
expansion ZIP. Encabezados y codigos duplicados se rechazan antes de guardar.
No ejecutar formulas, macros ni enlaces del documento; las formulas en los
campos del maestro se rechazan. Las hojas auxiliares no se importan.

Lectura/validacion del archivo antes de abrir la transaccion de escritura; el
guardado vuelve a comprobar digest y revision con bloqueo exclusivo. Las
consultas permanecen paginadas de50 en50, no se envian todas las posiciones al
celular. Cargar un maestro grande no obliga a renderizar una lista gigante.

Los registros normalizados y su historial quedan en SQLite persistente del
servidor, disponibles entre sesiones; no en localStorage o GitHub. No se archiva
el archivo original como otra fuente: se conserva el nombre como procedencia del
historial. Cargar un maestro no crea ni mueve stock.

Carga aditiva/actualizacion: nunca elimina filas ausentes. Una carga de solo
codigos conserva estado y todas las dimensiones existentes, y no reactiva bloqueadas. Estados:
HABILITADA, BLOQUEADA y BAJA. BAJA se conserva como historial y no es imprimible;
las bloqueadas mantienen su identificador fisico y si son imprimibles.

## Indicadores

- Instaladas = HABILITADA + BLOQUEADA; excluye BAJA.
- Denominador utilizable = HABILITADA.
- Con stock informado = ubicaciones habilitadas que aparecen como ubicacion por
  defecto en el corte vigente, con cantidad positiva; contar una posicion una vez.
- Ocupacion referencial = con stock informado / habilitadas. Sin corte o sin
  denominador, mostrar no disponible, nunca un porcentaje inventado.
- No afirmar que una posicion sin stock informado esta fisicamente libre.
  No mide volumen, peso, bultos ni unidades de capacidad por posicion.
- Stock sin ubicacion, ubicaciones no registradas o de baja con stock y bloqueadas
  con stock son advertencias visibles, no ayudas ocultables. No dividir una celda
  de ubicacion multiple ni atribuirle cantidades sin evidencia.

Consultas de 50 registros con filtros antes de paginar y resumen global separado.
La lectura usa una transaccion coherente. La proxima consulta refleja el corte
actualizado en la misma base; no agrega workers, solicitudes BI/DHL ni cron.

## Etiqueta De Rack

Confirmado por el usuario: dos etiquetas de 101.6 x 38.1mm en el papel existente
101.6 x 76.2mm (4x3 pulgadas), corte central. Contenido: logo privado Triton en
negro, codigo humano grande y Data Matrix ECC200 con solo la ubicacion exacta.
Mantiene ceros y separadores; sin SKU, OV, cliente o BL. No modifica los stickers
de productos, conteo o EM. La conversion monocroma se hace al renderizar, sin
publicar ni reemplazar el logo privado original.

Hasta 200 etiquetas por lote, 1-10 copias por posicion dentro del mismo limite.
Generacion local con el motor existente, cediendo el hilo cada 10 etiquetas.
Dos codigos independientes por hoja; lote impar deja una mitad en blanco.
Verificar logo/fuentes/geometria antes de habilitar imprimir; no recortar texto.
Una vista previa o PDF no certifica impresion real en TSC TE200 ni lector fisico.

## Verificacion

Pruebas especificas: test_location_capacity.py y test_location_capacity_http.py.
Fixture local support_location_capacity_server.py, sin DB/productivo ni workers.
location_capacity_browser.cjs cubre nueve tamanos, carga persistente, historial,
permisos, consulta AIM, errores/reintento, navegacion desde Inventario/Recepcion,
lotes impares/copies y 200 etiquetas. verify_location_label_pdf.py comprueba
papel 4x3, cada mitad a203dpi, payload exacto y logo monocromo.
Puede recibir como tercer argumento un maestro privado para validar su carga
completa en el fixture desechable. Ese archivo nunca forma parte del repositorio.
Ante consulta fallida, se retiran metricas antiguas y se bloquea Imprimir hasta
obtener una respuesta actual valida; no basta conservar la seleccion anterior.

Evidencia QA local privada en qa/location-capacity. No publicar maestros reales,
logos, PDF, capturas, Excel ni bases. Fusion, instalacion, carga del maestro real
y prueba fisica siguen siendo pasos separados que requieren autorizacion.
