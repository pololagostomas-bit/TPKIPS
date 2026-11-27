# Corrección de una IP en Facturas

Una corrección de IP no crea otra referencia cuando el corte y el WMS permiten
identificar de forma única la misma BL, FR y EM. La IP anterior debe haber
desaparecido del corte y de las líneas de Importaciones de esa BL. La IP nueva
debe estar en esas líneas. Cada referencia debe tener una sola IP y una sola EM.
Se requiere el mismo archivo de origen. No se identifica por número de fila,
posición del Excel, prefijo de IP ni fecha de actualización.

La corrección conserva el ID de la referencia anterior y de su EM manual,
su usuario, fecha y entrega. Cambia la IP documental y la clave del origen.
Una auditoría conserva el estado previo, incluido el de una posible referencia
duplicada generada por el importador anterior. Solo se retira ese duplicado
cuando carece de trabajo manual, entrega vinculada, auditoría o cobertura propia.
Las referencias de respaldo del costeo se remapean al ID conservado.
No se cambian cantidades, lecturas, ubicaciones, llegada ni confirmaciones SAP.

Si ambas IP siguen en el corte o en Importaciones, se conservan separadas.
También se conservan los casos ambiguos, varias IP/EM, documentos distintos,
otro archivo, coberturas explícitas o duplicados con trabajo propio. Requieren
revisión administrativa; esta regla no elige por similitud ni borra históricos.

La revisión del importador usa el mecanismo existente para reprocesar una vez
el mismo corte contable, aunque su contenido no haya cambiado. No crea otra
carga de datos ni modifica la frecuencia de sincronización.
