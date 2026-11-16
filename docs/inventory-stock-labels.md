# Etiquetas de stock

Inventario incorpora una pestaña Etiquetas de stock para los mismos roles que ya consultan el catálogo. El usuario carga Excel/CSV o pega una lista. Se prepara una etiqueta por cada fila con NP, conservando los repetidos y el orden del listado. La columna Cantidad no genera copias adicionales. Se conservan ceros y separadores; no se equiparan códigos diferentes.

La etiqueta reutiliza el perfil de Inventario del motor de recepción: TSC TE200 4 × 3 horizontal, marca y logos privados disponibles, NP exacto en Data Matrix ECC200, descripción y ubicación por defecto. No lleva OV, BL, cliente ni cantidad de recepción. Sin stock se conserva el recuadro de ubicación vacío.

El catálogo del servidor aporta los datos. La carga no importa existencias ni modifica registros. Los NP no encontrados se muestran aparte y no generan etiquetas; las demás filas mantienen su orden relativo. La preparación verifica hasta 100 filas por solicitud y solo mantiene una solicitud activa. Las búsquedas de catálogo se reutilizan, pero cada fila se conserva al preparar y actualizar la impresión. La impresión utiliza lotes consecutivos de hasta 500 etiquetas, incluyendo repetidos. El operador puede elegir cualquier lote; abrirlo no afirma que ya se imprimió.

La pantalla conserva la carga durante errores, muestra progreso y permite cancelar la preparación. La lista visible se limita a 50 resultados; los contadores y lotes incluyen todos los resultados. En celular se apilan los controles y la tabla se convierte en filas legibles. Se mantienen controles de 44 px y mensajes accesibles.

Límites: archivo de 4 MB, 20.000 filas con NP, 50.000 filas totales y 30 columnas. Los archivos requieren un encabezado NP, SKU o Código de artículo. Las fórmulas en la columna NP se rechazan. Los logos siguen fuera del repositorio público.
