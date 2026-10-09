"""Server-owned password policy shared by the manual and barcode pilots."""
import argparse
import json
import os
import sys
import time

from backend import app, wsgi
try:
    from backend.services import cloud_sync
except ImportError as error:
    if getattr(error, 'name', '') != 'backend.services.cloud_sync':
        raise
    cloud_sync = None
try:
    from backend.services import password_recovery
except ImportError as error:
    # Older approved images must still boot with the shared server policy.
    if getattr(error, 'name', '') not in {'backend.services', 'backend.services.password_recovery'}:
        raise
    password_recovery = None

BASE_APPLICATION = wsgi.application
TEMPLATES = app.ROOT / 'frontend/templates'


def init_schema(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(users)')}
    if 'must_change_password' not in columns:
        connection.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
    if 'temporary_password_expires_at' not in columns:
        connection.execute('ALTER TABLE users ADD COLUMN temporary_password_expires_at REAL NOT NULL DEFAULT 0')
    if password_recovery is not None:
        password_recovery.init_schema(connection)


def policy_for(connection, username):
    row = connection.execute('''SELECT must_change_password,temporary_password_expires_at
        FROM users WHERE username=? AND active=1''', (username,)).fetchone()
    if not row:
        raise PermissionError('Inicia sesión para continuar')
    required = bool(row['must_change_password'])
    if required and row['temporary_password_expires_at'] <= time.time():
        raise PermissionError('La clave temporal venció. Solicita una nueva al administrador.')
    return required


def reset_temporary(connection, username, password, hours=24):
    user = connection.execute('SELECT active,password_hash FROM users WHERE username=?', (username,)).fetchone()
    if not user or not user['active']:
        raise ValueError('No existe el usuario activo indicado')
    if app.identity.password_matches(password, user['password_hash']):
        raise ValueError('La clave temporal debe ser diferente de la actual')
    digest = app.identity.password_hash(password)
    connection.execute('''UPDATE users SET password_hash=?,must_change_password=1,
        temporary_password_expires_at=?,updated_at=? WHERE username=?''',
        (digest, time.time() + hours * 3600, app.identity.local_now(), username))
    connection.execute('DELETE FROM user_sessions WHERE username=?', (username,))
    app.identity.audit(connection, 'server-admin', username, 'CLAVE TEMPORAL', 'Cambio obligatorio; sesiones revocadas')


def change_password(connection, headers, data, remote):
    user = app.identity.session_user(connection, headers)
    username = user['username']
    policy_for(connection, username)
    old = data.get('current_password')
    new = data.get('new_password')
    confirmation = data.get('confirm_password')
    row = connection.execute('SELECT password_hash FROM users WHERE username=?', (username,)).fetchone()
    if not app.identity.password_matches(old, row['password_hash']):
        raise ValueError('La contraseña actual no es correcta')
    if not isinstance(new, str) or new != confirmation:
        raise ValueError('Las contraseñas nuevas no coinciden')
    if app.identity.password_matches(new, row['password_hash']):
        raise ValueError('La nueva contraseña debe ser diferente de la temporal o actual')
    digest = app.identity.password_hash(new)
    connection.execute('''UPDATE users SET password_hash=?,must_change_password=0,
        temporary_password_expires_at=0,updated_at=? WHERE username=?''',
        (digest, app.identity.local_now(), username))
    connection.execute('DELETE FROM user_sessions WHERE username=?', (username,))
    app.identity.audit(connection, username, username, 'CAMBIAR CONTRASEÑA', 'Sesiones anteriores revocadas')
    token, account = app.identity.login(connection, username, new, remote)
    if not token:
        raise ValueError('No se pudo renovar la sesión')
    account['must_change_password'] = False
    return token, account


def send(request, start_response):
    body = request.wfile.getvalue()
    headers = [(key, value) for key, value in request.response_headers if key.lower() != 'content-length']
    headers.append(('Content-Length', str(len(body))))
    from http import HTTPStatus
    start_response(f'{request.response_status} {HTTPStatus(request.response_status).phrase}', headers)
    return [b'' if request.command == 'HEAD' else body]


def redirect(request, target):
    request.send_response(303)
    request.send_header('Location', target)
    request.end_headers()


def application(environ, start_response):
    if os.getenv('TRITON_AUTH_MODE', 'demo') != 'local':
        return BASE_APPLICATION(environ, start_response)
    request = wsgi.Request(environ)
    path = environ.get('PATH_INFO', '/')
    method = request.command
    try:
        if cloud_sync is not None and path in {'/assets/cloud-connection.js', '/assets/cloud-connection.css'} and method in {'GET', 'HEAD'}:
            asset = app.ROOT / 'frontend/static' / path.rsplit('/', 1)[-1]
            request.send_response(200)
            request.send_header('Content-Type', 'text/css; charset=utf-8' if path.endswith('.css') else 'application/javascript; charset=utf-8')
            request.end_headers()
            request.wfile.write(asset.read_bytes())
            return send(request, start_response)
        if path in {'/recover-password', '/reset-password'} and method in {'GET', 'HEAD'}:
            body = (TEMPLATES / 'login.html').read_bytes()
            request.send_response(200)
            request.send_header('Content-Type', 'text/html; charset=utf-8')
            request.send_header('Cache-Control', 'no-store')
            request.send_header('Referrer-Policy', 'no-referrer')
            request.send_header('X-Frame-Options', 'DENY')
            request.end_headers()
            request.wfile.write(body)
            return send(request, start_response)
        if path.startswith('/api/password-recovery/'):
            if password_recovery is None:
                request.send_json({'error':'La recuperacion por correo aun no esta habilitada. Contacta al administrador.'}, 503)
                return send(request, start_response)
            if method != 'POST':
                request.send_header('Allow', 'POST')
                request.send_json({'error':'Usa POST para esta solicitud'}, 405)
                return send(request, start_response)
            if request.headers.get('X-WMS-Request') != '1' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                request.send_json({'error':'Actualiza la pagina antes de enviar cambios'}, 403)
                return send(request, start_response)
            if int(request.headers.get('Content-Length', 0)) > 16384:
                raise ValueError('Solicitud demasiado grande')
            data = request.body()
            if not isinstance(data, dict):
                raise ValueError('Solicitud no valida')
            remote = request.client_address[0]
            with app.db() as connection:
                connection.execute('BEGIN IMMEDIATE')
                if path == '/api/password-recovery/request':
                    payload, status = password_recovery.request_recovery(connection, data.get('username'), remote)
                elif path in {'/api/password-recovery/check', '/api/password-recovery/reset'}:
                    if not password_recovery.allow(connection, [('recovery-token', str(remote)[:120], 20, 900)]):
                        payload, status = {'error':'Demasiados intentos. Espera 15 minutos.'}, 429
                    else:
                        # Persist brute-force counters even when validation rejects a link.
                        connection.execute('SAVEPOINT recovery_change')
                        try:
                            payload = (password_recovery.inspect_token(connection, data.get('token'))
                                if path.endswith('/check') else password_recovery.reset_password(connection, data))
                            status = 200
                        except (ValueError, TypeError) as error:
                            connection.execute('ROLLBACK TO recovery_change')
                            payload, status = {'error':str(error)}, 400
                        finally:
                            connection.execute('RELEASE recovery_change')
                else:
                    payload, status = {'error':'Ruta no encontrada'}, 404
            request.send_header('Cache-Control', 'no-store')
            request.send_json(payload, status)
            return send(request, start_response)
        if path == '/api/login' and method == 'POST':
            captured = {}
            def capture(status, headers):
                captured.update(status=status, headers=headers)
            body = b''.join(BASE_APPLICATION(environ, capture))
            if captured['status'].startswith('200 '):
                payload = json.loads(body)
                try:
                    with app.db() as connection:
                        payload['must_change_password'] = policy_for(connection, payload['username'])
                except PermissionError:
                    # An expired temporary password must not issue a usable session.
                    cookie = next((value for key, value in captured['headers'] if key.lower() == 'set-cookie'), '')
                    with app.db() as connection:
                        app.identity.logout(connection, {'Cookie':cookie.split(';')[0]})
                    raise
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                captured['headers'] = [(key, value) for key, value in captured['headers'] if key.lower() != 'content-length']
                captured['headers'].append(('Content-Length', str(len(body))))
            start_response(captured['status'], captured['headers'])
            return [body]

        public = path.startswith('/assets/') or path in {
            '/health', '/icon.svg', '/manifest.webmanifest', '/service-worker.js', '/api/logout'}
        if public:
            return BASE_APPLICATION(environ, start_response)
        with app.db() as connection:
            try:
                user = app.identity.session_user(connection, request.headers)
            except PermissionError:
                if path == '/login':
                    return BASE_APPLICATION(environ, start_response)
                raise
            required = policy_for(connection, user['username'])

        if path == '/change-password' and method in {'GET', 'HEAD'}:
            body = (TEMPLATES / 'change-password.html').read_bytes()
            request.send_response(200)
            request.send_header('Content-Type', 'text/html; charset=utf-8')
            request.end_headers()
            request.wfile.write(body)
            return send(request, start_response)
        if path == '/api/change-password' and method == 'POST':
            if request.headers.get('X-WMS-Request') != '1' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                request.send_json({'error':'Actualiza la página antes de enviar cambios'}, 403)
                return send(request, start_response)
            data = request.body()
            with app.db() as connection:
                connection.execute('BEGIN IMMEDIATE')
                token, payload = change_password(connection, request.headers, data, request.client_address[0])
            request.send_header('Set-Cookie', app.identity.cookie_header(token))
            request.send_json(payload)
            return send(request, start_response)
        if path == '/api/me' and method in {'GET', 'HEAD'}:
            captured = {}
            def capture_me(status, headers):
                captured.update(status=status, headers=headers)
            body = b''.join(BASE_APPLICATION(environ, capture_me))
            if captured['status'].startswith('200 '):
                payload = json.loads(body)
                payload['must_change_password'] = required
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                captured['headers'] = [(key, value) for key, value in captured['headers'] if key.lower() != 'content-length']
                captured['headers'].append(('Content-Length', str(len(body))))
            start_response(captured['status'], captured['headers'])
            return [b'' if method == 'HEAD' else body]
        if required:
            if path.startswith('/api/'):
                request.send_header('X-WMS-Password-Change', 'required')
                request.send_json({'error':'Debes cambiar la contraseña temporal antes de continuar',
                    'code':'PASSWORD_CHANGE_REQUIRED'}, 403)
            else:
                redirect(request, '/change-password')
            return send(request, start_response)
        if cloud_sync is not None and path == '/cloud-connection' and method in {'GET', 'HEAD'}:
            if user['role'] != 'ADMINISTRADOR':
                request.send_json({'error':'Solo el administrador puede gestionar los cortes.'}, 403)
            else:
                request.send_response(200)
                request.send_header('Content-Type', 'text/html; charset=utf-8')
                request.end_headers()
                request.wfile.write((TEMPLATES / 'cloud-connection.html').read_bytes())
            return send(request, start_response)
        if cloud_sync is not None and (path.startswith('/api/cloud-connection/') or path == '/api/daily-cloud-sync'):
            payload, code = cloud_sync.handle(request, app, user)
            request.send_json(payload, code)
            return send(request, start_response)
        return BASE_APPLICATION(environ, start_response)
    except PermissionError as error:
        if path.startswith('/api/'):
            request.send_json({'error':str(error)}, 401)
        else:
            redirect(request, '/login')
        return send(request, start_response)
    except (ValueError, TypeError) as error:
        request.send_json({'error':str(error)}, 400)
        return send(request, start_response)
    except Exception:
        import logging
        logging.exception('Fallo de la politica de acceso: %s', path)
        request.send_json({'error':'No se pudo comprobar el acceso. Intenta nuevamente.'}, 500)
        return send(request, start_response)


def prepare():
    wsgi.prepare()
    with app.db() as connection:
        init_schema(connection)
        if cloud_sync is not None:
            cloud_sync.init_schema(connection)
    if cloud_sync is not None:
        cloud_sync.start_worker(app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'reset'])
    parser.add_argument('--username')
    args = parser.parse_args()
    if args.action == 'serve':
        prepare()
        wsgi.application = application
        wsgi.serve()
    else:
        if not args.username:
            parser.error('Indica --username')
        password = sys.stdin.readline().rstrip('\r\n')
        with app.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            init_schema(connection)
            reset_temporary(connection, args.username, password)
        print('Clave temporal aplicada; vence en 24 horas. Sesiones del usuario revocadas.')


if __name__ == '__main__':
    main()
