import json
import os
import sqlite3
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from backend.services.notifications import (
    ERROR,
    PENDING,
    REVIEW,
    SENDING,
    SENT,
    GraphConfig,
    MicrosoftGraphTransport,
    RetryableNotificationError,
    init_notifications_schema,
    notification_summary,
    process_notifications,
    retry_notification,
)


ENABLED_ENV = {
    "TRITON_MAIL_ENABLED": "1",
    "TRITON_GRAPH_TENANT_ID": "tenant-test",
    "TRITON_GRAPH_CLIENT_ID": "client-test",
    "TRITON_GRAPH_CLIENT_SECRET": "secret-test",
}


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.db_path = Path(__file__).parent / f".notifications-{uuid.uuid4().hex}.db"
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE reception_shipments (id INTEGER PRIMARY KEY);
                CREATE TABLE reception_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id),
                    notification_type TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDIENTE ENVIO',
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT
                );
                INSERT INTO reception_shipments (id) VALUES (1);
                """
            )
            init_notifications_schema(connection)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue(self, recipient="persona@example.test"):
        with self.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO reception_notifications
                   (shipment_id, notification_type, recipient, subject, body,
                    status, created_at)
                   VALUES (1, 'PRUEBA', ?, 'Asunto', 'Cuerpo', ?, ?)""",
                (recipient, PENDING, "2026-09-05T12:00:00+00:00"),
            )
            return cursor.lastrowid

    def row(self, notification_id):
        with self.connection() as connection:
            return dict(
                connection.execute(
                    "SELECT * FROM reception_notifications WHERE id = ?",
                    (notification_id,),
                ).fetchone()
            )

    def test_success_uses_existing_recipient_and_marks_sent(self):
        notification_id = self.enqueue("destino.existente@example.test")
        delivered = []

        with patch.dict(os.environ, ENABLED_ENV, clear=True):
            result = process_notifications(
                self.db_path, transport=lambda notification: delivered.append(notification)
            )

        row = self.row(notification_id)
        self.assertEqual(SENT, row["status"])
        self.assertIsNotNone(row["sent_at"])
        self.assertEqual(1, row["attempt_count"])
        self.assertEqual("destino.existente@example.test", delivered[0]["recipient"])
        self.assertEqual(1, result["sent"])

    def test_permission_denial_is_terminal_error(self):
        notification_id = self.enqueue()
        requests = []

        class Response:
            status = 200

            def read(self):
                return b'{"access_token":"token-test"}'

            def getcode(self):
                return self.status

            def close(self):
                pass

        def opener(request, timeout):
            requests.append((request, timeout))
            if len(requests) == 1:
                return Response()
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                BytesIO(b'{"error":{"code":"ErrorAccessDenied"}}'),
            )

        graph_transport = MicrosoftGraphTransport(
            GraphConfig.from_environ(ENABLED_ENV), opener=opener
        )

        with patch.dict(os.environ, ENABLED_ENV, clear=True):
            result = process_notifications(self.db_path, transport=graph_transport)

        row = self.row(notification_id)
        self.assertEqual(ERROR, row["status"])
        self.assertEqual(403, row["last_http_status"])
        self.assertEqual(1, row["attempt_count"])
        self.assertEqual(1, result["errors"])
        self.assertIn("/oauth2/v2.0/token", requests[0][0].full_url)
        self.assertTrue(requests[1][0].full_url.endswith("/users/tomas.polo%40triton.com.pe/sendMail"))
        graph_payload = json.loads(requests[1][0].data.decode("utf-8"))
        self.assertEqual(
            "persona@example.test",
            graph_payload["message"]["toRecipients"][0]["emailAddress"]["address"],
        )

    def test_transient_failures_back_off_and_stop_at_bound(self):
        notification_id = self.enqueue()
        calls = []
        start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

        def unavailable(_notification):
            calls.append(1)
            raise RetryableNotificationError("Graph HTTP 503", http_status=503)

        with patch.dict(os.environ, ENABLED_ENV, clear=True):
            first = process_notifications(
                self.db_path,
                transport=unavailable,
                now=start,
                max_attempts=3,
                base_backoff_seconds=10,
            )
            too_early = process_notifications(
                self.db_path,
                transport=unavailable,
                now=start + timedelta(seconds=9),
                max_attempts=3,
                base_backoff_seconds=10,
            )
            second = process_notifications(
                self.db_path,
                transport=unavailable,
                now=start + timedelta(seconds=10),
                max_attempts=3,
                base_backoff_seconds=10,
            )
            third = process_notifications(
                self.db_path,
                transport=unavailable,
                now=start + timedelta(seconds=30),
                max_attempts=3,
                base_backoff_seconds=10,
            )

        row = self.row(notification_id)
        self.assertEqual(3, len(calls))
        self.assertEqual(1, first["retried"])
        self.assertEqual(0, too_early["claimed"])
        self.assertEqual(1, second["retried"])
        self.assertEqual(1, third["errors"])
        self.assertEqual(ERROR, row["status"])
        self.assertEqual(3, row["attempt_count"])

    def test_two_workers_do_not_send_the_same_row_twice(self):
        notification_id = self.enqueue()
        calls = []
        call_lock = threading.Lock()
        start_together = threading.Barrier(2)
        failures = []

        def slow_transport(notification):
            with call_lock:
                calls.append(notification["id"])
            time.sleep(0.05)

        def worker(name):
            try:
                start_together.wait()
                process_notifications(
                    self.db_path,
                    transport=slow_transport,
                    worker_id=name,
                    limit=1,
                    environ=ENABLED_ENV,
                )
            except Exception as error:  # pragma: no cover - se muestra en el assert
                failures.append(error)

        threads = [
            threading.Thread(target=worker, args=("worker-a",)),
            threading.Thread(target=worker, args=("worker-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([], failures)
        self.assertEqual([notification_id], calls)
        self.assertEqual(SENT, self.row(notification_id)["status"])

    def test_missing_or_disabled_config_leaves_row_pending(self):
        notification_id = self.enqueue()
        calls = []

        with patch.dict(os.environ, {}, clear=True):
            disabled = process_notifications(
                self.db_path, transport=lambda row: calls.append(row)
            )
        with patch.dict(os.environ, {"TRITON_MAIL_ENABLED": "1"}, clear=True):
            missing = process_notifications(
                self.db_path, transport=lambda row: calls.append(row)
            )

        self.assertEqual([], calls)
        self.assertEqual(PENDING, self.row(notification_id)["status"])
        self.assertIn("deshabilitado", disabled["config_error"])
        self.assertIn("Configuración incompleta", missing["config_error"])

    def test_ambiguous_failure_requires_explicit_admin_retry(self):
        notification_id = self.enqueue()

        def uncertain(_notification):
            raise RuntimeError("conexión perdida después de escribir")

        with patch.dict(os.environ, ENABLED_ENV, clear=True):
            process_notifications(self.db_path, transport=uncertain)
            not_repeated = process_notifications(self.db_path, transport=uncertain)

        self.assertEqual(REVIEW, self.row(notification_id)["status"])
        self.assertEqual(0, not_repeated["claimed"])

        with self.connection() as connection:
            reopened = retry_notification(connection, notification_id, "admin.test")
            summary = notification_summary(connection)
        self.assertEqual(PENDING, reopened["status"])
        self.assertEqual("admin.test", reopened["retry_requested_by"])
        self.assertEqual(1, reopened["manual_retry_count"])
        self.assertEqual(1, summary["by_status"][PENDING])

        with patch.dict(os.environ, ENABLED_ENV, clear=True):
            process_notifications(self.db_path, transport=lambda _notification: None)
        self.assertEqual(SENT, self.row(notification_id)["status"])

    def test_expired_sending_claim_moves_to_review_without_resend(self):
        notification_id = self.enqueue()
        start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        with self.connection() as connection:
            connection.execute(
                """UPDATE reception_notifications
                   SET status = ?, claimed_at = ?, claim_token = 'dead-worker'
                   WHERE id = ?""",
                (SENDING, start.isoformat(), notification_id),
            )

        calls = []
        result = process_notifications(
            self.db_path,
            transport=lambda row: calls.append(row),
            now=start + timedelta(seconds=901),
            claim_timeout_seconds=900,
            environ=ENABLED_ENV,
        )

        self.assertEqual([], calls)
        self.assertEqual(1, result["recovered_for_review"])
        self.assertEqual(REVIEW, self.row(notification_id)["status"])


if __name__ == "__main__":
    unittest.main()
