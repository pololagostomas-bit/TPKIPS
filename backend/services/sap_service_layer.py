"""Cliente de solo lectura para SAP Business One Service Layer.

No guarda credenciales. Configúralas como variables de entorno en Azure Key Vault
o en el entorno local de pruebas.
"""

import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener


@dataclass
class SapConfig:
    base_url: str
    company_db: str
    username: str
    password: str


class SapServiceLayer:
    def __init__(self, config: SapConfig):
        self.config = config
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, method, path, payload=None):
        url = f"{self.config.base_url.rstrip('/')}/b1s/v1/{path.lstrip('/')}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        with self.opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def login(self):
        return self.request("POST", "Login", {
            "CompanyDB": self.config.company_db,
            "UserName": self.config.username,
            "Password": self.config.password,
        })

    def fetch(self, query_path):
        """Obtiene datos con una consulta OData autorizada y de solo lectura."""
        return self.request("GET", query_path)

    def logout(self):
        return self.request("POST", "Logout", {})
