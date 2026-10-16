"""Bounded, shared report jobs. Never render a workbook on a web request thread."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

KINDS = {'reception-dashboard', 'reception-history-preview', 'reception-history-xlsx'}
CACHE_SECONDS = 120
RETENTION_SECONDS = 1800
JOB_SECONDS = 600
MAX_QUEUE = 4
MAX_RESULT_BYTES = 64 * 1024 * 1024
_children = {}
_launch_lock = threading.Lock()


def directory(source):
    source = Path(source).resolve()
    digest = hashlib.sha256(str(source).encode()).hexdigest()[:12]
    return source.parent / ('.report-jobs-' + digest)


@contextmanager
def queue(source):
    root = directory(source)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / 'jobs.sqlite3'
    connection = sqlite3.connect(path, timeout=2)
    os.chmod(path, 0o600)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
            phase TEXT NOT NULL, created REAL NOT NULL, started REAL,
            finished REAL, snapshot_at REAL, error TEXT)''')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _public(row):
    return {key: row[key] for key in
            ('id', 'kind', 'status', 'phase', 'created', 'started', 'finished', 'snapshot_at', 'error')}


def submit(source, kind):
    if kind not in KINDS:
        raise ValueError('Reporte no valido')
    now = time.time()
    with queue(source) as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('''SELECT * FROM jobs WHERE kind=? AND
            (status IN ('QUEUED','RUNNING') OR (status='READY' AND finished>?))
            ORDER BY created DESC LIMIT 1''', (kind, now - CACHE_SECONDS)).fetchone()
        if row and (row['status'] != 'READY' or result_path(source, row).is_file()):
            result = _public(row)
        else:
            count = connection.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
            if count >= MAX_QUEUE:
                raise ValueError('La cola de reportes esta completa. Intenta nuevamente en unos minutos.')
            job_id = uuid.uuid4().hex
            connection.execute('INSERT INTO jobs(id,kind,status,phase,created) VALUES (?,?,\'QUEUED\',\'En cola\',?)',
                               (job_id, kind, now))
            result = _public(connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
    if result['status'] in {'QUEUED', 'RUNNING'}:
        ensure_worker(source)
    return result


def lookup(source, job_id):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('Reporte no valido')
    with queue(source) as connection:
        row = connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or (row['finished'] and row['finished'] < time.time() - RETENTION_SECONDS):
            raise ValueError('El reporte ha vencido. Solicitalo nuevamente.')
        result = _public(row)
    if result['status'] in {'QUEUED', 'RUNNING'}:
        ensure_worker(source)
    return result


def result_path(source, job):
    suffix = '.xlsx' if job['kind'].endswith('-xlsx') else '.json'
    return directory(source) / (job['id'] + suffix)


def ensure_worker(source):
    key = str(Path(source).resolve())
    with _launch_lock:
        child = _children.get(key)
        if child is not None and child.poll() is None:
            return
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        # A separate interpreter isolates both the GIL and workbook memory.
        _children[key] = subprocess.Popen(
            [sys.executable, '-m', 'backend.services.report_jobs', key],
            cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


@contextmanager
def _worker_lock(root):
    with (root / 'worker.lock').open('a+b') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                if not lock.read(1):
                    lock.write(b'0'); lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _phase(source, job_id, phase, **fields):
    with queue(source) as connection:
        fields['phase'] = phase
        connection.execute('UPDATE jobs SET ' + ','.join(key + '=?' for key in fields) + ' WHERE id=?',
                           (*fields.values(), job_id))


def _snapshot(source, target, deadline):
    if not Path(source).is_file():
        raise ValueError('Base operativa no disponible')
    size = Path(source).stat().st_size
    if shutil.disk_usage(target.parent).free < size * 2 + 128 * 1024 * 1024:
        raise ValueError('No hay espacio suficiente para preparar el reporte')
    original = sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    copy = sqlite3.connect(target)
    os.chmod(target, 0o600)
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('Tiempo de copia agotado')
    try:
        # Online backup releases the source read lock between small page batches.
        # Do not copy just the .db file: committed WAL rows must be included.
        original.backup(copy, pages=128, progress=progress, sleep=0.05)
    finally:
        original.close()
        copy.close()


def _build(source, job):
    from backend.services import reception
    job_id = job['id']
    root = directory(source)
    snapshot = root / (job_id + '.snapshot.sqlite3')
    partial = root / (job_id + '.partial')
    deadline = time.monotonic() + JOB_SECONDS
    if os.name != 'nt':
        import signal
        def timed_out(signum, frame):
            raise TimeoutError('Tiempo de reporte agotado')
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(JOB_SECONDS)
    try:
        _phase(source, job_id, 'Preparando corte SQLite')
        _snapshot(source, snapshot, min(deadline, time.monotonic() + 120))
        _phase(source, job_id, 'Generando reporte', snapshot_at=time.time())
        connection = sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        try:
            if job['kind'] == 'reception-dashboard':
                body = json.dumps(reception.reception_report(connection), ensure_ascii=False).encode('utf-8')
            elif job['kind'] == 'reception-history-preview':
                body = json.dumps(reception.reception_history_report(connection), ensure_ascii=False).encode('utf-8')
            else:
                body = reception.reception_history_export_bytes(connection)
        finally:
            connection.close()
        if time.monotonic() > deadline or len(body) > MAX_RESULT_BYTES:
            raise ValueError('Reporte demasiado grande; solicita un periodo menor')
        with partial.open('wb') as output:
            os.chmod(partial, 0o600)
            output.write(body)
        partial.replace(result_path(source, job))
        _phase(source, job_id, 'Listo para descargar', status='READY', finished=time.time())
    except Exception:
        _phase(source, job_id, 'No se pudo preparar', status='FAILED', finished=time.time(),
               error='No se pudo generar el reporte. Revisa espacio y disponibilidad del servidor y vuelve a solicitarlo.')
    finally:
        if os.name != 'nt':
            signal.alarm(0)
        partial.unlink(missing_ok=True)
        for suffix in ('', '-wal', '-shm', '-journal'):
            Path(str(snapshot) + suffix).unlink(missing_ok=True)


def run_worker(source):
    os.umask(0o077)
    if os.name != 'nt':
        os.nice(10)
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    with queue(source):
        pass
    root = directory(source)
    with _worker_lock(root) as acquired:
        if not acquired:
            return
        with queue(source) as connection:
            # Only the lock holder recovers an interrupted process, never a live job.
            connection.execute("""UPDATE jobs SET status='FAILED',phase='Proceso interrumpido',
                finished=?,error='El servidor interrumpio el reporte. Solicitalo nuevamente.'
                WHERE status='RUNNING'""", (time.time(),))
            expired = connection.execute('SELECT * FROM jobs WHERE finished<?',
                                         (time.time() - RETENTION_SECONDS,)).fetchall()
            for row in expired:
                result_path(source, row).unlink(missing_ok=True)
            connection.execute('DELETE FROM jobs WHERE finished<?', (time.time() - RETENTION_SECONDS,))
        for file in root.glob('*.snapshot.sqlite3*'):
            file.unlink(missing_ok=True)
        for file in root.glob('*.partial'):
            file.unlink(missing_ok=True)
        while True:
            with queue(source) as connection:
                connection.execute('BEGIN IMMEDIATE')
                job = connection.execute("SELECT * FROM jobs WHERE status='QUEUED' ORDER BY created LIMIT 1").fetchone()
                if job:
                    connection.execute("UPDATE jobs SET status='RUNNING',started=? WHERE id=?", (time.time(), job['id']))
            if not job:
                return
            _build(source, job)


if __name__ == '__main__':
    run_worker(Path(sys.argv[1]).resolve())
