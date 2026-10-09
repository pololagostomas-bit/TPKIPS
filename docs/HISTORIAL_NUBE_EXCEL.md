# Estado e historial de Excel en nube

Panel administrativo en Mi perfil > Herramientas y opciones > Cortes Excel >
Microsoft 365. Dos vistas: Estado e Historial. El modulo se entrega tambien
mediante infrastructure/cloud-overlay/Dockerfile para la variante manual,
sin sustituir su app ni su base operativa.

## Estado

La autorizacion guardada solo acredita que existe una cuenta/cache en el
servidor. Acceso comprobado requiere una descarga reciente y posterior a la
ultima autorizacion. No se consulta Graph al refrescar el panel: se leen los
resultados del servidor. Una nueva autorizacion requiere otra comprobacion.

Cada fuente distingue ultima comprobacion, consulta/importacion correcta,
ultima actualizacion efectiva y fecha del cambio en Microsoft. Sin cambios
actualiza la comprobacion, pero no la actualizacion efectiva ni genera otro
corte. Error conserva las fechas y el corte de la ultima carga correcta.
Una descarga correcta con Excel invalido acredita acceso Microsoft, no carga
correcta. Un HTTP403 puede ser permisos o politicas de TI: no cerrar la sesion
ni afirmar que la cuenta vencio solo por ese resultado.

El proceso automatico registra actividad y proxima revision prevista. Falta de
actividad y consultas antiguas se senalan como tales, sin afirmar que el proceso
esta muerto. Sin autorizacion registra Bloqueado, sin intentar descargar.
Un reinicio con una revision sin terminar registra Interrumpido; no certifica
si se habia confirmado alguna transaccion antes del reinicio. La siguiente
comprobacion verifica el hash/corte con las reglas existentes.

## Historial

Cada comprobacion terminada registra fuente, archivo, resultado, fecha/hora,
origen automatico o solicitado, intento forzado, duracion y motivo/accion.
Cuando existe, muestra fecha del corte solicitado, huella y referencia al
registro data_imports; cantidad de filas solo si el importador la informa.
No almacenar el contenido del Excel, URL privada, tokens, respuesta OAuth/Graph
ni errores de parser que puedan incluir celdas. Diagnosticos por codigos
controlados, no analizando mensajes de Microsoft.

Filtros por fuente/resultado y cursor por ID para navegar sin duplicar filas
si llegan comprobaciones nuevas. Solo administrador, incluso ante headers de
rol falsificados. GET/HEAD para historial; ninguna accion en esa consulta.

Retencion: hasta 30 dias y como maximo los ultimos 10000 registros por programa,
el limite que se alcance primero. Purga solo cloud_sync_history; no borrar cortes
data_imports, recepciones, auditoria, cuentas ni estados operativos. Bases del
lector y manual separadas: la misma fuente tiene una carga por cada programa.
Historial comienza al instalar esta version. No inventar eventos antiguos a
partir del ultimo estado; las fechas nuevas faltantes se muestran Sin registro.

## Despliegue y verificacion

Nuevo PR y aprobacion/fusion del propietario antes de instalar. Completar la
variante manual por separado; el agente actual solo despliega lector. No tocar
autorizaciones, direcciones de correo, fuentes, stock Power BI pendiente ni OV
manual para agregar este historial. No activar los reportes OC ni reiniciar los
servicios si no hay autorizacion explicita para ese despliegue.

Pruebas sinteticas: tests/test_cloud_history.py y test_cloud_connection.py;
no certifican un acceso o carga nueva al Excel empresarial real.

Fuente de diagnosticos HTTP: https://learn.microsoft.com/en-us/graph/errors
