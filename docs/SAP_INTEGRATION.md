# Contrato de integración SAP Business One

## Objetivo

Reemplazar la carga manual del Excel por una sincronización **de solo lectura**
desde SAP Business One. SAP sigue siendo el origen de OVs y líneas; Triton
Picking conserva sus atenciones, responsables, cantidades operativas e
historial.

## Dato indispensable: identidad estable de cada línea

La aplicación actual identifica líneas del Excel por la posición física de la
fila. Esto es suficiente para el piloto, pero no para una sincronización SAP:
la posición puede cambiar entre exportaciones. Antes de activar la integración
automática, la consulta debe devolver estos dos campos:

| Campo SAP | Uso |
| --- | --- |
| `DocEntry` | Identificador interno de la OV (no visible al usuario) |
| `LineNum` | Identificador de la línea dentro de esa OV |

La clave técnica de una línea será `DocEntry:LineNum`. El número mostrado en la
app continuará siendo `DocNum`/`Número de documento`.

## Campos requeridos por cada línea abierta

| Campo funcional | Nombre SAP sugerido | Obligatorio |
| --- | --- | --- |
| OV visible | `DocNum` | Sí |
| ID interno OV | `DocEntry` | Sí |
| Línea SAP | `LineNum` | Sí |
| Cliente | `CardCode`, `CardName` | Sí |
| SKU y descripción | `ItemCode`, `ItemDescription` | Sí |
| Cantidad solicitada | `Quantity` | Sí |
| Cantidad aún abierta | `OpenQuantity` | Sí |
| Almacén | `WarehouseCode` | Sí |
| Stock disponible | consulta de inventario por almacén | Sí para validar completa/parcial |
| Fecha y destino | `DocDueDate`, dirección/forma de envío | Recomendado |
| Situación de máquina | UDF o campo del query actual | Requerido por operación |
| Tipo de atención solicitado | UDF/campo del query | Requerido por operación |
| Estado de la OV en SAP | `DocumentStatus` / estado del query | Sí |

## Lo que debe proporcionar TI/SAP

1. URL del Service Layer, por ejemplo `https://servidor:50000` (sin usuario ni
   contraseña por chat).
2. Nombre de la compañía SAP (`CompanyDB`).
3. Una cuenta técnica de **solo lectura**, almacenada en Azure Key Vault.
4. El endpoint OData o query aprobado que retorne una fila por línea abierta,
   con los campos anteriores y orden fijo por `DocEntry, LineNum`.
5. Un ejemplo anonimizado de respuesta JSON con dos OVs y al menos una OV de
   dos líneas.
6. La frecuencia requerida: por ejemplo, cada 5 o 10 minutos.

## Reglas de sincronización

1. Crear OVs nuevas y sus Atenciones 1 en estado `PENDIENTE`.
2. Actualizar solo los datos fuente de OVs aún abiertas: stock, pendiente,
   destino y líneas.
3. Nunca modificar ni borrar la foto de líneas de una atención ya creada.
4. Si SAP cierra una línea/OV, conservar sus atenciones e historial y mostrar
   el estado SAP como referencia.
5. Si cambia una línea en SAP, registrar el cambio técnico de sincronización.
6. Si SAP no responde, mantener la última información disponible y avisar al
   administrador; nunca eliminar OVs por un error de consulta.

## Seguridad

- La contraseña SAP no va en `sap.env.example`, código, Excel ni repositorio.
- Azure Key Vault entrega las variables solo al trabajo programado de sync.
- El usuario SAP no puede crear, editar ni cerrar documentos.
- La aplicación web no se conecta directamente al Service Layer desde el
  navegador.

## Siguiente entregable técnico

Con la información anterior se implementará un trabajo `sync_sap.py` que
autentica, descarga, valida la estructura, actualiza las OVs con clave
`DocEntry:LineNum`, registra el resultado y cierra la sesión. Se prueba primero
contra una compañía de pruebas, sin modificar SAP.
