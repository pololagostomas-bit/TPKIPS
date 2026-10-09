"""Descarga de cortes Excel desde SharePoint/OneDrive mediante Microsoft Graph.

La importación sigue siendo responsabilidad de ``import_daily_excel``. Este
módulo solo autentica, descarga los archivos configurados y devuelve sus bytes.
La carga manual continúa disponible como respaldo.
"""

import base64
import os
from pathlib import Path

import requests
from backend.services import cloud_auth


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SOURCE_CONFIG = {
    "dispatch": ("GRAPH_SHARE_URL_DISPATCH", "OV y stock SAP.xlsx"),
    "stock": ("GRAPH_SHARE_URL_STOCK", "Stock de almacén.xlsx"),
    "importation": ("GRAPH_SHARE_URL_IMPORTATION", "IMPORTACIÓN DE REPUESTOS.xlsx"),
    "accounting": ("GRAPH_SHARE_URL_ACCOUNTING", "Facturas de reserva EM.xlsx"),
}


class CloudExcelError(ValueError):
    """Error visible y accionable para la sincronización desde Graph."""

    def __init__(self, message, code='cloud_error'):
        super().__init__(message)
        self.code = code


def configured_sources():
    """Devuelve solo las fuentes con URL configurada, en orden operativo."""
    sources = []
    for source_type, (setting_name, default_name) in SOURCE_CONFIG.items():
        if source_type == 'dispatch' and os.getenv('WMS_CLOUD_DISPATCH_MODE', 'cloud') == 'manual':
            continue
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


def _access_token():
    try:
        return cloud_auth.access_token()
    except cloud_auth.CloudAuthError as error:
        raise CloudExcelError(str(error), error.code) from error


def _graph_get(url, headers, **kwargs):
    try:
        response = requests.get(url, headers=headers, timeout=120, **kwargs)
    except requests.RequestException as error:
        raise CloudExcelError("No se pudo conectar con Microsoft Graph. Revisa la conexion.", 'network') from error
    if response.status_code >= 400:
        code = {401: 'authorization_required', 403: 'forbidden', 404: 'file_missing',
                410: 'file_missing', 429: 'throttled'}.get(response.status_code,
                'microsoft_unavailable' if response.status_code >= 500 else 'cloud_error')
        raise CloudExcelError(f"Microsoft Graph respondio HTTP {response.status_code}. Revisa autorizacion y permisos del archivo.", code)
    return response


def download_cloud_excels(force=False, sources=None):
    """Descarga los cortes configurados y devuelve bytes listos para importar."""
    sources = configured_sources() if sources is None else sources
    if not sources:
        raise CloudExcelError(
            "No hay archivos configurados. Define al menos una URL GRAPH_SHARE_URL_*.", 'configuration'
        )
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    downloaded = []
    for source in sources:
        share_id = _encode_share_url(source["share_url"])
        response = _graph_get(f"{GRAPH_ROOT}/shares/{share_id}/driveItem", headers,
            params={'$select': 'id,name,parentReference,size,lastModifiedDateTime'})
        try:
            item = response.json()
            if not isinstance(item, dict):
                raise ValueError('Invalid metadata')
        except ValueError as error:
            raise CloudExcelError('Microsoft no devolvio los datos esperados del archivo.', 'cloud_error') from error
        drive_id = (item.get("parentReference") or {}).get("driveId")
        item_id = item.get("id")
        if not drive_id or not item_id:
            raise CloudExcelError(f"Graph no devolvió driveId/itemId para {source['source_type']}", 'file_missing')
        if not str(item.get('name', '')).lower().endswith('.xlsx'):
            raise CloudExcelError('La fuente configurada no es un archivo Excel .xlsx.', 'file_format')
        if item.get('size', 0) > 50 * 1024 * 1024:
            raise CloudExcelError('El archivo supera el limite de 50 MB.', 'file_format')
        content = _graph_get(
            f"{GRAPH_ROOT}/drives/{drive_id}/items/{item_id}/content",
            headers,
            allow_redirects=True,
        ).content
        if not content:
            raise CloudExcelError(f"El archivo {item.get('name') or source['source_type']} está vacío", 'file_format')
        downloaded.append({
            **source,
            "filename": Path(item.get("name") or source["filename"]).name,
            "content": content,
            "item_name": item.get("name") or source["filename"],
            "item_id": item_id,
            "drive_id": drive_id,
            "modified_at": item.get('lastModifiedDateTime'),
            "forced": bool(force),
        })
    return downloaded
