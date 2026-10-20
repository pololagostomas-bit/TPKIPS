# Regularizacion Administrativa De BL

Solo WMS con lector. El administrador abre una BL y usa Regularizar o cerrar BL.
El control no depende de Mostrar ayudas ni de que la BL tenga camion o pueda
cerrarse por el flujo normal. La vista previa muestra el estado actual y los
bloqueos; los trabajadores no tienen acceso a esta revision ni a sus endpoints.

## Acciones Separadas

- Conciliar cierre validado conserva las comprobaciones documentales/fisicas
  existentes: no convierte una FR/EM de cabecera en evidencia de toda la BL.
- Retirar registro de prueba solo admite un registro sin lineas de origen,
  documentos contables o trabajo fisico real. Lo deja cerrado como REGISTRO DE
  PRUEBA RETIRADO, conservando el historial; no lo llama atendido ni lo elimina.
- Cerrar BL administrativamente es una excepcion confirmada del administrador.
  Cierra la BL y sus atenciones abiertas como CIERRE ADMINISTRATIVO. No confirma
  transferencia SAP, validez de FR/EM ni ubicacion fisica y mantiene sus datos.
- Cerrar solo esta entrega afecta exclusivamente la atencion seleccionada. La
  BL queda abierta y no se modifican cantidades ni el trabajo de otras entregas.

Antes de cerrar una entrega parcial, el administrador debe revisar su conteo y
corregir el NP no recibido a cero con motivo. Los valores predefinidos no son
lecturas confirmadas. El cierre no reparte cantidades automaticamente entre
entregas ni corrige duplicados por suposicion. Reabrir y Corregir NP conservan
sus propios permisos y reglas; los bultos DHL siguen siendo independientes.

## Protecciones

Cada accion requiere motivo, confirmacion y escribir la BL completa. Los cierres
excepcionales requieren reconocer que no equivalen a verificacion SAP/documental.
Se valida un token de la vista previa bajo reserva de escritura. Si otra persona
o un corte cambia los datos, se rechaza el formulario desactualizado para revisar
nuevamente; un reintento del mismo cierre no duplica la auditoria.

Las llegadas de camion aun en proceso se resuelven en su control propio, no se
cancelan silenciosamente. Enlaces de transferencia pendientes del alcance cerrado
se revocan; una confirmacion SAP existente no se inventa ni se borra. Cantidades,
lecturas, bultos, recibos, referencias, stock e historial se preservan.

El historial distingue los cierres administrativos de una terminacion operativa.
Las importaciones no deben reabrirlos ni convertir el cierre de una sola atencion
en cierre automatico de toda la BL. Para corregir una IP documental, debe seguirse
corrigiendo su fuente o implementarse una equivalencia explicita auditada: este
modulo no une referencias P/IP por semejanza ni modifica el Excel.

Una llegada ordinaria enviada desde una pestaña antigua tampoco puede reabrir
una BL con cierre administrativo o retirada de prueba. Primero debe usarse la
reapertura administrativa explicita con motivo; las entregas parciales normales
mantienen su flujo independiente.

Publicar el codigo no ejecuta cierres sobre BL reales. Aprobacion/fusion e
instalacion siguen separadas. El cierre administrativo es trazable, no una
certificacion de que el trabajo fisico o SAP fueron completados.
