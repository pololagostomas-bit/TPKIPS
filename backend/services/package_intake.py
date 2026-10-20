"""Package-first truck intake using local, unambiguous BL ownership."""
from backend.services import dhl_tracking, reception
from backend.services.truck_entry import resolve_entered_bl


class IdentificationError(ValueError):
    def __init__(self, message, code, can_identify=False):
        super().__init__(message)
        self.code = code
        self.can_identify = can_identify


def _find_bl(connection, awb):
    rows = connection.execute("""SELECT * FROM reception_shipments WHERE
        upper(replace(replace(trim(bl_awb),' ',''),'-',''))=?""", (awb,)).fetchall()
    if not rows:
        raise IdentificationError('La guia del bulto no existe en Importaciones. Actualiza el corte.', 'missing_bl')
    if len(rows) != 1:
        raise IdentificationError('Hay mas de una BL para esta guia. Requiere revision del administrador.', 'ambiguous_bl')
    return rows[0]


def scan_piece(connection, truck_guide, package_code, username, role,
               bl_code=None, confirm_unverified=False):
    reception.require_reception_access(role)
    if role not in {'ADMINISTRADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'}:
        raise PermissionError('Tu rol no puede registrar bultos recibidos.')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    guide = str(truck_guide or '').strip()
    header = reception._truck_guide_header(connection, guide, create_if_missing=False)
    if not header or not int(header['scanner_enabled'] or 0):
        raise ValueError('Selecciona un camion con lector.')
    if reception._truck_guide_status(header) not in {'PENDIENTE', 'EN_CURSO'}:
        raise ValueError('La llegada de este camion ya esta cerrada.')
    raw, normalized = reception._normalize_scan_code(package_code, 'codigo unico de bulto')
    normalized = dhl_tracking.piece_code(normalized)
    if connection.execute("""SELECT 1 FROM reception_shipments WHERE
        upper(replace(replace(trim(bl_awb),' ',''),'-',''))=? LIMIT 1""", (normalized.replace('-', ''),)).fetchone():
        raise IdentificationError('Ese codigo es una BL/AWB. Escanea el codigo unico del bulto.', 'awb_not_piece')

    # Durable physical scans still deduplicate if the external cache has expired.
    duplicate = reception._package_scan_for_code(connection, normalized)
    owner = dhl_tracking.piece_owner(connection, normalized)
    if duplicate:
        if str(duplicate['truck_guide']).casefold() != guide.casefold():
            raise IdentificationError('Bulto ya registrado en BL ' + duplicate['bl_awb']
                + ', camion ' + duplicate['truck_guide'] + '.', 'other_truck')
        shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?',
                                      (duplicate['shipment_id'],)).fetchone()
        if owner and dhl_tracking.awb_code(shipment['bl_awb']) != owner:
            raise IdentificationError('La relacion DHL cambio; el administrador debe revisar este bulto.', 'ownership_changed')
    elif owner:
        shipment = _find_bl(connection, owner)
    elif bl_code and confirm_unverified is True:
        try:
            shipment, _ = resolve_entered_bl(connection, bl_code, username, role)
        except ValueError as error:
            raise IdentificationError(str(error), 'manual_bl', can_identify=role == 'ADMINISTRADOR') from None
    else:
        raise IdentificationError('Codigo sin coincidencia DHL vigente. No se registro el bulto. '
                                  'Revisa la etiqueta o solicita revision del administrador.',
                                  'unknown_piece', can_identify=role == 'ADMINISTRADOR')
    if bl_code and confirm_unverified is True:
        selected, _ = resolve_entered_bl(connection, bl_code, username, role)
        if selected['id'] != shipment['id']:
            raise IdentificationError('El bulto corresponde a la BL ' + shipment['bl_awb'] + '.', 'wrong_bl')
    if str(shipment['app_status'] or '').upper() == 'CERRADO':
        raise IdentificationError('La BL ' + shipment['bl_awb'] + ' esta cerrada. Requiere revision del administrador.', 'closed_bl')
    sid = int(shipment['id'])
    try:
        reception._require_scanned_bl_available(connection, guide, shipment)
    except ValueError as error:
        raise IdentificationError(str(error), 'other_truck') from None

    # Failure after linking must not leave an empty association, even for service callers.
    connection.execute('SAVEPOINT package_intake')
    try:
        linked = reception._attach_scanned_truck_bl(connection, guide, shipment, shipment['bl_awb'], username)
        result = reception.scan_truck_package(connection, guide, sid, raw, username, role)
        if not owner and not duplicate:
            reception._write_history(connection, sid, 'IDENTIFICACION BULTO', 'guia:' + guide + ':paquete:' + normalized,
                                     '', raw, username, 'BL confirmada explicitamente; sin verificacion DHL')
        connection.execute('RELEASE SAVEPOINT package_intake')
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT package_intake')
        connection.execute('RELEASE SAVEPOINT package_intake')
        raise
    return {**result, 'shipment_id':sid, 'bl_awb':shipment['bl_awb'],
            'bl_added':bool(linked.get('added')), 'identification':'physical' if duplicate else 'dhl' if owner else 'manual'}
