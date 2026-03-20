from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DIRECT_DISTRIBUTIONS = {"direct_download", "portable", "lan", "self_hosted", "github_release", "package_manager"}
EDGE_DISTRIBUTIONS = {"app_store", "managed_mobile", "managed_desktop", "hosted_web"}


@dataclass(frozen=True)
class SurfacePolicySignal:
    surface: str
    distribution: str = "direct_download"
    os_provider: str = ""
    age_signal_present: bool = False
    user_mode: str = "standard"
    requested_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfacePolicyDecision:
    surface: str
    distribution: str
    adapter_active: bool
    core_policy_scope: str
    enforcement_scope: str
    requires_age_signal: bool
    user_controlled: bool
    recommended_mode: str
    blocked_capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_surface_policy_signal(
    surface: str,
    *,
    distribution: str = "direct_download",
    os_provider: str = "",
    age_signal_present: bool = False,
    user_mode: str = "standard",
    requested_capabilities: list[str] | tuple[str, ...] | None = None,
) -> SurfacePolicySignal:
    return SurfacePolicySignal(
        surface=str(surface or "desktop").strip().lower() or "desktop",
        distribution=str(distribution or "direct_download").strip().lower() or "direct_download",
        os_provider=str(os_provider or "").strip().lower(),
        age_signal_present=bool(age_signal_present),
        user_mode=str(user_mode or "standard").strip().lower() or "standard",
        requested_capabilities=tuple(str(item).strip().lower() for item in list(requested_capabilities or []) if str(item).strip()),
    )


def evaluate_surface_policy(signal: SurfacePolicySignal) -> SurfacePolicyDecision:
    surface = str(signal.surface or "desktop").strip().lower() or "desktop"
    distribution = str(signal.distribution or "direct_download").strip().lower() or "direct_download"
    requested = tuple(str(item).strip().lower() for item in signal.requested_capabilities if str(item).strip())

    adapter_active = distribution in EDGE_DISTRIBUTIONS
    requires_age_signal = adapter_active and surface in {"ios", "android", "mobile_app", "app_store_client"}
    blocked: list[str] = []
    notes: list[str] = []
    recommended_mode = "core_default"

    if distribution in DIRECT_DISTRIBUTIONS:
        notes.append("Surface uses the sovereign core path with no mandatory centralized identity layer.")
        notes.append("Any compliance logic must remain optional and client-local.")
    elif adapter_active:
        recommended_mode = "edge_adapter"
        notes.append("This surface may require client-edge compatibility handling, but the core runtime stays unchanged.")
        notes.append("Do not store central identity or age records in Somi Core by default.")
        if requires_age_signal and not bool(signal.age_signal_present):
            notes.append("If the distribution layer demands age signaling, keep it coarse and isolated to this client.")
        if "payments" in requested or "external_purchase" in requested:
            blocked.append("payments")
            notes.append("Financial actions remain human-approved regardless of surface policy.")
    else:
        notes.append("Unknown distribution type: defaulting to sovereign-core posture with optional adapter hooks only.")

    return SurfacePolicyDecision(
        surface=surface,
        distribution=distribution,
        adapter_active=adapter_active,
        core_policy_scope="core",
        enforcement_scope="surface_only" if adapter_active else "none",
        requires_age_signal=requires_age_signal,
        user_controlled=True,
        recommended_mode=recommended_mode,
        blocked_capabilities=tuple(blocked),
        notes=tuple(notes),
    )


def build_distribution_sovereignty_snapshot(
    *,
    signals: list[SurfacePolicySignal] | None = None,
) -> dict[str, Any]:
    rows = [evaluate_surface_policy(signal).as_dict() for signal in list(signals or [])]
    return {
        "core_identity": "self_hosted_local_first",
        "central_identity_required": False,
        "surface_count": len(rows),
        "rows": rows,
        "principles": [
            "Preserve cognition and execution policy in the self-hosted core.",
            "Keep any distribution-compatibility handling isolated to the affected surface.",
            "Do not require centralized identity storage by default.",
        ],
    }
