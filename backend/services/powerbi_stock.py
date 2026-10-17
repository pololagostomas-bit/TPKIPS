"""Local capability diagnostics, not a Power BI stock connector.

Never acquire tokens, discover datasets or query a model from a status read.
Report/embed identifiers and a working Graph connection prove no BI access.
"""
import os
from uuid import UUID


def _identifier_state(name):
    value = os.getenv(name, '').strip()
    if not value:
        return 'missing'
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError):
        return 'invalid'
    return 'declared'


def status():
    configuration = {key: _identifier_state(name) for key, name in (
        ('report', 'POWERBI_STOCK_REPORT_ID'),
        ('workspace', 'POWERBI_STOCK_WORKSPACE_ID'),
        ('dataset', 'POWERBI_STOCK_DATASET_ID'))}
    return {
        'state': 'not_implemented',
        'connector_implemented': False,
        'stock_connected': False,
        'configuration': configuration,
        'required_warehouse': '01',
        'warehouse_filter_verified': False,
        'model_mapping': 'unverified',
        'api_access': 'unverified',
        'refresh_schedule': {'state': 'unknown'},
        'last_refresh_at': None,
        'action': 'Pendiente de espacio de trabajo, modelo, permisos de Power BI '
                  'y validacion de stock exclusivo del almacen 01.',
    }
