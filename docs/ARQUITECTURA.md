# Arquitectura de TRITON WMS Piloto

## Regla de operación

La etapa 1 usa cortes Excel manuales y SQLite. El Excel de despacho alimenta las OV y el Excel de importaciones identifica compromisos aéreos/marítimos; no reemplaza el stock global. Cada modificación operativa se registra en el historial.

## Separación actual

`backend/app.py` conserva temporalmente las rutas HTTP y el HTML de Picking para mantener el piloto estable. Los servicios de dominio se encuentran en `backend/services/`. La interfaz de Recepción está en `frontend/templates/reception.html` y sus recursos en `frontend/static/`.

Los directorios `backend/api`, `backend/database`, `backend/imports` y `frontend/components` son puntos de extracción para futuras etapas; no contienen lógica duplicada.

## Arranque

Desde esta carpeta:

```powershell
py .\app.py --host 127.0.0.1 --port 8000
```

Con Docker:

```powershell
docker compose -f .\infrastructure\docker-compose.yml up -d --build
```
