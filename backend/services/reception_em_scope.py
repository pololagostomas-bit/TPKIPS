"""Explicitly associate an existing unassigned EM with one received attention."""


def bind_existing(connection, shipment_id, attention_id, data, username, role):
    from backend.services import reception as r
    if role != 'ADMINISTRADOR':
        raise PermissionError('Solo el administrador puede vincular una EM existente a una entrega')
    if type(attention_id) is not int or attention_id <= 0:
        raise ValueError('Selecciona la entrega que corresponde a la EM')
    if any(type(data.get(key)) is not int or data[key] <= 0 for key in ('id', 'em_id')):
        raise ValueError('Selecciona una referencia y una EM existentes')
    reason = str(data.get('reason') or '').strip()
    if data.get('confirmed') is not True or not 8 <= len(reason) <= 500:
        raise ValueError('Confirma la entrega e indica un motivo de 8 a 500 caracteres')
    if not connection.in_transaction:
        connection.execute('BEGIN IMMEDIATE')
    else:
        connection.execute('UPDATE reception_shipments SET id=id WHERE 0')
    shipment = r._get_reception_shipment(connection, shipment_id, username, role)
    attention = r._location_context(connection, shipment, attention_id)
    if attention['app_status'] not in {'EM', 'UBICACION', 'VALIDACION', 'SOLICITUD TRANSFERENCIA'}:
        raise PermissionError('Vincula la EM en una entrega abierta desde la etapa EM')
    reference = connection.execute('SELECT * FROM reception_accounting_refs WHERE id=? AND shipment_id=?',
                                   (data['id'], shipment_id)).fetchone()
    entry = connection.execute('SELECT * FROM reception_accounting_ems WHERE id=? AND accounting_ref_id=?',
                               (data['em_id'], data['id'])).fetchone()
    if not reference or not entry or not str(reference['fr_number'] or '').strip():
        raise ValueError('La EM no pertenece a la FR seleccionada de esta BL')
    ips = r._ip_tokens(reference['ip_reference'])
    ip = str(data.get('ip_key') or '').strip()
    if ip not in ips or not r._accounting_ref_has_received_sku(connection, shipment_id, reference, ip, attention_id):
        raise ValueError('La IP no tiene NP recibidos en esta entrega')
    if entry['ip_reference_key'] and entry['ip_reference_key'] != ip:
        raise ValueError('La EM corresponde a otra IP de esta FR')
    values = r._accounting_em_tokens(data.get('em_number'))
    if len(values) != 1 or values != r._accounting_em_tokens(entry['em_number']):
        raise ValueError('La EM cambió; actualiza la BL antes de vincularla')
    value = values[0]
    if value not in r._accounting_em_tokens(reference['em_number']):
        raise ValueError('La EM ya no está declarada en la referencia actual')
    # Numeric separator aliases must not bind the same document to two arrivals.
    for other in connection.execute('''SELECT e.*,f.ip_reference,f.fr_number FROM reception_accounting_ems e
            JOIN reception_accounting_refs f ON f.id=e.accounting_ref_id
            WHERE f.shipment_id=? AND e.attention_id IS NOT NULL''', (shipment_id,)):
        if (r._normalized_identifier(other['fr_number']) == r._normalized_identifier(reference['fr_number'])
                and ip in r._ip_tokens(other['ip_reference'])
                and value in r._accounting_em_tokens(other['em_number'])
                and int(other['attention_id']) != attention_id):
            raise ValueError('Esta EM ya está vinculada a otra entrega; requiere revisión administrativa')
    if entry['attention_id'] is not None:
        if int(entry['attention_id']) == attention_id:
            return False
        raise ValueError('Esta EM ya corresponde a otra entrega')
    connection.execute('UPDATE reception_accounting_ems SET attention_id=? WHERE id=? AND attention_id IS NULL',
                       (attention_id, entry['id']))
    r._write_history(connection, shipment_id, 'VINCULO EM', f"em:{entry['id']}:attention_id", '', attention_id,
                     username, f"EM {value}; entrega {attention['sequence_no']}: {reason}")
    return True
