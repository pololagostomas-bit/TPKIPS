# Correcciones De NP Y Conteo Parcial

Solo WMS con lector. El conteo de NP y la recepcion fisica de bultos son
procesos distintos; corregir un NP nunca cambia los paquetes DHL.

## Correccion Administrativa

En Inicio de conteo, el administrador puede usar Corregir NP, seleccionar el
pedido y marcar No recibido en esta entrega. La accion exige una lectura
existente, atencion explicita, motivo, confirmacion y cantidad previa vigente.
Un trabajador no puede invocarla ni reactivar por edicion una correccion del
administrador. Para modificar una atencion avanzada debe reabrirse primero.

La cantidad de esa atencion pasa a cero y queda pendiente para otra llegada.
Se conserva el plan original, la lectura original y el historial; no se borra
el pedido ni se inventa un nuevo escaneo. El reintento tardio del lector devuelve
la cantidad ya corregida, sin restablecerla. Una correccion normal del
administrador puede restaurar una cantidad positiva tras la comprobacion fisica.

El servidor comprueba la cantidad anterior bajo reserva de escritura; si cambio,
rechaza la correccion para que se revise nuevamente. El cliente conserva motivo
y borradores ante errores, y una respuesta de otra atencion no reemplaza la vista.

## Finalizar Esta Entrega

El progreso excluye los NP corregidos a cero: nueve recibidos de diez mantienen
9/10 y muestran el faltante por separado, aunque exista una lectura historica.
Los pedidos de distinta OV/IP no se fusionan al corregir uno.

Finalizar conteo de esta entrega reutiliza el conteo parcial existente. Confirma
los NP ausentes y lleva solamente esa atencion a EM. Tambien funciona si todos
los faltantes ya estaban regularizados: no exige inventar una nueva lectura.
No permite declarar un conteo parcial sin un NP positivo leido, omitir pedidos
sin resolver, modificar bultos, cerrar toda la BL o confirmar una transferencia
SAP. EM, ubicacion, validacion y transferencia conservan sus propias validaciones.

Reabrir directamente Inicio de conteo conserva cantidades cero, parciales y
excedentes registrados. Volver explicitamente a Zona de recepcion conserva el
comportamiento de reinicio de conteo ya existente. El valor total por defecto
se usa al inicializar un conteo nuevo, no para sobrescribir una correccion al
reabrirlo.

Publicar este codigo no instala una version ni ejecuta regularizaciones sobre
registros operativos. Los datos reales requieren respaldo y auditoria separados.

## Confirmacion Sonora Del Lector

Inicio de conteo y la recepcion del camion usan el mismo aviso local: un tono
corto agudo para un registro confirmado y dos tonos graves para codigo ajeno,
lectura repetida, seleccion pendiente o fallo de guardado. No suena exito al
detectar el codigo ni para respuestas de otra vista; una cantidad NP cero no
suena como recibido. Las correcciones administrativas no simulan lecturas nuevas.

El lector de teclado se activa con Enter y la camara con su boton de apertura.
No hay audio al cargar la pagina ni archivos o servicios externos de sonido.
Si el navegador bloquea el audio o el equipo esta silenciado, permanecen los
avisos visuales y el escaneo sigue funcionando. Las rafagas tienen un limite
de 600 ms de audio pendiente para evitar pitidos viejos; el exceso no se reproduce
mas tarde. La comprobacion fisica de volumen y parlante requiere el equipo real.
