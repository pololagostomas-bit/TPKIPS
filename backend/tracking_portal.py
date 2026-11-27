"""Restricted tracking surface; authentication stays owned by password_policy."""
import json
import os
import sqlite3
import threading
import time
from collections import deque
from http import HTTPStatus
from urllib.parse import parse_qs

ASSETS = {'tracking.js': ('application/javascript', 'frontend/static/tracking.js'),
          'tracking.css': ('text/css', 'frontend/static/tracking.css'),
          'logo.png': ('image/png', 'frontend/static/triton-logo.png')}
_requests = {}
_lock = threading.Lock()


def _allow(username):
    now = time.monotonic()
    with _lock:
        if username not in _requests and len(_requests) >= 512:
            del _requests[min(_requests, key=lambda key: _requests[key][-1])]
        stamps = _requests.setdefault(username, deque())
        while stamps and stamps[0] <= now - 60:
            stamps.popleft()
        if len(stamps) >= 30:
            return False
        stamps.append(now)
        return True


def application(environ, start_response, authenticate):
    from backend import app, password_policy
    path = environ.get('PATH_INFO', '')
    method = environ.get('REQUEST_METHOD', 'GET')
    authenticated = False

    def respond(payload, status=200, content_type='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        start_response(f'{status} {HTTPStatus(status).phrase}', [
            ('Content-Type', content_type), ('Content-Length', str(len(body))),
            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'),
            ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")])
        return [b'' if method == 'HEAD' else body]

    try:
        if os.getenv('TRITON_AUTH_MODE', 'demo') != 'local':
            return respond({'error': 'Tracking requiere autenticación local habilitada.'}, 503)
        if path in {'/tracking', '/tracking/', '/tracking/login'} and method in {'GET', 'HEAD'}:
            return respond((app.ROOT / 'frontend/templates/tracking.html').read_bytes(), content_type='text/html; charset=utf-8')
        name = path.removeprefix('/tracking/static/')
        if path.startswith('/tracking/static/') and name in ASSETS and method in {'GET', 'HEAD'}:
            mime, filename = ASSETS[name]
            return respond((app.ROOT / filename).read_bytes(), content_type=mime)
        aliases = {f'/tracking/api/{name}': f'/api/{name}' for name in ('login', 'logout', 'change-password')}
        if path in aliases:
            if method != 'POST':
                return respond({'error': 'Usa POST para esta solicitud.'}, 405)
            origin = environ.get('HTTP_ORIGIN')
            scheme = 'https' if os.getenv('TRITON_COOKIE_SECURE', '0') == '1' else environ.get('wsgi.url_scheme', 'http')
            expected = scheme + '://' + environ.get('HTTP_HOST', '')
            if (environ.get('HTTP_X_WMS_REQUEST') != '1' or environ.get('HTTP_SEC_FETCH_SITE') == 'cross-site'
                    or (origin and origin.lower() != expected.lower())):
                return respond({'error': 'La solicitud debe proceder de esta página.'}, 403)
            length = int(environ.get('CONTENT_LENGTH') or 0)
            if not 0 <= length <= 4096:
                raise ValueError('Solicitud demasiado grande.')
            return authenticate({**environ, 'PATH_INFO': aliases[path]}, start_response)
        if len(environ.get('QUERY_STRING', '')) > 512:
            raise ValueError('Consulta demasiado grande.')
        if path not in {'/tracking/api/me', '/tracking/api/search'}:
            return respond({'error': 'Ruta no disponible.'}, 404)
        if method not in {'GET', 'HEAD'}:
            return respond({'error': 'Tracking es solo de consulta.'}, 405)
        with app.db() as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            from backend.wsgi import Request
            user = app.identity.session_user(connection, Request(environ).headers)
            authenticated = True
            if user['role'] not in app.identity.TRACKING_ROLES:
                raise PermissionError('Solicita al administrador un perfil de Tracking.')
            details = user['role'] == app.identity.TRACKING_PARTS_ROLE
            required = password_policy.policy_for(connection, user['username'])
            if path.endswith('/me'):
                return respond({'username': user['username'], 'display_name': user['display_name'],
                                'must_change_password': required, 'details': details})
            if required:
                return respond({'error': 'Debes cambiar tu contraseña temporal.', 'code': 'PASSWORD_CHANGE_REQUIRED'}, 403)
            query = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True, strict_parsing=True, max_num_fields=4)
            if set(query) - {'type', 'number', 'offset', 'limit'} or any(len(v) != 1 for v in query.values()):
                raise ValueError('Filtros no válidos.')
            kind = query.get('type', [''])[0].strip().upper()
            if not _allow(user['username']):
                return respond({'error': 'Demasiadas consultas. Espera un minuto.'}, 429)
            from backend.services import tracking
            result = tracking.search(connection, kind, query.get('number', [''])[0],
                                     offset=int(query.get('offset', ['0'])[0]), limit=int(query.get('limit', ['50'])[0]),
                                     details=details)
            return respond(result)
    except PermissionError as error:
        return respond({'error': str(error)}, 403 if authenticated else 401)
    except ValueError as error:
        return respond({'error': str(error)[:200] or 'Revisa el tipo de documento, número y página.'}, 400)
    except TypeError:
        return respond({'error': 'Revisa el tipo de documento, número y página.'}, 400)
    except sqlite3.Error:
        return respond({'error': 'No se pudo leer el último corte. Intenta de nuevo.'}, 503)
