"""Explicit physical package totals for maritime BLs without unique labels."""
from backend.services import reception


def set_package_count(connection, truck_guide, shipment_id, quantity, expected_version, username, role):
    reception.require_reception_access(role)
    if role not in {'ADMINISTRADOR','ASISTENTE_RECEPCION'}:
        raise PermissionError('Solo el administrador o asistente puede registrar bultos por cantidad.')
    if any(isinstance(value,bool) for value in (quantity,expected_version,shipment_id)):
        raise ValueError('Cantidad y version deben ser enteros.')
    count=reception._truck_package_count(quantity,'Bultos recibidos',allow_zero=True)
    version=reception._truck_package_count(expected_version,'Version del registro',allow_zero=True)
    if count > 2147483647:
        raise ValueError('La cantidad de bultos supera el rango permitido.')
    sid=reception._truck_package_count(shipment_id,'BL seleccionada')
    if sid > 9223372036854775807:
        raise ValueError('Selecciona una BL valida.')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    guide=str(truck_guide or '').strip()
    header=reception._truck_guide_header(connection,guide,create_if_missing=False)
    if not header or not int(header['scanner_enabled'] or 0):
        raise ValueError('Selecciona un camion con lector.')
    if reception._truck_guide_status(header) not in {'PENDIENTE','EN_CURSO'}:
        raise ValueError('La llegada termino; el administrador debe reabrirla antes de corregir.')
    shipment=connection.execute('SELECT * FROM reception_shipments WHERE id=?',(sid,)).fetchone()
    if not shipment or shipment['transport_type']!='MARITIMO' or shipment['app_status']=='CERRADO':
        raise ValueError('El ingreso por cantidad solo aplica a una BL maritima abierta.')
    manifest=connection.execute('''SELECT * FROM reception_truck_bl_manifest
        WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND operational_active=1''',(guide,sid)).fetchone()
    if not manifest:
        raise ValueError('Selecciona primero la BL de este camion.')
    reception._require_scanned_bl_available(connection,guide,shipment)
    if connection.execute('''SELECT 1 FROM reception_truck_package_scans WHERE
        lower(truck_guide)=lower(?) AND shipment_id=? AND scan_status='ACTIVO' LIMIT 1''',(guide,sid)).fetchone():
        raise ValueError('Esta BL ya tiene lecturas de bultos; no se pueden mezclar con cantidad manual.')
    previous=int(manifest['planned_packages']) if manifest['package_count_mode']=='QUANTITY' else 0
    current_version=int(manifest['package_count_version'])
    if previous==count:
        return {'count':count,'version':current_version,'duplicate':True,'shipment_id':sid}
    if version!=current_version:
        raise ValueError('Otro usuario cambio los bultos. Revisa el total guardado antes de volver a guardar.')
    connection.execute('SAVEPOINT maritime_count')
    try:
        connection.execute('''UPDATE reception_truck_bl_manifest SET package_count_mode='QUANTITY',
            planned_packages=?,package_count_version=package_count_version+1,updated_at=?
            WHERE lower(truck_guide)=lower(?) AND shipment_id=?''',(count,reception.reception_now(),guide,sid))
        connection.execute('''UPDATE reception_truck_guides SET planned_packages=(SELECT COALESCE(SUM(planned_packages),0)
            FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND operational_active=1),updated_at=?
            WHERE lower(guide_code)=lower(?)''',(guide,reception.reception_now(),guide))
        reception._write_history(connection,sid,'CONTEO BULTOS',f'guia:{guide}:cantidad',previous,count,username,
            'Cantidad fisica declarada para BL maritima; sin codigos individuales ni verificacion DHL')
        connection.execute('RELEASE SAVEPOINT maritime_count')
    except Exception:
        connection.execute('ROLLBACK TO SAVEPOINT maritime_count')
        connection.execute('RELEASE SAVEPOINT maritime_count')
        raise
    return {'count':count,'version':current_version+1,'duplicate':False,'shipment_id':sid}


def reset_count(connection, guide, sid, username, reason):
    row=connection.execute('''SELECT planned_packages FROM reception_truck_bl_manifest
        WHERE lower(truck_guide)=lower(?) AND shipment_id=? AND package_count_mode='QUANTITY' ''',(guide,sid)).fetchone()
    if not row or not row['planned_packages']:
        return
    connection.execute('''UPDATE reception_truck_bl_manifest SET planned_packages=0,
        package_count_version=package_count_version+1,updated_at=? WHERE lower(truck_guide)=lower(?) AND shipment_id=?''',
        (reception.reception_now(),guide,sid))
    connection.execute('''UPDATE reception_truck_guides SET planned_packages=(SELECT COALESCE(SUM(planned_packages),0)
        FROM reception_truck_bl_manifest WHERE lower(truck_guide)=lower(?) AND operational_active=1),updated_at=?
        WHERE lower(guide_code)=lower(?)''',(guide,reception.reception_now(),guide))
    reception._write_history(connection,sid,'CONTEO BULTOS',f'guia:{guide}:cantidad',row['planned_packages'],0,username,reason)
