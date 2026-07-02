from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from yourvpn_core.config import AppSettings
from yourvpn_core.version import __version__


class HealthStatus(BaseModel):
    service: str
    status: str = "ok"
    version: str = __version__
    environment: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)


def build_health_status(
    *,
    service: str,
    settings: AppSettings,
    details: dict[str, Any] | None = None,
) -> HealthStatus:
    return HealthStatus(
        service=service,
        environment=settings.environment,
        details=details or {},
    )
