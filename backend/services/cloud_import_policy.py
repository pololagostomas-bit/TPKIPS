"""Request-local boundary: background Excel changes documents, not operator work."""
from contextvars import ContextVar

documentary_only = ContextVar('cloud_documentary_only', default=False)
