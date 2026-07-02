from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address, ip_network

from yourvpn_core.domain.enums import Role
from yourvpn_core.modules.errors import AuthorizationError


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: Role
    email: str | None = None


@dataclass(frozen=True)
class RequestContext:
    ip_address: str
    user_agent: str | None = None


@dataclass(frozen=True)
class GrantableAccessGroup:
    access_group_id: str
    is_high_privilege: bool = False


class AuthorizationModule:
    def require_role(self, actor: Actor, allowed_roles: set[Role]) -> None:
        if actor.role not in allowed_roles:
            raise AuthorizationError(f"Role {actor.role} is not allowed")

    def require_admin_ip_allowed(
        self,
        context: RequestContext,
        allowed_cidrs: list[str],
    ) -> None:
        if not allowed_cidrs:
            return

        try:
            source_ip = ip_address(context.ip_address)
        except ValueError as exc:
            raise AuthorizationError(f"IP {context.ip_address} is not valid") from exc
        if not any(source_ip in ip_network(cidr, strict=False) for cidr in allowed_cidrs):
            raise AuthorizationError(f"IP {context.ip_address} is not allowed for admin API")

    def can_grant_access_groups(
        self,
        actor: Actor,
        access_groups: list[GrantableAccessGroup],
    ) -> None:
        if any(group.is_high_privilege for group in access_groups) and actor.role != Role.ADMIN:
            raise AuthorizationError("Only admin can grant high-privilege access groups")

        self.require_role(actor, {Role.ADMIN, Role.APPROVER})
