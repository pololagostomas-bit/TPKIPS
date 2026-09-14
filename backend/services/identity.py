"""Local pilot identities: persistent users, revocable sessions and audited changes."""
import hashlib
import hmac
import os
import re
import secrets
import time
from http.cookies import SimpleCookie

from backend.services.daily_operations import local_now

COOKIE = 'triton_session'
PUBLIC_FIELDS = 'username, display_name, first_name, last_name, document_id, role, shift, active, created_at, updated_at'


def password_hash(password):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        raise ValueError('La contraseña debe tener entre 12 y 256 caracteres')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def password_matches(password, encoded):
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100000 <= int(rounds) <= 1000000:
            return False
        if not isinstance(password, str) or len(password) > 256:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, AttributeError, TypeError):
        return False


def init_identity_schema(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(users)')}
    if 'password_hash' not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
    for column in ('first_name', 'last_name', 'document_id'):
        if column not in columns:
            connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS user_sessions (
          token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
          expires_at REAL NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS user_audit (
          id INTEGER PRIMARY KEY, actor TEXT NOT NULL, username TEXT NOT NULL,
          action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts (
          attempt_key TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(username);
    ''')


def audit(connection, actor, username, action, detail=''):
    connection.execute('INSERT INTO user_audit(actor,username,action,detail,created_at) VALUES(?,?,?,?,?)',
                       (actor, username, action, detail, local_now()))


def bootstrap_admin(connection, roles):
    if connection.execute("SELECT 1 FROM users WHERE role='ADMINISTRADOR' AND active=1 AND password_hash<>''").fetchone():
        return
    username = os.getenv('TRITON_BOOTSTRAP_ADMIN_USERNAME', '').strip().lower()
    password = os.getenv('TRITON_BOOTSTRAP_ADMIN_PASSWORD', '')
    if not username or not password:
        raise ValueError('Primer inicio: configura TRITON_BOOTSTRAP_ADMIN_USERNAME y TRITON_BOOTSTRAP_ADMIN_PASSWORD (mínimo 12 caracteres).')
    save(connection, {'username':username, 'display_name':username, 'role':'ADMINISTRADOR',
                      'shift':'DÍA', 'password':password}, 'bootstrap', roles)


def save(connection, data, actor, roles):
    username = str(data.get('username') or '').strip().lower()
    name = str(data.get('display_name') or '').strip()
    first_name = str(data.get('first_name') or '').strip()
    last_name = str(data.get('last_name') or '').strip()
    document_id = str(data.get('document_id') or '').strip()
    role = str(data.get('role') or '').upper()
    shift = str(data.get('shift') or 'DÍA').upper()
    if not re.fullmatch(r'[a-z0-9][a-z0-9._@+\-]{1,119}', username):
        raise ValueError('Usuario: usa entre 2 y 120 letras, números, punto, guion o correo')
    if not name or len(name) > 160 or len(first_name) > 80 or len(last_name) > 120 or len(document_id) > 40 or role not in roles or shift not in {'DÍA','NOCHE'}:
        raise ValueError('Nombre, rol o turno no válido')
    existing = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if existing and existing['active'] and existing['role']=='ADMINISTRADOR' and role!='ADMINISTRADOR':
        _protect_admin(connection, username)
    password = data.get('password')
    digest = password_hash(password) if password else (existing['password_hash'] if existing else '')
    if not digest and os.getenv('TRITON_AUTH_MODE', 'demo') == 'local':
        raise ValueError('Este usuario necesita una contraseña para iniciar sesión')
    timestamp = local_now()
    connection.execute('''INSERT INTO users(username,display_name,first_name,last_name,document_id,role,shift,active,created_at,updated_at,password_hash)
        VALUES(?,?,?,?,?,?,?,1,?,?,?) ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,
        first_name=excluded.first_name,last_name=excluded.last_name,document_id=excluded.document_id,
        role=excluded.role,shift=excluded.shift,active=1,updated_at=excluded.updated_at,password_hash=excluded.password_hash''',
        (username,name,first_name,last_name,document_id,role,shift,timestamp,timestamp,digest))
    if existing and (password or role != existing['role']):
        connection.execute('DELETE FROM user_sessions WHERE username=?', (username,))
    audit(connection, actor, username, 'ACTUALIZAR' if existing else 'CREAR', f'Rol={role}; turno={shift}')
    return dict(connection.execute(f'SELECT {PUBLIC_FIELDS} FROM users WHERE username=?', (username,)).fetchone())


def _protect_admin(connection, username):
    count = connection.execute("SELECT COUNT(*) FROM users WHERE role='ADMINISTRADOR' AND active=1 AND username<>? AND password_hash<>''", (username,)).fetchone()[0]
    if not count:
        raise ValueError('Debe quedar al menos un administrador activo con acceso')


def deactivate(connection, username, actor):
    existing = connection.execute('SELECT role FROM users WHERE username=?', (username,)).fetchone()
    if not existing:
        raise ValueError('Usuario no encontrado')
    if username == actor:
        raise ValueError('No puedes desactivar tu propia cuenta')
    if existing['role'] == 'ADMINISTRADOR':
        _protect_admin(connection, username)
    connection.execute('UPDATE users SET active=0,updated_at=? WHERE username=?', (local_now(),username))
    connection.execute('DELETE FROM user_sessions WHERE username=?', (username,))
    audit(connection, actor, username, 'DESACTIVAR')


def login(connection, username, password, remote=''):
    """Return (session token, user). Failed attempts must be committed by caller."""
    username = str(username or '').strip().lower()[:120]
    key = hashlib.sha256((username+'|'+remote).encode()).hexdigest()
    clock = time.time()
    attempt = connection.execute('SELECT * FROM login_attempts WHERE attempt_key=?', (key,)).fetchone()
    if attempt and attempt['locked_until'] > clock:
        return None, None
    user = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if not user or not user['active'] or not password_matches(password, user['password_hash']):
        failures = (attempt['failures'] if attempt and attempt['failures'] < 5 and attempt['locked_until'] > clock-900 else 0)+1
        connection.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, failures, clock+900 if failures>=5 else clock))
        return None, None
    connection.execute('DELETE FROM login_attempts WHERE attempt_key=?', (key,))
    connection.execute('DELETE FROM user_sessions WHERE expires_at<?', (clock,))
    token = secrets.token_urlsafe(32)
    hours = max(1, min(24, int(os.getenv('TRITON_SESSION_HOURS', '12'))))
    connection.execute('INSERT INTO user_sessions VALUES(?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), username, clock+hours*3600, local_now()))
    audit(connection, username, username, 'INICIAR SESION')
    return token, {key:user[key] for key in ('username','display_name','first_name','last_name','document_id','role','shift')}


def token_from_headers(headers):
    try:
        cookie = SimpleCookie()
        cookie.load(headers.get('Cookie', ''))
        return cookie[COOKIE].value if COOKIE in cookie else ''
    except Exception:
        return ''


def session_user(connection, headers):
    token = token_from_headers(headers)
    if not token:
        raise PermissionError('Inicia sesión para continuar')
    user = connection.execute('''SELECT u.username,u.role,u.display_name,u.first_name,u.last_name,u.document_id,u.shift FROM user_sessions s
         JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>? AND u.active=1''',
         (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if not user:
        raise PermissionError('La sesión venció o el usuario está desactivado')
    return dict(user)


def logout(connection, headers):
    token = token_from_headers(headers)
    connection.execute('DELETE FROM user_sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def cookie_header(token, expired=False):
    secure = '; Secure' if os.getenv('TRITON_COOKIE_SECURE', '0') == '1' else ''
    return f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict{secure}' + ('; Max-Age=0' if expired else '')


def require_assignee(connection, username, expected_role):
    if os.getenv('TRITON_AUTH_MODE','demo') != 'local' or not username:
        return
    user = connection.execute('SELECT role,active FROM users WHERE username=?', (username,)).fetchone()
    accepted_roles = {
        'PICKER': {'PICKER', 'PICKER_GUIADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'},
        'GUIADOR': {'GUIADOR', 'PICKER_GUIADOR', 'ASISTENTE_RECEPCION', 'AUXILIAR_RECEPCION'},
        'ASISTENTE_RECEPCION': {'ASISTENTE_RECEPCION'},
        'AUXILIAR_RECEPCION': {'AUXILIAR_RECEPCION'},
    }.get(expected_role, {expected_role})
    if not user or not user['active'] or user['role'] not in accepted_roles:
        raise ValueError(f'Selecciona un usuario activo compatible con {expected_role}')
