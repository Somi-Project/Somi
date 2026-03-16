from __future__ import annotations

from typing import Any, Iterable


def select_subagent_profile(
    objective: str,
    *,
    preferred: str = "",
    metadata: dict[str, Any] | None = None,
    available_profiles: Iterable[str] | None = None,
) -> str:
    available = [str(x or "").strip().lower() for x in list(available_profiles or []) if str(x or "").strip()]
    available_set = set(available)

    pref = str(preferred or "").strip().lower()
    if pref and pref in available_set:
        return pref

    text = str(objective or "").strip().lower()
    meta = dict(metadata or {})
    image_paths = list(meta.get("image_paths") or [])

    if image_paths and "data_gatherer" in available_set:
        return "data_gatherer"

    coding_markers = (
        "code",
        "python",
        "script",
        "function",
        "refactor",
        "debug",
        "fix",
        "patch",
        "test",
        "repo",
        "repository",
        "module",
        "class",
        "cli",
        "shell",
    )
    research_markers = (
        "research",
        "compare",
        "find",
        "search",
        "latest",
        "current",
        "news",
        "sources",
        "evidence",
        "web",
        "docs",
    )

    if any(marker in text for marker in coding_markers) and "coding_worker" in available_set:
        return "coding_worker"
    if any(marker in text for marker in research_markers) and "research_scout" in available_set:
        return "research_scout"
    if "data_gatherer" in available_set:
        return "data_gatherer"
    if "research_scout" in available_set:
        return "research_scout"
    if available:
        return available[0]
    return "research_scout"
