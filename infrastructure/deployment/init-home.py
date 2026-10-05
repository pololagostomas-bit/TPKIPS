"""Create private bootstrap configuration without overwriting existing secrets."""
import argparse
import os
from pathlib import Path
import re
import secrets


def initialize(destination, email, username="admin.almacen", port=8086):
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email):
        raise ValueError("Indica un correo individual valido; no se aceptan comodines")
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
        raise ValueError("Usuario no valido")
    if not 1024 <= port <= 65535:
        raise ValueError("Puerto fuera de rango")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"TRITON_BOOTSTRAP_ADMIN_USERNAME={username}\n"
        f"TRITON_BOOTSTRAP_ADMIN_PASSWORD={secrets.token_urlsafe(32)}\n"
        f"TRITON_HOST_PORT={port}\n"
        f"WMS_ALLOWED_EMAIL={email}\n"
    )
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--username", default="admin.almacen")
    parser.add_argument("--port", type=int, default=8086)
    args = parser.parse_args()
    path = initialize(args.destination, args.email, args.username, args.port)
    print(f"Configuracion privada creada en {path}. La clave no se imprime ni se sube a Git.")
