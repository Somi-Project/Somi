from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeProfile:
    profile_id: str
    display_name: str
    description: str
    allowed_backends: tuple[str, ...]
    default_model_profile: str
    max_risk_tier: str
    delivery_channels: tuple[str, ...]
    rollout_gates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "description": self.description,
            "allowed_backends": list(self.allowed_backends),
            "default_model_profile": self.default_model_profile,
            "max_risk_tier": self.max_risk_tier,
            "delivery_channels": list(self.delivery_channels),
            "rollout_gates": dict(self.rollout_gates or {}),
            "metadata": dict(self.metadata or {}),
        }


DEFAULT_RUNTIME_PROFILES: tuple[RuntimeProfile, ...] = (
    RuntimeProfile(
        profile_id="local_workstation",
        display_name="Local Workstation",
        description="Default local-first profile for consumer-grade desktops and laptops.",
        allowed_backends=("local",),
        default_model_profile="balanced",
        max_risk_tier="MEDIUM",
        delivery_channels=("gui", "desktop", "chat"),
        rollout_gates={"required_executables": ("python",), "min_memory_gb": 8, "consumer_safe": True},
        metadata={"priority": 1},
    ),
    RuntimeProfile(
        profile_id="homelab_node",
        display_name="Homelab Node",
        description="A stronger always-on node that may expose local Docker workers and background delivery.",
        allowed_backends=("local", "docker"),
        default_model_profile="throughput",
        max_risk_tier="HIGH",
        delivery_channels=("desktop", "heartbeat", "telegram"),
        rollout_gates={"required_executables": ("python",), "optional_executables": ("docker",), "min_memory_gb": 16},
        metadata={"priority": 2},
    ),
    RuntimeProfile(
        profile_id="remote_worker",
        display_name="Remote Worker",
        description="A remote execution profile for trusted nodes reached over SSH.",
        allowed_backends=("remote", "docker"),
        default_model_profile="server_balanced",
        max_risk_tier="MEDIUM",
        delivery_channels=("heartbeat", "telegram"),
        rollout_gates={"required_executables": ("ssh",), "min_memory_gb": 4},
        metadata={"priority": 3},
    ),
    RuntimeProfile(
        profile_id="edge_worker",
        display_name="Edge Worker",
        description="A low-risk, low-overhead profile for constrained edge and field devices.",
        allowed_backends=("local",),
        default_model_profile="edge_low_memory",
        max_risk_tier="LOW",
        delivery_channels=("heartbeat", "telegram"),
        rollout_gates={"required_executables": ("python",), "consumer_safe": True},
        metadata={"priority": 4},
    ),
)


def list_profiles() -> list[RuntimeProfile]:
    return list(DEFAULT_RUNTIME_PROFILES)


def profile_map() -> dict[str, RuntimeProfile]:
    return {profile.profile_id: profile for profile in DEFAULT_RUNTIME_PROFILES}


def get_profile(profile_id: str) -> RuntimeProfile | None:
    return profile_map().get(str(profile_id or "").strip().lower())
