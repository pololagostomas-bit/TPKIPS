"""Envío durable de la bandeja ``reception_notifications`` por Microsoft Graph.

El módulo no habilita correo por sí solo. Incluso con credenciales presentes,
``TRITON_MAIL_ENABLED`` debe valer exactamente ``1`` para reclamar una fila.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


PENDING = "PENDIENTE ENVIO"
SENDING = "ENVIANDO"
SENT = "ENVIADO"
ERROR = "ERROR"
REVIEW = "REVISAR ENVIO"
STATUSES = (PENDING, SENDING, SENT, ERROR, REVIEW)

DEFAULT_SENDER = "tomas.polo@triton.com.pe"
DEFAULT_GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_BACKOFF_SECONDS = 60
DEFAULT_MAX_BACKOFF_SECONDS = 3600
DEFAULT_CLAIM_TIMEOUT_SECONDS = 900
DEFAULT_HTTP_TIMEOUT_SECONDS = 30


class NotificationError(Exception):
    """Base para errores de entrega que se pueden guardar sin exponer secretos."""


class RetryableNotificationError(NotificationError):
    """Graph confirmó un fallo temporal; la fila puede reintentarse con backoff."""

    def __init__(self, message, *, retry_after_seconds=None, http_status=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status


class PermanentNotificationError(NotificationError):
    """Fallo definitivo (por ejemplo, aplicación sin permiso Mail.Send)."""

    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


class AmbiguousNotificationError(NotificationError):
    """No se puede probar si Graph aceptó el mensaje; requiere revisión humana."""


@dataclass(frozen=True)
class GraphConfig:
    enabled: bool
    tenant_id: str
    client_id: str
    client_secret: str
    sender: str = DEFAULT_SENDER
    graph_endpoint: str = DEFAULT_GRAPH_ENDPOINT
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS

    @classmethod
    def from_environ(cls, environ=None):
        values = os.environ if environ is None else environ

        def configured(primary, fallback, default=""):
            return str(values.get(primary) or values.get(fallback) or default).strip()

        return cls(
            enabled=str(values.get("TRITON_MAIL_ENABLED", "")).strip() == "1",
            tenant_id=configured("TRITON_GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
            client_id=configured("TRITON_GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
            client_secret=configured("TRITON_GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
            sender=str(values.get("TRITON_MAIL_FROM") or DEFAULT_SENDER).strip(),
            graph_endpoint=str(
                values.get("TRITON_GRAPH_ENDPOINT") or DEFAULT_GRAPH_ENDPOINT
            ).strip().rstrip("/"),
            timeout_seconds=_positive_int(
                values.get("TRITON_MAIL_HTTP_TIMEOUT_SECONDS"),
                DEFAULT_HTTP_TIMEOUT_SECONDS,
            ),
        )

    @property
    def missing(self):
        missing = []
        if not self.tenant_id:
            missing.append("TRITON_GRAPH_TENANT_ID/AZURE_TENANT_ID")
        if not self.client_id:
            missing.append("TRITON_GRAPH_CLIENT_ID/AZURE_CLIENT_ID")
        if not self.client_secret:
            missing.append("TRITON_GRAPH_CLIENT_SECRET/AZURE_CLIENT_SECRET")
        if not self.sender:
            missing.append("TRITON_MAIL_FROM")
        return missing


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _utc_now(value=None):
    current = value() if callable(value) else value
    current = current or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0)


def _timestamp(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _columns(connection, table):
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _ensure_column(connection, column, definition):
    if column not in _columns(connection, "reception_notifications"):
        connection.execute(
            f"ALTER TABLE reception_notifications ADD COLUMN {column} {definition}"
        )


def init_notifications_schema(connection):
    """Crea o amplía la bandeja existente sin reconstruir ni perder filas."""
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reception_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES reception_shipments(id) ON DELETE CASCADE,
            notification_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDIENTE ENVIO',
            created_at TEXT NOT NULL,
            sent_at TEXT,
            error TEXT
        )
        """
    )
    additions = {
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "next_attempt_at": "TEXT",
        "claimed_at": "TEXT",
        "claim_token": "TEXT",
        "last_attempt_at": "TEXT",
        "last_http_status": "INTEGER",
        "manual_retry_count": "INTEGER NOT NULL DEFAULT 0",
        "retry_requested_at": "TEXT",
        "retry_requested_by": "TEXT",
    }
    for column, definition in additions.items():
        _ensure_column(connection, column, definition)
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_reception_notifications_delivery
           ON reception_notifications(status, next_attempt_at, id)"""
    )


def _response_text(response):
    raw = response.read()
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


def _safe_error_body(error):
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    body = " ".join(body.split())
    return body[:500]


def _retry_after_seconds(headers):
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0, int((retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def _http_failure(error, action):
    status = int(error.code)
    try:
        detail = _safe_error_body(error)
    finally:
        error.close()
    message = f"Microsoft Graph rechazó {action} con HTTP {status}"
    if detail:
        message = f"{message}: {detail}"
    if status in {408, 429} or 500 <= status <= 599:
        return RetryableNotificationError(
            message,
            retry_after_seconds=_retry_after_seconds(error.headers),
            http_status=status,
        )
    return PermanentNotificationError(message, http_status=status)


class MicrosoftGraphTransport:
    """Cliente mínimo de Graph con client credentials y ``urllib`` estándar."""

    def __init__(self, config, opener=urlopen):
        self.config = config
        self.opener = opener
        self._access_token = None

    def _open(self, request, action, *, ambiguous_network):
        try:
            return self.opener(request, timeout=self.config.timeout_seconds)
        except HTTPError as error:
            raise _http_failure(error, action) from error
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            message = f"Fallo de red al {action}: {error}"
            if ambiguous_network:
                raise AmbiguousNotificationError(message) from error
            raise RetryableNotificationError(message) from error

    def _token(self):
        if self._access_token:
            return self._access_token
        token_url = (
            "https://login.microsoftonline.com/"
            f"{quote(self.config.tenant_id, safe='')}/oauth2/v2.0/token"
        )
        request = Request(
            token_url,
            data=urlencode(
                {
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                }
            ).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        response = self._open(
            request,
            "solicitar el token de aplicación",
            ambiguous_network=False,
        )
        try:
            payload = json.loads(_response_text(response))
        except (ValueError, TypeError) as error:
            raise PermanentNotificationError(
                "La respuesta del token de Microsoft no fue JSON válido"
            ) from error
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise PermanentNotificationError(
                "La respuesta del token de Microsoft no incluyó access_token"
            )
        self._access_token = token
        return token

    def send(self, notification):
        payload = {
            "message": {
                "subject": str(notification["subject"]),
                "body": {
                    "contentType": "Text",
                    "content": str(notification["body"]),
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": str(notification["recipient"]).strip()
                        }
                    }
                ],
            }
        }
        endpoint = (
            f"{self.config.graph_endpoint}/users/"
            f"{quote(self.config.sender, safe='')}/sendMail"
        )
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        response = self._open(request, "enviar el correo", ambiguous_network=True)
        try:
            status = int(getattr(response, "status", response.getcode()))
            _response_text(response)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        if not 200 <= status <= 299:
            raise PermanentNotificationError(
                f"Microsoft Graph devolvió HTTP {status} al enviar el correo",
                http_status=status,
            )


def _connect(db_path):
    connection = sqlite3.connect(str(db_path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _recover_stale_claims(connection, current, claim_timeout_seconds):
    cutoff = _timestamp(current - timedelta(seconds=claim_timeout_seconds))
    cursor = connection.execute(
        """UPDATE reception_notifications
           SET status = ?, error = ?, claim_token = NULL
           WHERE status = ? AND (claimed_at IS NULL OR claimed_at <= ?)""",
        (
            REVIEW,
            "Claim vencido: el proceso terminó sin confirmar si Graph aceptó el correo",
            SENDING,
            cutoff,
        ),
    )
    connection.commit()
    return cursor.rowcount


def _claim_one(connection, current, worker_id, max_attempts):
    timestamp = _timestamp(current)
    token = f"{worker_id}:{uuid.uuid4().hex}"
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            """SELECT id
               FROM reception_notifications
               WHERE status = ?
                 AND attempt_count < ?
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY COALESCE(next_attempt_at, created_at), id
               LIMIT 1""",
            (PENDING, max_attempts, timestamp),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        cursor = connection.execute(
            """UPDATE reception_notifications
               SET status = ?, claim_token = ?, claimed_at = ?,
                   last_attempt_at = ?, attempt_count = attempt_count + 1,
                   next_attempt_at = NULL, error = NULL
               WHERE id = ? AND status = ?""",
            (SENDING, token, timestamp, timestamp, row["id"], PENDING),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        claimed = connection.execute(
            "SELECT * FROM reception_notifications WHERE id = ?", (row["id"],)
        ).fetchone()
        connection.commit()
        return claimed
    except Exception:
        connection.rollback()
        raise


def _finish_success(connection, row, current):
    cursor = connection.execute(
        """UPDATE reception_notifications
           SET status = ?, sent_at = ?, error = NULL, next_attempt_at = NULL,
               claimed_at = NULL, claim_token = NULL, last_http_status = 202
           WHERE id = ? AND status = ? AND claim_token = ?""",
        (SENT, _timestamp(current), row["id"], SENDING, row["claim_token"]),
    )
    connection.commit()
    if cursor.rowcount != 1:
        raise RuntimeError("Se perdió el claim después de que Graph aceptó el correo")


def _finish_failure(
    connection,
    row,
    current,
    error,
    max_attempts,
    base_backoff_seconds,
    max_backoff_seconds,
):
    http_status = getattr(error, "http_status", None)
    if isinstance(error, RetryableNotificationError) and row["attempt_count"] < max_attempts:
        exponential = base_backoff_seconds * (2 ** (row["attempt_count"] - 1))
        requested = error.retry_after_seconds or 0
        delay = min(max_backoff_seconds, max(exponential, requested))
        status = PENDING
        next_attempt_at = _timestamp(current + timedelta(seconds=delay))
    elif isinstance(error, (PermanentNotificationError, RetryableNotificationError)):
        status = ERROR
        next_attempt_at = None
    else:
        status = REVIEW
        next_attempt_at = None
    cursor = connection.execute(
        """UPDATE reception_notifications
           SET status = ?, error = ?, next_attempt_at = ?, claimed_at = NULL,
               claim_token = NULL, last_http_status = ?
           WHERE id = ? AND status = ? AND claim_token = ?""",
        (
            status,
            str(error)[:1000],
            next_attempt_at,
            http_status,
            row["id"],
            SENDING,
            row["claim_token"],
        ),
    )
    connection.commit()
    if cursor.rowcount != 1:
        raise RuntimeError("Se perdió el claim al registrar el fallo del correo")
    return status


def _deliver(transport, row):
    notification = dict(row)
    sender = getattr(transport, "send", None)
    if sender is not None:
        return sender(notification)
    return transport(notification)


def process_notifications(
    db_path,
    *,
    transport=None,
    limit=20,
    now=None,
    worker_id=None,
    environ=None,
    max_attempts=None,
    base_backoff_seconds=None,
    max_backoff_seconds=None,
    claim_timeout_seconds=None,
):
    """Procesa hasta ``limit`` filas debidas y devuelve contadores del ciclo.

    El transporte inyectable debe ser invocable con el diccionario de la fila o
    exponer ``send(notification)``. Esto permite probar sin tocar la red.
    """
    config = GraphConfig.from_environ(environ)
    result = {
        "claimed": 0,
        "sent": 0,
        "retried": 0,
        "errors": 0,
        "review": 0,
        "recovered_for_review": 0,
        "config_error": None,
    }
    current = _utc_now(now)
    max_attempts = _positive_int(max_attempts, DEFAULT_MAX_ATTEMPTS)
    base_backoff_seconds = _positive_int(
        base_backoff_seconds, DEFAULT_BASE_BACKOFF_SECONDS
    )
    max_backoff_seconds = _positive_int(
        max_backoff_seconds, DEFAULT_MAX_BACKOFF_SECONDS
    )
    claim_timeout_seconds = _positive_int(
        claim_timeout_seconds, DEFAULT_CLAIM_TIMEOUT_SECONDS
    )
    limit = max(0, int(limit))
    worker_id = str(worker_id or f"worker-{os.getpid()}")

    with closing(_connect(db_path)) as connection:
        init_notifications_schema(connection)
        connection.commit()
        result["recovered_for_review"] = _recover_stale_claims(
            connection, current, claim_timeout_seconds
        )
        if not config.enabled:
            result["config_error"] = "Correo deshabilitado: TRITON_MAIL_ENABLED debe ser 1"
            return result
        if config.missing:
            result["config_error"] = "Configuración incompleta: " + ", ".join(config.missing)
            return result
        active_transport = transport or MicrosoftGraphTransport(config)
        for _ in range(limit):
            row = _claim_one(connection, current, worker_id, max_attempts)
            if row is None:
                break
            result["claimed"] += 1
            try:
                _deliver(active_transport, row)
            except (PermanentNotificationError, RetryableNotificationError) as error:
                final_status = _finish_failure(
                    connection,
                    row,
                    current,
                    error,
                    max_attempts,
                    base_backoff_seconds,
                    max_backoff_seconds,
                )
                if final_status == PENDING:
                    result["retried"] += 1
                else:
                    result["errors"] += 1
            except Exception as error:
                # Un error desconocido puede ocurrir después de entregar bytes a
                # Graph. No se reintenta automáticamente para evitar duplicados.
                _finish_failure(
                    connection,
                    row,
                    current,
                    AmbiguousNotificationError(f"Resultado ambiguo del transporte: {error}"),
                    max_attempts,
                    base_backoff_seconds,
                    max_backoff_seconds,
                )
                result["review"] += 1
            else:
                _finish_success(connection, row, current)
                result["sent"] += 1
    return result


def notification_summary(connection):
    """Resumen estable para una futura ruta administrativa."""
    init_notifications_schema(connection)
    counts = {status: 0 for status in STATUSES}
    other = 0
    for row in connection.execute(
        "SELECT status, COUNT(*) AS quantity FROM reception_notifications GROUP BY status"
    ):
        if row["status"] in counts:
            counts[row["status"]] = row["quantity"]
        else:
            other += row["quantity"]
    return {
        "total": sum(counts.values()) + other,
        "by_status": counts,
        "other": other,
    }


def retry_notification(connection, notification_id, actor):
    """Reabre explícitamente un ERROR/REVISAR ENVIO y registra al administrador."""
    init_notifications_schema(connection)
    actor = str(actor or "").strip()
    if not actor:
        raise ValueError("El actor administrativo es obligatorio")
    row = connection.execute(
        "SELECT id, status FROM reception_notifications WHERE id = ?",
        (notification_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Notificación no encontrada")
    if row["status"] not in {ERROR, REVIEW}:
        raise ValueError("Solo se puede reintentar una notificación en ERROR o REVISAR ENVIO")
    requested_at = _timestamp(_utc_now())
    connection.execute(
        """UPDATE reception_notifications
           SET status = ?, attempt_count = 0, next_attempt_at = NULL,
               claimed_at = NULL, claim_token = NULL, error = NULL,
               last_http_status = NULL,
               manual_retry_count = manual_retry_count + 1,
               retry_requested_at = ?, retry_requested_by = ?
           WHERE id = ?""",
        (PENDING, requested_at, actor, notification_id),
    )
    return dict(
        connection.execute(
            "SELECT * FROM reception_notifications WHERE id = ?", (notification_id,)
        ).fetchone()
    )
