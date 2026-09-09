"""Pruebas de identidad Microsoft Entra y preparación PWA/Azure."""

import base64
import json
import os

import app


class FakeHandler:
    def __init__(self, headers):
        self.headers = headers


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    original_mode = os.environ.get("TRITON_AUTH_MODE")
    try:
        os.environ["TRITON_AUTH_MODE"] = "entra"
        principal = base64.b64encode(json.dumps({
            "userDetails": "picker@triton.local",
            "userRoles": ["authenticated", "PICKER"],
        }).encode("utf-8")).decode("ascii")
        username, role = app.current_user(FakeHandler({"X-MS-CLIENT-PRINCIPAL": principal}))
        check(username == "picker@triton.local" and role == "PICKER", "Debe identificar al picker desde Entra")
        try:
            app.current_user(FakeHandler({}))
        except PermissionError:
            pass
        else:
            raise AssertionError("Entra debe rechazar solicitudes sin identidad")
        check(app.MANIFEST["display"] == "standalone", "La PWA debe ser instalable")
        check(app.MANIFEST["icons"][0]["src"] == "/icon.svg", "La PWA debe incluir un icono instalable")
        check("/api/" in app.SERVICE_WORKER, "La PWA no debe almacenar respuestas dinámicas de la API")
        check("function applyRoleInterface" in app.HTML, "La interfaz debe aplicar permisos por rol")
        check("$('importButton').hidden=!isAdmin" in app.HTML, "Solo el administrador debe ver la carga de Excel")
        check("triton-admin-welcome-seen" in app.HTML, "La bienvenida del administrador debe mostrarse una sola vez")
        check('warehouse-art"><svg viewBox="0 0 420 250"' in app.HTML, "La bienvenida debe incluir el flujo SVG")
        check('aria-label="Flujo operativo: asignar, preparar, guiar y entregar"' in app.HTML, "El SVG debe representar el flujo operativo")
        check("Atenciones por estado" in app.HTML and "status-chart" in app.HTML, "La reportería debe incluir una visualización por estado")
        check("stock_shortage_lines" in app.HTML and "statusFilter" in app.HTML, "La cola debe incluir disponibilidad y filtro por etapa")
        check("triton-mobile-navigation" in app.HTML, "La interfaz móvil debe conservar el detalle junto a la cola")
        dockerfile = open(app.ROOT / "infrastructure" / "Dockerfile", encoding="utf-8").read()
        check("TRITON_DB_PATH=/home/data/triton.db" in dockerfile, "El contenedor debe usar la ruta persistente de App Service")
        print("SEGURIDAD Y DESPLIEGUE OK: Entra, PWA y contenedor preparados.")
    finally:
        if original_mode is None:
            os.environ.pop("TRITON_AUTH_MODE", None)
        else:
            os.environ["TRITON_AUTH_MODE"] = original_mode


if __name__ == "__main__":
    main()
