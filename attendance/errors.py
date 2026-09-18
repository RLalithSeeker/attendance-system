"""Attendance module — typed application errors and standard envelope.

Errors are serialised as ``{"error": {"code": ..., "message": ..., "request_id": ...}}``
per the API contract. HTTP mapping happens at the router layer (see routers.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AttendanceError(Exception):
    """Base error for the attendance domain.

    code      stable machine code (contract: 400/401/403/404/409/422/503)
    http      HTTP status to return
    message   human-safe message (never leaks other identities/scores)
    request_id  correlation id attached at the router
    """

    code: str = "internal_error"
    http: int = 500
    message: str = "Internal error."
    request_id: Optional[str] = None
    detail: Optional[dict] = field(default=None)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.code}: {self.message}"


class NotFoundError(AttendanceError):
    def __init__(self, message: str = "Not found."):
        super().__init__(code="not_found", http=404, message=message)


class ForbiddenError(AttendanceError):
    def __init__(self, message: str = "Forbidden."):
        super().__init__(code="forbidden", http=403, message=message)


class UnauthorizedError(AttendanceError):
    def __init__(self, message: str = "Authentication required."):
        super().__init__(code="unauthorized", http=401, message=message)


class ConflictError(AttendanceError):
    def __init__(self, message: str = "Conflict."):
        super().__init__(code="conflict", http=409, message=message)


class ValidationError(AttendanceError):
    def __init__(self, message: str = "Invalid request.", detail: Optional[dict] = None):
        super().__init__(code="validation_error", http=422, message=message, detail=detail)


class MatcherUnavailableError(AttendanceError):
    def __init__(self, message: str = "Face matcher unavailable."):
        super().__init__(code="matcher_unavailable", http=503, message=message)