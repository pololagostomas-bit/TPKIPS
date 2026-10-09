"""Headless Microsoft authorization; one protected server cache for both pilots."""
import hashlib
import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import msal
import requests

SCOPES = ["https://graph.microsoft.com/Files.ReadWrite"]
MAIL_SCOPES = SCOPES + ["https://graph.microsoft.com/Mail.Send"]
_lock = threading.RLock()


class CloudAuthError(ValueError):
    def __init__(self, message, code='authorization_required'):
        super().__init__(message)
        self.code = code


def cache_path():
    return Path(os.getenv('GRAPH_TOKEN_CACHE_PATH', 'data/microsoft/cache.json'))


@contextmanager
def locked():
    # Serialize refresh-token rotation across the two independent containers.
    path = cache_path().parent
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt':
        path.chmod(0o700)
    if not _lock.acquire(timeout=30):
        raise CloudAuthError('Microsoft esta ocupado. Intenta nuevamente.', 'busy')
    descriptor = None
    acquired = False
    try:
        descriptor = os.open(path / 'cache.lock', os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + 30
        while not acquired:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise CloudAuthError('Microsoft esta ocupado. Intenta nuevamente.', 'busy')
                time.sleep(0.05)
        yield
    finally:
        if descriptor is not None:
            if acquired:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        _lock.release()


def read_state(name):
    path = cache_path().parent / name
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise CloudAuthError('La configuracion Microsoft necesita revision.')
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as error:
        raise CloudAuthError('La configuracion Microsoft necesita revision.') from error


def write_state(name, data):
    target = cache_path().parent / name
    temporary = target.with_name(target.name + '.' + secrets.token_hex(8) + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(json.dumps(data))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
        if os.name != 'nt':
            target.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def settings():
    state = read_state('connection.json')
    return {
        'tenant_id': os.getenv('GRAPH_TENANT_ID', '').strip(),
        # Do not silently authorize an unverified application bundled in old code.
        'client_id': state.get('client_id') or os.getenv('GRAPH_CLIENT_ID', '').strip(),
    }


class _Http:
    def get(self, url, **kwargs):
        kwargs.setdefault('timeout', 20)
        return requests.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs.setdefault('timeout', 20)
        return requests.post(url, **kwargs)


def client():
    config = settings()
    try:
        tenant, application = str(UUID(config['tenant_id'])), str(UUID(config['client_id']))
    except (ValueError, TypeError, AttributeError) as error:
        raise CloudAuthError('Falta el Client ID de la aplicacion WMS registrada por TI.', 'configuration') from error
    cache = msal.SerializableTokenCache()
    try:
        if cache_path().exists():
            cache.deserialize(cache_path().read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise CloudAuthError('La autorizacion guardada necesita renovarse.') from error
    app = msal.PublicClientApplication(application,
        authority=f'https://login.microsoftonline.com/{tenant}', token_cache=cache, http_client=_Http())
    return app, cache


def save_cache(cache):
    if cache.has_state_changed:
        # MSAL serialization is JSON; atomic replacement retains owner-only mode.
        write_state(cache_path().name, json.loads(cache.serialize()))


def owner_key(headers):
    return hashlib.sha256(str(headers.get('Cookie', '')).encode()).hexdigest()


def configure(client_id):
    try:
        client_id = str(UUID(str(client_id)))
    except (ValueError, TypeError, AttributeError) as error:
        raise CloudAuthError('El Client ID debe ser un identificador UUID de Microsoft Entra.') from error
    with locked():
        if cache_path().exists() or read_state('pending.json'):
            raise CloudAuthError('Desconecta o cancela la autorizacion antes de cambiar la aplicacion.')
        write_state('connection.json', {'client_id': client_id})
    return {'configured': True}


def status():
    with locked():
        config = settings()
        selected = read_state('account.json')
        pending = read_state('pending.json')
        if pending and pending.get('expires_at', 0) <= time.time():
            write_state('pending.json', {})
            pending = {}
        return {'configured': bool(config['client_id'] and config['tenant_id']),
            'authorized': bool(selected.get('home_account_id') and cache_path().exists()),
            'pending': bool(pending), 'client_id': config['client_id'],
            'authorization_at': selected.get('authorization_at'),
            'mail_username': selected.get('mail_username', '')}


def begin(owner, mail_sender=None):
    with locked():
        pending = read_state('pending.json')
        if pending and pending.get('expires_at', 0) > time.time():
            raise CloudAuthError('Ya hay una autorizacion pendiente. Cancelala o espera su vencimiento.')
        app, _cache = client()
        try:
            flow = app.initiate_device_flow(scopes=MAIL_SCOPES if mail_sender else SCOPES)
        except (requests.RequestException, ValueError) as error:
            raise CloudAuthError('No se pudo contactar con Microsoft. Revisa la conexion y el registro de TI.') from error
        if not flow.get('user_code') or not flow.get('device_code'):
            raise CloudAuthError('Microsoft no permitio iniciar la conexion. TI debe habilitar el flujo de dispositivo.')
        flow_id = secrets.token_urlsafe(32)
        expires_at = min(flow.get('expires_at', time.time() + 900), time.time() + 900)
        write_state('pending.json', {'flow': flow, 'id': flow_id, 'owner': owner,
            'expires_at': expires_at, 'next_poll': time.time() + max(5, flow.get('interval', 5)),
            'mail_sender': mail_sender})
        return {'flow_id': flow_id, 'user_code': flow['user_code'],
            'verification_uri': 'https://microsoft.com/devicelogin',
            'expires_at': expires_at, 'interval': max(5, flow.get('interval', 5))}


def _pending(owner, flow_id):
    pending = read_state('pending.json')
    if not pending or pending.get('owner') != owner or not secrets.compare_digest(str(pending.get('id', '')), str(flow_id)):
        raise CloudAuthError('La autorizacion no pertenece a esta sesion o ya termino.')
    if pending.get('expires_at', 0) <= time.time():
        write_state('pending.json', {})
        raise CloudAuthError('El codigo Microsoft vencio. Inicia una nueva conexion.')
    return pending


def poll(owner, flow_id):
    with locked():
        pending = _pending(owner, flow_id)
        if pending['next_poll'] > time.time():
            return {'state': 'pending'}
        app, cache = client()
        try:
            result = app.acquire_token_by_device_flow(pending['flow'], exit_condition=lambda _flow: True)
        except requests.RequestException as error:
            raise CloudAuthError('No se pudo consultar Microsoft. Intenta nuevamente.') from error
        if result.get('access_token'):
            claims = result.get('id_token_claims') or {}
            expected = settings()['tenant_id'].lower()
            if str(claims.get('tid', '')).lower() != expected:
                write_state('pending.json', {})
                raise CloudAuthError('Autoriza con una cuenta de la empresa, no una cuenta personal.')
            sender = pending.get('mail_sender')
            if sender and str(claims.get('preferred_username', '')).casefold() != sender.casefold():
                write_state('pending.json', {})
                raise CloudAuthError('Autoriza con la cuenta configurada como remitente del reporte.')
            if sender and not any(scope.rsplit('/', 1)[-1].casefold() == 'mail.send'
                                  for scope in str(result.get('scope', '')).split()):
                write_state('pending.json', {})
                raise CloudAuthError('Microsoft no confirmo Mail.Send; solicita a TI el permiso de correo.')
            accounts = app.get_accounts(username=claims.get('preferred_username'))
            if len(accounts) != 1:
                write_state('pending.json', {})
                raise CloudAuthError('Microsoft no confirmo una cuenta unica. Vuelve a conectar.')
            previous = read_state('account.json')
            save_cache(cache)
            write_state('account.json', {'home_account_id': accounts[0]['home_account_id'],
                'authorization_at': time.time(), 'mail_username': sender or (
                    previous.get('mail_username', '') if previous.get('home_account_id') ==
                    accounts[0]['home_account_id'] else '')})
            write_state('pending.json', {})
            return {'state': 'authorized'}
        if result.get('error') in {'authorization_pending', 'slow_down'}:
            pending['next_poll'] = time.time() + max(5, pending['flow'].get('interval', 5))
            write_state('pending.json', pending)
            return {'state': 'pending'}
        write_state('pending.json', {})
        raise CloudAuthError('La autorizacion fue rechazada o vencio. TI puede requerir permisos o MFA.')


def cancel(owner, flow_id):
    with locked():
        _pending(owner, flow_id)
        write_state('pending.json', {})
    return {'state': 'cancelled'}


def disconnect():
    with locked():
        cache_path().unlink(missing_ok=True)
        write_state('account.json', {})
        write_state('pending.json', {})
    return {'state': 'disconnected'}


def access_token(scopes=None, expected_username=None):
    with locked():
        secret = os.getenv('GRAPH_CLIENT_SECRET', '').strip()
        if secret:
            if expected_username:
                raise CloudAuthError('El reporte requiere autorizar el buzon remitente con Microsoft.')
            config = settings()
            try:
                tenant, application = str(UUID(config['tenant_id'])), str(UUID(config['client_id']))
            except (ValueError, TypeError, AttributeError) as error:
                raise CloudAuthError('Falta configurar la aplicacion Microsoft del servidor.', 'configuration') from error
            result = msal.ConfidentialClientApplication(application,
                authority=f'https://login.microsoftonline.com/{tenant}', client_credential=secret,
                http_client=_Http()).acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])
            if not result.get('access_token'):
                raise CloudAuthError('No se pudo autorizar la aplicacion Microsoft del servidor.')
            return result['access_token']
        app, cache = client()
        selected = read_state('account.json').get('home_account_id')
        account = next((a for a in app.get_accounts() if a.get('home_account_id') == selected), None)
        if not account:
            raise CloudAuthError('Conecta Microsoft desde Cortes Excel con el administrador.')
        if expected_username and str(account.get('username', '')).casefold() != expected_username.casefold():
            raise CloudAuthError('La cuenta Microsoft no corresponde al remitente del reporte.')
        try:
            result = app.acquire_token_silent(scopes or SCOPES, account=account)
        except requests.RequestException as error:
            raise CloudAuthError('No se pudo renovar el acceso Microsoft. Revisa la conexion.', 'network') from error
        save_cache(cache)
        if not result or not result.get('access_token'):
            raise CloudAuthError('Microsoft requiere una nueva autorizacion del administrador.')
        if expected_username and not any(scope.rsplit('/', 1)[-1].casefold() == 'mail.send'
                                        for scope in str(result.get('scope', '')).split()):
            raise CloudAuthError('Autoriza Mail.Send con el remitente desde Alertas de compras / OC.')
        return result['access_token']
