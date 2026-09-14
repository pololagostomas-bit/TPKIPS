"""Mantenimiento seguro de la base SQLite de TRITON WMS.

Las copias se crean con la API online de SQLite: nunca se copia el archivo de
base de datos en bruto mientras la aplicación está ejecutándose.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import signal
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = Path(os.getenv("TRITON_DB_PATH", str(ROOT / "triton.db")))
DEFAULT_BACKUP_DIR = Path(os.getenv("TRITON_BACKUP_DIR", str(ROOT / "backups")))
BACKUP_PREFIX = "triton-"
BACKUP_SUFFIX = ".db"


class MaintenanceError(RuntimeError):
    """Error operativo esperado, apto para mostrar en la CLI."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("no puede ser negativo")
    return parsed


def _require_database(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise MaintenanceError(f"No existe la base SQLite: {resolved}")
    return resolved


def check_database(path: Path) -> dict[str, object]:
    """Ejecuta quick_check y valida el SHA-256 adjunto cuando existe."""
    database = _require_database(path)
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)
        try:
            rows = [row[0] for row in connection.execute("PRAGMA quick_check").fetchall()]
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise MaintenanceError(f"SQLite no pudo abrir/verificar {database}: {error}") from error
    if rows != ["ok"]:
        raise MaintenanceError(f"La verificación SQLite falló para {database}: {'; '.join(rows)}")
    checksum_path = Path(f"{database}.sha256")
    checksum = _sha256(database)
    if checksum_path.exists():
        try:
            expected = checksum_path.read_text(encoding="ascii").split()[0].lower()
        except (OSError, IndexError, UnicodeError) as error:
            raise MaintenanceError(f"No se pudo leer el checksum {checksum_path}: {error}") from error
        if expected != checksum:
            raise MaintenanceError(f"El checksum SHA-256 no coincide para {database}")
    return {
        "status": "ok",
        "path": str(database),
        "bytes": database.stat().st_size,
        "sha256": checksum,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_name(now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{BACKUP_PREFIX}{moment:%Y%m%dT%H%M%S%fZ}{BACKUP_SUFFIX}"


def _sqlite_sidecars(path: Path) -> tuple[Path, Path]:
    return Path(f"{path}-wal"), Path(f"{path}-shm")


def _remove_sqlite_sidecars(path: Path) -> None:
    for sidecar in _sqlite_sidecars(path):
        if sidecar.exists():
            sidecar.unlink()


def create_backup(database: Path, backup_dir: Path) -> Path:
    """Crea, verifica y publica atómicamente una copia online de SQLite."""
    source_path = _require_database(database)
    target_dir = backup_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _backup_name()
    temporary = target.with_suffix(target.suffix + ".partial")

    try:
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=30)
        destination = sqlite3.connect(temporary, timeout=30)
        try:
            source.backup(destination, pages=256, sleep=0.05)
            # El artefacto debe ser un único archivo transportable, aunque la
            # base de origen esté en WAL. Esta transición fuerza el checkpoint.
            destination.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            destination.close()
            source.close()
        check_database(temporary)
        os.replace(temporary, target)
        checksum = _sha256(target)
        target.with_suffix(target.suffix + ".sha256").write_text(
            f"{checksum}  {target.name}\n", encoding="ascii"
        )
        return target
    except (OSError, sqlite3.Error) as error:
        raise MaintenanceError(f"No se pudo crear la copia online: {error}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
        _remove_sqlite_sidecars(temporary)


def prune_backups(
    backup_dir: Path,
    retention_count: int,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> list[Path]:
    """Elimina copias que exceden cantidad o antigüedad configuradas."""
    target_dir = backup_dir.expanduser().resolve()
    if not target_dir.exists():
        return []
    backups = sorted(
        target_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - timedelta(days=retention_days).total_seconds()
    removed: list[Path] = []
    for index, backup in enumerate(backups):
        exceeds_count = retention_count > 0 and index >= retention_count
        exceeds_age = retention_days > 0 and backup.stat().st_mtime < cutoff
        if exceeds_count or exceeds_age:
            checksum = backup.with_suffix(backup.suffix + ".sha256")
            backup.unlink()
            if checksum.exists():
                checksum.unlink()
            removed.append(backup)
    return removed


def default_restore_destination(database: Path) -> Path:
    database = database.expanduser().resolve()
    return database.with_name(f"{database.stem}.restored{database.suffix or '.db'}")


def restore_backup(
    backup: Path,
    database: Path,
    destination: Path | None = None,
    *,
    overwrite: bool = False,
    app_stopped: bool = False,
) -> Path:
    """Restaura a otro archivo por defecto; protege cualquier reemplazo."""
    backup_path = _require_database(backup)
    check_database(backup_path)
    live_database = database.expanduser().resolve()
    target = (destination or default_restore_destination(live_database)).expanduser().resolve()
    replacing_live = target == live_database

    if replacing_live and not overwrite:
        raise MaintenanceError("Restaurar sobre la base configurada requiere --overwrite")
    if target.exists() and not overwrite:
        raise MaintenanceError(f"El destino ya existe; use --overwrite: {target}")
    if (replacing_live or target.exists()) and not app_stopped:
        raise MaintenanceError("Sobrescribir requiere detener la aplicación y declarar --app-stopped")

    target.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".partial", dir=target.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        source = sqlite3.connect(backup_path.as_uri() + "?mode=ro", uri=True, timeout=30)
        restored = sqlite3.connect(temporary, timeout=30)
        try:
            source.backup(restored, pages=256, sleep=0.05)
            # A restored snapshot cannot know which messages were sent later.
            # Quarantine all deliverable rows before the worker can see them.
            if restored.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reception_notifications'").fetchone():
                restored.execute("UPDATE reception_notifications SET status='REVISAR ENVIO', error='Base restaurada: conciliar correos antes de reintentar' WHERE status IN ('PENDIENTE ENVIO','ERROR','ENVIANDO')")
                restored.commit()
            restored.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            restored.close()
            source.close()
        check_database(temporary)
        if replacing_live or target.exists():
            _remove_sqlite_sidecars(target)
        os.replace(temporary, target)
        return target
    except (OSError, sqlite3.Error) as error:
        raise MaintenanceError(f"No se pudo restaurar la copia: {error}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
        _remove_sqlite_sidecars(temporary)


def _run_backup(args: argparse.Namespace) -> Path:
    backup = create_backup(args.database, args.backup_dir)
    removed = prune_backups(args.backup_dir, args.retention_count, args.retention_days)
    print(f"backup_ok path={backup} sha256={_sha256(backup)} removed={len(removed)}", flush=True)
    return backup


def run_schedule(args: argparse.Namespace) -> None:
    """Ejecuta una copia inmediata y luego repite hasta recibir SIGTERM/SIGINT."""
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop.is_set():
        try:
            _run_backup(args)
        except MaintenanceError as error:
            print(f"backup_error error={error}", file=sys.stderr, flush=True)
        stop.wait(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Copias, verificación y restauración SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="crear una copia online verificada")
    backup.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    backup.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    backup.add_argument("--retention-count", type=_non_negative_int, default=int(os.getenv("TRITON_BACKUP_RETENTION_COUNT", "30")))
    backup.add_argument("--retention-days", type=_non_negative_int, default=int(os.getenv("TRITON_BACKUP_RETENTION_DAYS", "30")))

    check = subparsers.add_parser("check", help="verificar una base o copia sin modificarla")
    check.add_argument("path", nargs="?", type=Path, default=DEFAULT_DATABASE)

    restore = subparsers.add_parser("restore", help="restaurar a un archivo separado por defecto")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="base activa; define el destino separado predeterminado")
    restore.add_argument("--destination", type=Path)
    restore.add_argument("--overwrite", action="store_true")
    restore.add_argument("--app-stopped", action="store_true", help="confirma que la aplicación está detenida")

    schedule = subparsers.add_parser("schedule", help="ejecutar el ciclo periódico de copias")
    schedule.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    schedule.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    schedule.add_argument("--interval", type=_positive_int, default=int(os.getenv("TRITON_BACKUP_INTERVAL_SECONDS", "86400")))
    schedule.add_argument("--retention-count", type=_non_negative_int, default=int(os.getenv("TRITON_BACKUP_RETENTION_COUNT", "30")))
    schedule.add_argument("--retention-days", type=_non_negative_int, default=int(os.getenv("TRITON_BACKUP_RETENTION_DAYS", "30")))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "backup":
            _run_backup(args)
        elif args.command == "check":
            result = check_database(args.path)
            print(f"check_ok path={result['path']} bytes={result['bytes']}")
        elif args.command == "restore":
            target = restore_backup(
                args.backup,
                args.database,
                args.destination,
                overwrite=args.overwrite,
                app_stopped=args.app_stopped,
            )
            print(f"restore_ok path={target}")
        elif args.command == "schedule":
            run_schedule(args)
    except MaintenanceError as error:
        print(f"maintenance_error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
