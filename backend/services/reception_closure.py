"""Master closure never closes an unfinished partial attention."""
from backend.services import reception

RETIRED_HISTORY = 'Historico documental con atenciones de prueba retiradas'


def _retired_history_confirmed(connection, shipment_id, attentions):
    """An annulment alone is not proof that a receipt was a retired pilot."""
    receipts = connection.execute('SELECT * FROM reception_receipts WHERE shipment_id=?',
                                  (shipment_id,)).fetchall()
    by_id = {row['id']: row for row in receipts}
    if not receipts or any(not row['receipt_id'] or row['receipt_id'] not in by_id
                           for row in attentions):
        return False
    for receipt in receipts:
        if not str(receipt['truck_guide'] or '').strip():
            return False
        guide = reception._truck_guide_header(connection, receipt['truck_guide'], create_if_missing=False)
        if (not guide or guide['guide_status'] != 'CANCELADA' or not guide['archived_at']
                or 'prueba' not in str(guide['archive_reason'] or '').casefold()):
            return False
    return True


def closure_check(connection, shipment_id, *, allow_documentary=False):
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?',
                                  (shipment_id,)).fetchone()
    if not shipment:
        raise ValueError('No existe la BL seleccionada')
    all_attentions = reception._attention_rows(connection, shipment_id)
    if any(row['condition_status'] == 'CIERRE ADMINISTRATIVO'
           for row in all_attentions
           if not str(row['condition_status'] or '').startswith('ANULADA')):
        return False, 'ATENCION CON CIERRE ADMINISTRATIVO POR CONCILIAR'
    if reception._accounting_status_for_shipment(
            connection, shipment_id, shipment, include_unreceived_ips=True) != 'EM REGISTRADA':
        return False, 'FR/EM pendientes para alguna IP'
    attentions = [row for row in all_attentions
                  if not str(row['condition_status'] or '').startswith('ANULADA')]
    retired = [row for row in all_attentions
               if str(row['condition_status'] or '').startswith('ANULADA')]
    if any(row['app_status'] != 'CERRADO' for row in retired):
        return False, 'ANULACION INCONSISTENTE'
    if any(row['app_status'] != 'CERRADO' for row in attentions):
        return False, 'OTRA ATENCION PENDIENTE'
    if connection.execute('''SELECT 1 FROM reception_truck_bl_manifest m
        JOIN reception_truck_guides g ON lower(g.guide_code)=lower(m.truck_guide)
        WHERE m.shipment_id=? AND COALESCE(m.operational_active,1)=1
          AND g.guide_status<>'CANCELADA'
          AND (g.is_confirmed=1 OR g.source_type='ESTIMACION_PRUEBA')
          AND NOT EXISTS (SELECT 1 FROM reception_truck_bl_arrivals a
               WHERE a.shipment_id=m.shipment_id AND lower(a.truck_guide)=lower(m.truck_guide)
                 AND a.received_packages>0) LIMIT 1''', (shipment_id,)).fetchone():
        return False, 'CAMION POR ARRIBAR'
    positive_receipts = connection.execute('''SELECT 1 FROM reception_receipts
        WHERE shipment_id=? AND received_packages>0 LIMIT 1''', (shipment_id,)).fetchone()
    positive_arrivals = connection.execute('''SELECT 1 FROM reception_truck_bl_arrivals
        WHERE shipment_id=? AND received_packages>0 LIMIT 1''', (shipment_id,)).fetchone()
    if connection.execute('''SELECT 1 FROM reception_receipts r
        WHERE r.shipment_id=? AND r.received_packages>0
          AND NOT EXISTS (SELECT 1 FROM reception_attentions a WHERE a.receipt_id=r.id)
        LIMIT 1''', (shipment_id,)).fetchone():
        return False, 'LLEGADA SIN ATENCION'
    if attentions or positive_receipts or positive_arrivals or float(shipment['received_packages'] or 0)>0:
        if reception.truck_bl_package_balance(connection, shipment_id)['pending_packages'] > 0:
            return False, 'SALDO POR ARRIBAR'
        if not attentions or all(str(a['condition_status'] or '').startswith('ANULADA') for a in attentions):
            return False, 'ATENCIONES POR REVISAR'
        from backend.services.reception_source_bl import excluded_ids
        excluded=excluded_ids(connection,shipment_id)
        if any(row['id'] not in excluded for row in connection.execute('''SELECT id FROM reception_lines
            WHERE shipment_id=? AND expected_qty>received_qty+0.000000001''',(shipment_id,))):
            return False, 'UNIDADES POR ATENDER'
        return True, 'Todas las atenciones cerradas y FR/EM completas'
    if not allow_documentary:
        return False, 'HISTORICO POR CONFIRMAR'
    if connection.execute('''SELECT 1 FROM reception_truck_bl_manifest
        WHERE shipment_id=? AND COALESCE(operational_active,1)=1 LIMIT 1''',
                          (shipment_id,)).fetchone():
        return False, 'CAMION ASOCIADO POR REVISAR'
    if connection.execute('''SELECT 1 FROM reception_lines WHERE shipment_id=?
        AND received_qty<>0 LIMIT 1''', (shipment_id,)).fetchone():
        return False, 'UNIDADES REGISTRADAS POR REVISAR'
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='inventory_lots'").fetchone():
        if connection.execute('SELECT 1 FROM inventory_lots WHERE reception_shipment_id=? LIMIT 1',
                              (shipment_id,)).fetchone():
            return False, 'LOTES OPERATIVOS POR REVISAR'
    origin = connection.execute('''SELECT event_type FROM reception_history
        WHERE shipment_id=? AND field_name='app_status' AND new_value='ARRIBADO'
        ORDER BY id DESC LIMIT 1''', (shipment_id,)).fetchone()
    if shipment['app_status'] != 'PROGRAMADO' and not (
            shipment['app_status']=='ARRIBADO' and origin and origin[0]=='IMPORTACION EXCEL'):
        return False, 'ETAPA OPERATIVA POR REVISAR'
    if not reception._shipment_expected_ips(connection, shipment_id, shipment):
        return False, 'IP DOCUMENTALES POR IDENTIFICAR'
    if retired:
        if not _retired_history_confirmed(connection, shipment_id, retired):
            return False, 'ANULACIONES SIN PROCEDENCIA DE PRUEBA'
        return True, RETIRED_HISTORY
    return True, 'Historico documental confirmado; sin inventar recepcion fisica'


def master_state(connection, shipment_id):
    attentions = reception._attention_rows(connection, shipment_id)
    pending = [a for a in attentions if a['app_status']!='CERRADO']
    if pending:
        return pending[0]['app_status'], pending[0]['condition_status']
    eligible, reason = closure_check(connection, shipment_id)
    return ('CERRADO', 'COMPLETADO') if eligible else ('ARRIBADO', reason)


def reconcile_closure(connection, shipment_id, data, username, role, *, return_detail=True):
    reception.require_reception_access(role)
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede conciliar el cierre de una BL')
    reason = str(data.get('reason') or '').strip()
    if data.get('confirmed') is not True or len(reason)<8:
        raise ValueError('Confirma el cierre e indica un motivo de al menos 8 caracteres')
    shipment = reception._get_reception_shipment(connection, shipment_id, username, role)
    if shipment['app_status']=='CERRADO':
        return (reception.reception_detail(connection, shipment_id, role) if return_detail else
                {'id': shipment_id, 'app_status': 'CERRADO', 'unchanged': True})
    eligible, detail = closure_check(connection, shipment_id,
                                    allow_documentary=data.get('historical') is True)
    if not eligible:
        raise ValueError('No se puede cerrar esta BL: '+detail)
    if detail == RETIRED_HISTORY:
        for field in ('first_arrival_at', 'completed_arrival_at'):
            if shipment[field]:
                reception._write_history(connection, shipment_id, 'CONCILIACION CIERRE', field,
                    shipment[field], '', username, reason+'; fecha de prueba retirada')
        connection.execute('''UPDATE reception_shipments SET first_arrival_at=NULL,
            completed_arrival_at=NULL,physical_initialized=1,system_quantities_initialized=1
            WHERE id=?''', (shipment_id,))
    connection.execute('''UPDATE reception_shipments SET app_status='CERRADO',
        condition_status='COMPLETADO', updated_at=? WHERE id=?''',
                       (reception.reception_now(), shipment_id))
    reception._write_history(connection, shipment_id, 'CONCILIACION CIERRE', 'app_status',
                             shipment['app_status'], 'CERRADO', username, reason+'; '+detail)
    return (reception.reception_detail(connection, shipment_id, role) if return_detail else
            {'id': shipment_id, 'app_status': 'CERRADO', 'unchanged': False})
