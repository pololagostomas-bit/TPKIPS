"""Explicit single-piece fallback. All tracking reads use the retained local cache."""
import time

from backend.services import dhl_tracking as dhl, reception


WRITERS = {'ADMINISTRADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'}


def _context(connection, truck_guide, shipment_id, role):
    reception.require_reception_access(role)
    if role not in WRITERS:
        raise PermissionError('Tu rol no puede registrar bultos recibidos.')
    guide = str(truck_guide or '').strip()
    header = reception._truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header['scanner_enabled'] or 0):
        raise ValueError('Selecciona un camion con lector.')
    try:
        sid = int(shipment_id)
    except (TypeError, ValueError):
        raise ValueError('Elige primero la BL de recepcion.') from None
    shipment = connection.execute('''SELECT s.* FROM reception_shipments s
        JOIN reception_truck_bl_manifest m ON m.shipment_id=s.id
        WHERE s.id=? AND lower(m.truck_guide)=lower(?)
          AND COALESCE(m.operational_active,1)=1''', (sid, guide)).fetchone()
    if not shipment:
        raise ValueError('La BL no pertenece al manifiesto activo de este camion.')
    return guide, header, shipment


def cached_pieces(connection, truck_guide, shipment_id, role, query='', page=1, now=None):
    """GET contract: 50 rows, no enqueue, writes, network, or inferred receipt."""
    guide, header, shipment = _context(connection, truck_guide, shipment_id, role)
    now = time.time() if now is None else now
    status = dhl.shipment_status(connection, shipment['id'], now=now)
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        raise ValueError('La pagina de piezas no es valida.') from None
    query = str(query or '').strip()
    if len(query) > 120:
        raise ValueError('La busqueda admite hasta 120 caracteres.')
    needle = dhl.piece_code(query)
    payload = {'truck_guide': guide, 'shipment_id': shipment['id'], 'bl_awb': shipment['bl_awb'],
               'items': [], 'page': 1, 'page_size': 50, 'total': 0, 'pages': 1,
               'state': status['state'], 'applicable': status['applicable'],
               'enabled': status['enabled'], 'checked_at': status['checked_at'],
               'list_complete': status.get('piece_list_complete', False),
               'expected': status['total_pieces'], 'received': status.get('matched_pieces', 0),
               'missing': status.get('pending_pieces'), 'error': status['error']}
    if not status['enabled'] or not status['applicable'] or status['checked_at'] is None:
        return payload
    awb = dhl.awb_code(shipment['bl_awb'])
    codes = sorted({dhl.piece_code(row[0]) for row in connection.execute(
        'SELECT piece_id FROM dhl_tracking_pieces WHERE awb=?', (awb,))})
    codes = [code for code in codes if not needle or needle in code]
    payload['total'] = len(codes)
    payload['pages'] = max(1, (len(codes) + 49) // 50)
    payload['page'] = min(page, payload['pages'])
    start = (payload['page'] - 1) * 50
    writable = reception._truck_guide_status(header) in {'PENDIENTE', 'EN_CURSO'}
    writable = writable and str(shipment['app_status'] or '').upper() != 'CERRADO'
    for code in codes[start:start + 50]:
        item = {'code': code, 'state': 'missing', 'can_select': bool(writable), 'detail': ''}
        try:
            owner = dhl.piece_owner(connection, code, now=now)
            duplicate = reception._package_scan_for_code(connection, code)
            if owner != awb:
                raise ValueError('La relacion DHL requiere revision del administrador.')
            if duplicate:
                if int(duplicate['shipment_id']) != int(shipment['id']):
                    raise ValueError('Codigo registrado en otra BL; requiere revision del administrador.')
                item.update(state='received', can_select=False,
                            detail='Este camion' if duplicate['truck_guide'].casefold() == guide.casefold()
                            else 'Arribo anterior')
        except ValueError as error:
            item.update(state='blocked', can_select=False, detail=str(error))
        payload['items'].append(item)
    return payload


def register_piece(connection, truck_guide, shipment_id, package_code, username, role,
                   source=None, reason=None, confirmed=False):
    """POST contract: caller owns BEGIN IMMEDIATE; retries reuse the physical code."""
    guide, header, shipment = _context(connection, truck_guide, shipment_id, role)
    if confirmed is not True:
        raise ValueError('Confirma la identidad y presencia fisica de este bulto exacto.')
    if source not in {'cache', 'known_code'}:
        raise ValueError('Elige una pieza del cache o ingresa su codigo unico conocido.')
    reason = str(reason or '').strip()
    if not 8 <= len(reason) <= 500:
        raise ValueError('Indica la evidencia de identificacion (8 a 500 caracteres).')
    raw, normalized = reception._normalize_scan_code(package_code, 'codigo unico de bulto')
    normalized = dhl.piece_code(normalized)
    if reception._truck_guide_status(header) not in {'PENDIENTE', 'EN_CURSO'}:
        raise ValueError('La llegada de este camion ya esta cerrada.')
    # Durable same-context retries remain safe even after cache expiry/disablement.
    duplicate = reception._package_scan_for_code(connection, normalized)
    same = duplicate and int(duplicate['shipment_id']) == int(shipment['id']) and (
        duplicate['truck_guide'].casefold() == guide.casefold())
    if source == 'cache' and not same:
        status = dhl.shipment_status(connection, shipment['id'])
        if not status['enabled'] or not status['applicable'] or status['checked_at'] is None:
            raise ValueError('El cache DHL no esta vigente. Verifica un codigo unico conocido o solicita revision.')
        if dhl.piece_owner(connection, normalized) != dhl.awb_code(shipment['bl_awb']):
            raise ValueError('La pieza elegida ya no pertenece al cache vigente de esta BL.')
    dhl.verify_piece(connection, shipment['id'], normalized)
    connection.execute('SAVEPOINT reception_manual_package')
    try:
        result = reception.scan_truck_package(connection, guide, shipment['id'], raw, username, role)
        if result.get('accepted'):
            reception._write_history(connection, shipment['id'], 'REGISTRO MANUAL BULTO',
                'guia:' + guide + ':paquete:' + normalized, '', raw, username,
                'Origen: ' + source + '; identidad y presencia confirmadas; evidencia: ' + reason)
        connection.execute('RELEASE SAVEPOINT reception_manual_package')
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT reception_manual_package')
        connection.execute('RELEASE SAVEPOINT reception_manual_package')
        raise
    return {**result, 'shipment_id': shipment['id'], 'bl_awb': shipment['bl_awb'],
            'manual': True, 'source': source}
