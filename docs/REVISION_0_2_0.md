# Revisión local 0.2.0 — 6 de septiembre de 2026

## Alcance realizado

- Inicio con Waitress en Windows/Linux; imagen no privilegiada, healthcheck y logs rotativos.
- Identidades locales, contraseñas derivadas, sesiones revocables y permisos servidor.
- Administración de usuarios y bandeja de correo con reintento manual auditable.
- Copias SQLite online verificadas y restauración separada con cuarentena de correos.
- Volumen Docker externo obligatorio para evitar crear otra base durante una actualización.
- Reportes por fecha de finalización, ventanas nocturnas 16:00 Lima y metas lunes-viernes.
- Fecha de creación con HoraCrea_OV; la fecha de llegada de importaciones nunca sustituye la de la OV.
- Recepción no genera stock en etapa 1. Lotes avanzados ocultos si están deshabilitados.
- Controles compartidos de 44 px, acciones administrativas agrupadas en móvil y etiquetas de formulario.

## Verificación

Las pruebas se ejecutan sobre bases separadas, no sobre triton.db. Se probaron
autenticación, permisos, persistencia, importación HTTP, recepción, reasignación,
reinicio, cierre SAP, compromisos aéreos, stock compartido, reportes, correos con
transporte simulado y restauración. El navegador validó inicio de sesión, creación
y búsqueda de una BL ficticia, reapertura y lista móvil. Se inspeccionó recepción
en 375, 768 y 1280 px y se comprobaron controles principales de 44 px.

La base operativa estaba en uso fuera de estas pruebas; su hash cambió entre turnos.
No se utiliza esa comparación como prueba de inmutabilidad ni se revierte el archivo.

## Revisión de animaciones — emil-design-eng, solo revisión

No se modifican animaciones como resultado de esta auditoría.

| Antes | Después propuesto (no aplicado) | Por qué |
|---|---|---|
| Avisos con opacity/transform de 250 ms | Mantener duración; respetar reduced-motion | Respuesta breve sin retrasar tareas repetidas. |
| Cola móvil con desplazamiento de 250 ms | Mantener para orientar; desactivar con reduced-motion | El movimiento ayuda a distinguir lista y detalle. |
| Desplazamiento smooth en búsquedas | Usar desplazamiento instantáneo con movimiento reducido | Evitar movimiento forzado durante búsquedas frecuentes. |
| Barras de reporte de 300 ms | Sin animación durante cambios repetidos de filtro | La lectura precisa importa más que la transición. |

Impeccable y gpt-tasteskill no se encontraron instalados en la sesión revisada;
no se afirma haber ejecutado esos comandos. Los ajustes visuales fueron directos.

## Pendientes externos antes de declarar producción

1. Marino/TI: probar Docker Compose en Linux con copia de la base y volumen correcto;
   verificar permisos UID 10001, reinicio y recuperación. Docker no está disponible aquí.
2. TI: autorizar Microsoft Graph Mail.Send y la cuenta remitente; probar un destinatario
   controlado antes de activar envíos operativos. ENVIADO significa aceptado, no leído.
3. Realizar una jornada piloto con los usuarios del almacén y validar los indicadores.
4. Confirmar hora de creación en el Excel: una fecha sin hora no permite un corte exacto.
5. Verificar todos los formularios poblados de Despacho en celulares reales. La revisión
   de recepción no sustituye la aceptación de ambos módulos por los trabajadores.

No se ha actualizado el servidor ni conectado SAP. Las etapas 2/3 continúan fuera
del alcance operativo de esta revisión.
