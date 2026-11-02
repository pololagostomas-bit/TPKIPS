# Asociación vigente de NP y ajuste de etiquetas

Un pedido solo se ofrece en una BL cuando el corte de Importaciones lo asigna explícitamente a esa BL. Compartir NP, OV u OC con otro pedido no acredita la asociación. La fila actual puede cambiar de IP, quedar sin guía o pasar a otra BL: esto no debe trasladar lecturas ni cantidades entre pedidos.

## Fuente y trabajo físico

El importador conserva una proyección del último archivo por hoja, incluyendo filas de NP sin guía. No crea recepciones nuevas para esas filas. Se comprueba NP exacto, hoja, BL y anclas IP/OC/OV. La posición de Excel solo identifica la fila del corte; no relaciona pedidos históricos. En instalaciones anteriores, el mapa vigente de OVs aporta evidencia positiva para detectar una guía retirada antes de la primera nueva importación; no es una fuente completa para Stock/sin OV.

Una fila retirada o reasignada conserva su ID, plan, lecturas e historial, pero queda fuera del listado de conteo/ubicación y las etiquetas. No se puede escanear ni guardar como recibida para esa BL. La pantalla informa de la asociación por revisar; no oculta este requisito por la preferencia de ayudas.

Si existen cantidades positivas guardadas, el avance exige regularización administrativa. En Inicio de conteo el administrador puede «Retirar cantidad de esta entrega»: confirma cantidad anterior, cero y motivo de 8 a 500 caracteres. La API valida rol, pertenencia y estado vigente dentro de la transacción. Conserva la lectura y el plan de esa atención, actualiza acumulados y audita, sin tocar bultos ni enviar un correo adicional. Las otras entregas no cambian. Un NP retirado de la BL no se convierte por ese hecho en un pendiente de llegada de esa misma BL. Documentos/fechas de costeo no evitan esta revisión.

Sin evidencia de un nuevo corte no se presume que una línea manual o heredada fue retirada. Un error de base distinto de una tabla heredada inexistente no convierte una denegación en permiso.

## Etiquetas

Se conserva el formato TE200 4 × 3 pulgadas, Data Matrix con NP exacto, marca, OV, descripción, cliente, BL, cantidad y ubicación. En inventario se conserva su variante sin datos del pedido.

- El código de artículo ocupa una sola línea. Su fuente se ajusta independientemente cuando es largo, sin cambiar el texto ni el Data Matrix.
- El cliente ocupa como máximo dos líneas y reduce su fuente cuando hace falta. No se usan puntos suspensivos ni recortes silenciosos.
- Se conserva el tamaño físico del sticker y el espacio de marca/ubicación. Si el texto no cabe dentro del mínimo legible, la impresión permanece bloqueada con el aviso existente.

La impresión vuelve a consultar la BL/atención guardada y excluye asociaciones no vigentes; no utiliza una lista local antigua para imprimir. Cambios comunes probados también en etiquetas de inventario y varias dimensiones de pantalla.

## Entrega

Solo lector, mediante PR revisable; no modifica datos operativos ni instala por terminar las pruebas. La regularización de una cantidad real es una acción separada del administrador, con confirmación/motivo. Nunca publicar el Excel, detalles del caso real, credenciales o logos privados.
