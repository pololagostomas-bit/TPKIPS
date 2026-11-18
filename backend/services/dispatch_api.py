"""Dispatch additions use the same session, stock ledger and audit as the WMS."""
from urllib.parse import urlsplit
from . import dispatch_operations as ops


def handle(app, request, payload=None):
    try:
        return _handle(app, request, payload)
    except PermissionError as error:
        request.send_json({'error': str(error)}, 403)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        request.send_json({'error': str(error)}, 400)


def _handle(app, request, payload):
    path = urlsplit(request.path).path
    username, role = app.current_user(request)
    app.require_dispatch_access(role)
    parts = path.strip('/').split('/')
    if request.command == 'GET' and path == '/api/dispatch/branches':
        with app.db() as db:
            result = {'items': [dict(row) for row in db.execute('SELECT * FROM dispatch_branches ORDER BY name')]}
    elif request.command == 'GET' and len(parts) == 5 and parts[2] == 'receipts' and parts[4] == 'evidence':
        ops._admin(role)
        with app.db() as db:
            photo = db.execute('SELECT mime_type,image_bytes FROM dispatch_receipt_evidence WHERE request_key=?', (parts[3],)).fetchone()
        if not photo: raise ValueError('No se encontró la evidencia.')
        request.send_response(200)
        request.send_header('Content-Type', photo['mime_type'])
        request.send_header('Content-Length', str(len(photo['image_bytes'])))
        request.send_header('Cache-Control', 'no-store')
        request.send_header('X-Content-Type-Options', 'nosniff')
        request.end_headers(); request.wfile.write(photo['image_bytes'])
        return
    elif request.command != 'POST':
        request.send_json({'error': 'Ruta no encontrada.'}, 404); return
    elif path == '/api/dispatch/branches':
        with app.db() as db: result = ops.save_branch(db, payload, username, role)
    elif path == '/api/dispatch/requests':
        result = ops.create_request(app, payload, username, role)
    elif len(parts) == 5 and parts[2] == 'attentions':
        aid = int(parts[3]); action = parts[4]
        if action == 'scan': result = ops.scan(app, aid, payload.get('code'), username, role, payload.get('line_id'))
        elif action == 'manual': result = ops.confirm_line(app, aid, int(payload.get('line_id', 0)), payload.get('quantity'), payload.get('reason'), username, role)
        elif action == 'finish-picking': result = ops.finish_picking(app, aid, username, role)
        elif action == 'shipping': result = ops.ship(app, aid, payload, username, role)
        else: raise ValueError('Acción no encontrada.')
    elif len(parts) == 5 and parts[2] == 'shipments' and parts[4] == 'receive':
        result = ops.receive(app, int(parts[3]), payload, username, role)
    else:
        request.send_json({'error': 'Ruta no encontrada.'}, 404); return
    request.send_json(result)
