from __future__ import annotations

from enum import IntEnum

from runtime.errors import PrivilegeError


class PrivilegeLevel(IntEnum):
    SAFE = 0
    ACTIVE = 1


def require_privilege(ctx, level: PrivilegeLevel) -> None:
    current = getattr(ctx, "privilege", PrivilegeLevel.SAFE)
    if int(current) < int(level):
        raise PrivilegeError(f"Privilege {current.name} too low; requires {level.name}")
