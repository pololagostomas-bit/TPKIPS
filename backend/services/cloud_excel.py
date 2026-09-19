"""Descarga de cortes Excel desde SharePoint/OneDrive mediante Microsoft Graph.

La importación sigue siendo responsabilidad de ``import_daily_excel``. Este
módulo solo autentica, descarga los archivos configurados y devuelve sus bytes.
La carga manual continúa disponible como respaldo.
"""

import base64
import os
from pathlib import Path

import msal
import requests


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DEFAULT_TENANT_ID = "108ab96b-5b54-4c6f-a691-cd77954e1af1"
DEFAULT_CLIENT_ID = "2637d6cb-1bc8-4798-834e-98621684d83b"
SOURCE_CONFIG = {
    "dispatch": ("GRAPH_SHARE_URL_DISPATCH", "OV y stock SAP.xlsx"),
    "stock": ("GRAPH_SHARE_URL_STOCK", "Stock de almacén.xlsx"),
    "importation": ("GRAPH_SHARE_URL_IMPORTATION", "IMPORTACIÓN DE REPUESTOS.xlsx"),
    "accounting": ("GRAPH_SHARE_URL_ACCOUNTING", "Facturas de reserva EM.xlsx"),
}


class CloudExcelError(ValueError):
    """Error visible y accionable para la sincronización desde Graph."""


def configured_sources():
    """Devuelve solo las fuentes con URL configurada, en orden operativo."""
    sources = []
    for source_type, (setting_name, default_name) in SOURCE_CONFIG.items():
        share_url = str(os.getenv(setting_name, "")).strip()
        if share_url:
            sources.append({
                "source_type": source_type,
                "share_url": share_url,
                "filename": os.getenv(f"GRAPH_FILENAME_{source_type.upper()}", default_name),
            })
    return sources


def _encode_share_url(share_url):
    encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def _token_cache():
    cache = msal.SerializableTokenCache()
    cache_path = Path(os.getenv("GRAPH_TOKEN_CACHE_PATH", "data/msal_token_cache.bin"))
    if cache_path.exists():
        try:
            cache.deserialize(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return cache, cache_path


def _save_token_cache(cache, cache_path):
    if not cache.has_state_changed:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(cache.serialize(), encoding="utf-8")


def _access_token():
    tenant_id = os.getenv("GRAPH_TENANT_ID", DEFAULT_TENANT_ID).strip()
    client_id = os.getenv("GRAPH_CLIENT_ID", DEFAULT_CLIENT_ID).strip()
    if not tenant_id or not client_id:
        raise CloudExcelError("Falta GRAPH_TENANT_ID o GRAPH_CLIENT_ID en la configuración")
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    client_secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
    if client_secret:
        app = msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=client_secret
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
    else:
        cache, cache_path = _token_cache()
        app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)
        accounts = app.get_accounts()
        result = app.acquire_token_silent(["Files.Read"], account=accounts[0]) if accounts else None
        if not result:
            result = app.acquire_token_interactive(
                scopes=["Files.Read"], prompt="select_account"
            )
        _save_token_cache(cache, cache_path)
    token = result.get("access_token") if result else None
    if not token:
        detail = (result or {}).get("error_description") or (result or {}).get("error")
        raise CloudExcelError(f"Microsoft Graph no entregó un token: {detail or 'respuesta vacía'}")
    return token


def _graph_get(url, headers, **kwargs):
    try:
        response = requests.get(url, headers=headers, timeout=120, **kwargs)
    except requests.RequestException as error:
        raise CloudExcelError(f"No se pudo conectar con Microsoft Graph: {error}") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except ValueError:
            detail = response.text[:300]
        raise CloudExcelError(f"Microsoft Graph respondió HTTP {response.status_code}: {detail}")
    return response


def download_cloud_excels(force=False):
    """Descarga los cortes configurados y devuelve bytes listos para importar."""
    sources = configured_sources()
    if not sources:
        raise CloudExcelError(
            "No hay archivos configurados. Define al menos una URL GRAPH_SHARE_URL_*."
        )
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    downloaded = []
    for source in sources:
        share_id = _encode_share_url(source["share_url"])
        item = _graph_get(f"{GRAPH_ROOT}/shares/{share_id}/driveItem", headers).json()
        drive_id = (item.get("parentReference") or {}).get("driveId")
        item_id = item.get("id")
        if not drive_id or not item_id:
            raise CloudExcelError(f"Graph no devolvió driveId/itemId para {source['source_type']}")
        content = _graph_get(
            f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}/content",
            headers,
            allow_redirects=True,
        ).content
        if not content:
            raise CloudExcelError(f"El archivo {item.get('name') or source['source_type']} está vacío")
        downloaded.append({
            **source,
            "filename": Path(item.get("name") or source["filename"]).name,
            "content": content,
            "item_name": item.get("name") or source["filename"],
            "item_id": item_id,
            "drive_id": drive_id,
            "forced": bool(force),
        })
    return downloaded
