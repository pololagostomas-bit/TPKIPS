"""Master closure never closes an unfinished partial attention."""
from backend.services import reception


def closure_check(connection, shipment_id, *, allow_documentary=False):
    shipment = connection.execute('SELECT * FROM reception_shipments WHERE id=?',
                                  (shipment_id,)).fetchone()
    if not shipment:
        raise ValueError('No existe la BL seleccionada')
    if reception._accounting_status_for_shipment(
            connection, shipment_id, shipment, include_unreceived_ips=True) != 'EM REGISTRADA':
        return False, 'FR/EM pendientes para alguna IP'
    attentions = reception._attention_rows(connection, shipment_id)
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
        if connection.execute('''SELECT 1 FROM reception_lines
            WHERE shipment_id=? AND expected_qty>received_qty+0.000000001 LIMIT 1''',
                              (shipment_id,)).fetchone():
            return False, 'UNIDADES POR ATENDER'
        return True, 'Todas las atenciones cerradas y FR/EM completas'
    if not allow_documentary:
        return False, 'HISTORICO POR CONFIRMAR'
    origin = connection.execute('''SELECT event_type FROM reception_history
        WHERE shipment_id=? AND field_name='app_status' AND new_value='ARRIBADO'
        ORDER BY id DESC LIMIT 1''', (shipment_id,)).fetchone()
    if shipment['app_status'] != 'PROGRAMADO' and not (
            shipment['app_status']=='ARRIBADO' and origin and origin[0]=='IMPORTACION EXCEL'):
        return False, 'ETAPA OPERATIVA POR REVISAR'
    if not reception._shipment_expected_ips(connection, shipment_id, shipment):
        return False, 'IP DOCUMENTALES POR IDENTIFICAR'
    return True, 'Historico documental confirmado; sin inventar recepcion fisica'


def master_state(connection, shipment_id):
    attentions = reception._attention_rows(connection, shipment_id)
    pending = [a for a in attentions if a['app_status']!='CERRADO']
    if pending:
        return pending[0]['app_status'], pending[0]['condition_status']
    eligible, reason = closure_check(connection, shipment_id)
    return ('CERRADO', 'COMPLETADO') if eligible else ('ARRIBADO', reason)


def reconcile_closure(connection, shipment_id, data, username, role):
    reception.require_reception_access(role)
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede conciliar el cierre de una BL')
    reason = str(data.get('reason') or '').strip()
    if data.get('confirmed') is not True or len(reason)<8:
        raise ValueError('Confirma el cierre e indica un motivo de al menos 8 caracteres')
    shipment = reception._get_reception_shipment(connection, shipment_id, username, role)
    if shipment['app_status']=='CERRADO':
        return reception.reception_detail(connection, shipment_id, role)
    eligible, detail = closure_check(connection, shipment_id,
                                    allow_documentary=data.get('historical') is True)
    if not eligible:
        raise ValueError('No se puede cerrar esta BL: '+detail)
    connection.execute('''UPDATE reception_shipments SET app_status='CERRADO',
        condition_status='COMPLETADO', updated_at=? WHERE id=?''',
                       (reception.reception_now(), shipment_id))
    reception._write_history(connection, shipment_id, 'CONCILIACION CIERRE', 'app_status',
                             shipment['app_status'], 'CERRADO', username, reason+'; '+detail)
    return reception.reception_detail(connection, shipment_id, role)
