# Recepción coherente: adaptación funcional de Odoo

Base: main0bbb1de11cf16a9e9fc35a8e35b15a49cdc943e7, incluye PR65.
Alcance autorizado: reforzar toda recepción del lector. Sin reemplazar el WMS,
modificar SAP, instalar versiones ni tocar datos o servicios operativos.

Referencia: estudio funcional Odoo19/REA del12/11, ADAPTACION_WMS/CATALOGO_FUNCIONAL.
Reutilizar estados y transacciones existentes; no copiar módulos ni crear un ERP.
El modo es Operate: completar la tarea en celular/PC con el MASTER vigente.

## Diseño decidido para este refuerzo

- Cabecera de BL y entrega actual, con estado físico separado del documental.
  FR pendiente permanece visible y no simula llegada, retroceso o disponibilidad.
- Una tarea activa y acción principal existente. Etapas anteriores consultables
  mediante el selector existente, sin habilitar escritura histórica al operario.
- Accesos relacionados a entregas, documentos, historial y administración.
  Secciones cerradas inicialmente; al abrir conservan contexto y eventos.
  Documentos reutiliza relaciones FR/EM/IP actuales. No se envían correos al abrir.
- Administración separada y accesible por rol; no depende de mostrar ayudas.
- Guardado compartido de recepción impide doble envío, muestra espera, conserva
  campos ante error y rechaza aplicar una respuesta a otra BL/atención.
  Sin reintentos automáticos de escrituras ni cambios a permisos/transiciones API.
- Una sola interfaz adaptable. 320/393px, PC, horizontal y reflujo200%; foco,
  controles táctiles y mensajes de error accesibles con UI/UX Pro Max.

Se conservan claves físicas estables, saldo de parciales, conteo predefinido,
ubicación sugerida/temporal/final separadas, cobertura EM/costeo por entrega,
reversión administrativa auditada, etiquetas y retorno a camión.

## Verificación y límites

Probar todos los estados del expediente, operario/admin, FR pendiente/completa,
doble clic, error de guardado y respuesta tardía tras cambiar de entrega.
Comprobar conteo, ubicación, validación/transferencia y consultas relacionadas.
REA se utiliza como análisis estático acotado; su grafo no certifica el negocio.
Revisión Gemini exacta y CI antes de entregar el PR; aceptación física posterior.
