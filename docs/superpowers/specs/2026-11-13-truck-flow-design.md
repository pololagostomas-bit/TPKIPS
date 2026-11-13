# Camiones: recepción física y vista operativa

El propietario pide simplificar recepción para asistentes/auxiliares, priorizar
camiones y mantener disponibles los controles administrativos. Una sola interfaz
adaptable, con Python/SQLite/HTML/CSS/JS y el MASTER vigente.

## Decisiones de implementación

- Un borrador tiene clave interna estable, sin número operativo. Se asigna
  CAMION-AAMMDD-NN al confirmar una llegada positiva. Cancelar o abrir vacío no
  consume número. La confirmación repetida conserva el número. No renumerar
  históricos ni cambiar claves relacionadas.
- Mostrar primero bultos de ESTE camión, BL y marca. Total DHL, recibidos previos
  y pendiente global quedan en detalles. Un parcial positivo puede confirmarse;
  nunca completar por anticipado los bultos esperados.
- Lista de BL visible durante el escaneo; revisar una BL no cambia el destino
  de otra lectura. Las lecturas esperadas siguen restringidas al administrador.
- Flujo: registrar bultos, revisar/confirmar llegada, ubicación temporal y
  continuar recepción. Historial consultable con contexto y cantidades.
- Ubicación temporal general y excepciones por BL aceptan lector Data Matrix,
  cámara y entrada manual mediante los helpers existentes.
- Simplificar navegación y consultas del operario sin quitar etapas necesarias,
  errores, historial o validación API. Mantener permisos existentes y herramientas
  administrativas. No introducir permisos por esconder botones.
- Indicador parcial: BL única con varias entregas positivas, o entrega positiva
  aún incompleta frente a un total documentado. Exponer cantidad de entregas y
  días, sin contar borradores/cancelaciones ni confundir líneas con BL. El total
  conocido se conserva en la llegada para no depender de la caché del proveedor.

La fecha se interpreta en el horario operativo existente. Es una decisión
conservadora mantener códigos SCAN históricos, aunque la interfaz diga Camión.
No se añade un total manual ficticio de bultos para este camión: las lecturas
aceptadas y la confirmación física determinan lo que llegó.

## Aceptación

Dos borradores cancelados no consumen el 01. Dos confirmaciones concurrentes
obtienen números distintos. Reintento y reapertura conservan identidad.
Dos bultos de tres se confirman sin exigir el tercero; otra llegada atiende
el saldo, con historial y contador único. Escanear ubicación general distribuye
solo lo recibido y conserva excepciones. Roles, error/reintento, foco, 320/393px,
PC, horizontal y texto ampliado deben probarse con datos sintéticos.

Solo lector. No despliegue, servicios, SQL operativo, correo, Excel ni aplicación
manual. Revisión externa del candidato exacto y PR antes de una instalación.
