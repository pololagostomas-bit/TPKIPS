"""Validate an already mapped physical per-bin stock result before storage.

Input quantities must be the stock of each bin, never a warehouse total
repeated across bins. The API/mapping boundary is responsible for that fact.
No source discovery, credentials, database writes or default warehouse here.
"""
import math

from backend.services.daily_operations import item_key


def normalize_rows(rows):
    """Return warehouse01 SKU totals and positive bins, in deterministic order.

    Identical repeated bins are idempotent; conflicting repeats reject the
    entire result. Empty results cannot clear a previous valid snapshot without
    a separate, explicitly verified empty-source contract.
    """
    items = {}
    for row in rows:
        if not isinstance(row, dict) or not {'warehouse', 'item_code', 'location', 'quantity'} <= row.keys():
            raise ValueError('El stock no tiene las columnas verificadas.')
        if str(row['warehouse']).strip() not in {'1', '01'}:
            continue
        code = str(row['item_code'] or '').strip()
        key = item_key(code)
        if not key:
            raise ValueError('El stock contiene un articulo sin codigo.')
        location = str(row['location'] or '').strip().upper()
        raw = row['quantity']
        try:
            amount = float(raw)
        except (ValueError, TypeError, OverflowError):
            raise ValueError('El stock contiene una cantidad no valida.') from None
        if isinstance(raw, bool) or not math.isfinite(amount):
            raise ValueError('El stock contiene una cantidad no valida.')
        item = items.setdefault(code.upper(), {'item_code': code, 'item_key':key, 'bins': {}})
        item['item_code'] = min(item['item_code'], code)
        if location in item['bins'] and item['bins'][location] != amount:
            raise ValueError('Hay cantidades diferentes para el mismo articulo y ubicacion.')
        item['bins'][location] = amount
    if not items:
        raise ValueError('No se obtuvo un corte completo del almacen 01.')
    result = []
    for _, item in sorted(items.items()):
        key=item['item_key']
        locations = sorted(({'location': location, 'quantity': amount}
            for location, amount in item['bins'].items() if location and amount > 0),
            key=lambda value: (-value['quantity'], value['location']))
        total = sum(max(0.0, amount) for amount in item['bins'].values())
        if not math.isfinite(total):
            raise ValueError('El total de stock no es valido.')
        result.append({'item_key': key, 'item_code': item['item_code'], 'quantity': total,
            'default_location': locations[0]['location'] if locations else '',
            'locations': locations})
    return result
