from __future__ import annotations

from typing import Any


REGRESSION_PACKS: tuple[dict[str, Any], ...] = (
    {
        "id": "web",
        "label": "Web Search",
        "scenarios": [
            "latest info with explicit recency",
            "contextual follow-up open 2",
            "source-grounded summary contract",
        ],
    },
    {
        "id": "finance",
        "label": "Finance",
        "scenarios": [
            "currency conversion",
            "historical price follow-up",
            "finance news routing guard",
        ],
    },
    {
        "id": "reminder",
        "label": "Reminder",
        "scenarios": [
            "due reminder consumption",
            "heartbeat reminder provider",
            "task reminder projection",
        ],
    },
    {
        "id": "artifact",
        "label": "Artifact",
        "scenarios": [
            "artifact intent detection",
            "artifact store write and recall",
            "research brief degrade notice",
        ],
    },
    {
        "id": "automation",
        "label": "Automation",
        "scenarios": [
            "natural-language schedule parse",
            "delivery gateway dispatch",
            "automation status page render",
        ],
    },
    {
        "id": "subagent",
        "label": "Subagent",
        "scenarios": [
            "delegation profile dispatch",
            "child run snapshot persistence",
            "task-graph parent/child continuity",
        ],
    },
)


def list_regression_packs() -> list[dict[str, Any]]:
    return [dict(item) for item in REGRESSION_PACKS]
