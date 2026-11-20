# Clasificación de rotación en etiquetas de Recepción

El administrador carga el Excel desde **Cortes Excel → Clasificación de rotación**.
Usa una sola hoja con las columnas **NP**, **Descripción** y **Clasificación**.
Puede cambiar el orden de las columnas. Se admiten los encabezados SAP equivalentes.

El NP identifica el repuesto. Se ignoran mayúsculas y espacios al inicio/final;
se conservan guiones, puntos, prefijos y ceros. Guarda los NP como texto para
conservar su identidad. Los formatos numéricos simples de ceros también se respetan.
La descripción sirve de referencia; no reemplaza la descripción de la recepción.

La carga actualiza los NP incluidos y conserva los ausentes. Dos filas del mismo
NP con clasificaciones distintas rechazan todo el archivo. Un archivo vacío,
incorrecto o anterior al corte vigente no reemplaza el catálogo.
El historial de cargas conserva fecha, responsable, nombre y hash del archivo.
El catálogo queda en la base privada del servidor y sobrevive a los cortes de stock.

Todas las etiquetas de Recepción consultan el catálogo vigente al imprimir:
Inicio de conteo, EM, atenciones actuales y reimpresiones. La etiqueta añade
**Clasificación de rotación** junto a los datos de recepción. Un NP sin coincidencia
indica **Sin clasificación**. El programa no calcula ni inventa la categoría.

Se mantienen cantidad, OV, cliente, BL, ubicación, marca y Data Matrix con el NP exacto.
Las etiquetas masivas de stock/inventario conservan su formato independiente.
La carga no cambia existencias, conteos, estados, documentos, asignaciones ni conexiones.
