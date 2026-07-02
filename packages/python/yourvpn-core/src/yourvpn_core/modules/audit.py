from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from yourvpn_core.db.models import AuditLog


@dataclass(frozen=True)
class AuditEvent:
    action: str
    target_type: str
    target_id: str | None = None
    actor_user_id: str | None = None
    actor_type: str = "system"
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None


class AuditModule:
    def record(self, db: Session, event: AuditEvent) -> AuditLog:
        row = AuditLog(
            actor_user_id=event.actor_user_id,
            actor_type=event.actor_type,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            before_json=event.before_json,
            after_json=event.after_json,
            ip_address=event.ip_address,
            user_agent=event.user_agent,
        )
        db.add(row)
        db.flush()
        return row
