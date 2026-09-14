"""Pruebas aisladas para copias y restauración SQLite."""

import os
import shutil
import sqlite3
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.maintenance import (
    MaintenanceError,
    check_database,
    create_backup,
    default_restore_destination,
    prune_backups,
    restore_backup,
)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        qa_root = Path(__file__).resolve().parents[1] / "qa"
        qa_root.mkdir(parents=True, exist_ok=True)
        self.root = qa_root / f"maintenance-test-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.database = self.root / "qa.db"
        self.backup_dir = self.root / "backups"
        self.connection = sqlite3.connect(self.database)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE inventory (sku TEXT PRIMARY KEY, quantity INTEGER)")
        self.connection.execute("INSERT INTO inventory VALUES ('QA-001', 7)")
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        shutil.rmtree(self.root)

    def test_online_backup_includes_committed_wal_data_and_is_valid(self):
        backup = create_backup(self.database, self.backup_dir)

        self.assertEqual(check_database(backup)["status"], "ok")
        with closing(sqlite3.connect(backup)) as copied:
            self.assertEqual(copied.execute("SELECT * FROM inventory").fetchone(), ("QA-001", 7))
        self.assertTrue(backup.with_suffix(".db.sha256").is_file())
        self.assertFalse(backup.with_suffix(".db.partial").exists())
        self.assertFalse(Path(f"{backup.with_suffix('.db.partial')}-wal").exists())
        self.assertFalse(Path(f"{backup.with_suffix('.db.partial')}-shm").exists())

    def test_check_does_not_create_missing_database(self):
        missing = self.root / "missing.db"
        with self.assertRaises(MaintenanceError):
            check_database(missing)
        self.assertFalse(missing.exists())

    def test_check_rejects_a_wrong_checksum(self):
        backup = create_backup(self.database, self.backup_dir)
        backup.with_suffix(".db.sha256").write_text(
            f"{'0' * 64}  {backup.name}\n", encoding="ascii"
        )

        with self.assertRaisesRegex(MaintenanceError, "checksum"):
            check_database(backup)

    def test_restore_defaults_to_separate_destination(self):
        backup = create_backup(self.database, self.backup_dir)
        target = restore_backup(backup, self.database)

        self.assertEqual(target, default_restore_destination(self.database))
        self.assertNotEqual(target, self.database)
        with closing(sqlite3.connect(target)) as restored:
            self.assertEqual(restored.execute("SELECT quantity FROM inventory").fetchone()[0], 7)

    def test_existing_destination_requires_overwrite_and_stopped_app(self):
        backup = create_backup(self.database, self.backup_dir)
        target = self.root / "existing.db"
        sqlite3.connect(target).close()

        with self.assertRaisesRegex(MaintenanceError, "--overwrite"):
            restore_backup(backup, self.database, target)
        with self.assertRaisesRegex(MaintenanceError, "--app-stopped"):
            restore_backup(backup, self.database, target, overwrite=True)
        restored = restore_backup(
            backup, self.database, target, overwrite=True, app_stopped=True
        )
        self.assertEqual(check_database(restored)["status"], "ok")

    def test_live_database_requires_both_explicit_guards(self):
        backup = create_backup(self.database, self.backup_dir)

        with self.assertRaisesRegex(MaintenanceError, "--overwrite"):
            restore_backup(backup, self.database, self.database)
        with self.assertRaisesRegex(MaintenanceError, "--app-stopped"):
            restore_backup(backup, self.database, self.database, overwrite=True)

    def test_in_place_restore_removes_stale_wal_sidecars(self):
        backup = create_backup(self.database, self.backup_dir)
        self.connection.close()
        self.connection = sqlite3.connect(":memory:")
        Path(f"{self.database}-wal").write_bytes(b"stale")
        Path(f"{self.database}-shm").write_bytes(b"stale")

        restore_backup(
            backup,
            self.database,
            self.database,
            overwrite=True,
            app_stopped=True,
        )

        self.assertFalse(Path(f"{self.database}-wal").exists())
        self.assertFalse(Path(f"{self.database}-shm").exists())
        self.assertEqual(check_database(self.database)["status"], "ok")

    def test_retention_removes_old_and_excess_backups_with_checksums(self):
        files = []
        for index in range(3):
            path = self.backup_dir / f"triton-2026010{index + 1}T000000000000Z.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"backup")
            path.with_suffix(".db.sha256").write_text("hash\n", encoding="ascii")
            timestamp = datetime(2026, 1, index + 1, tzinfo=timezone.utc).timestamp()
            os.utime(path, (timestamp, timestamp))
            files.append(path)

        removed = prune_backups(
            self.backup_dir,
            retention_count=2,
            retention_days=0,
            now=datetime(2026, 1, 4, tzinfo=timezone.utc),
        )

        self.assertEqual(removed, [files[0]])
        self.assertFalse(files[0].exists())
        self.assertFalse(files[0].with_suffix(".db.sha256").exists())


if __name__ == "__main__":
    unittest.main()
