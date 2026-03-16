from __future__ import annotations

from typing import Any, Dict


def _render_start_here_snapshot(snapshot: dict[str, Any]) -> str:
    lines = ["[Start Here]"]
    featured = list(snapshot.get("featured_recipes") or [])
    if featured:
        lines.append("Featured recipes:")
        for row in featured[:4]:
            lines.append(
                f"- {row.get('name')} [{row.get('primary_surface')}] -> /recipe {row.get('id')}"
            )
    agents = list(snapshot.get("agent_templates") or [])
    if agents:
        lines.append("")
        lines.append("Agent templates:")
        for row in agents[:4]:
            lines.append(f"- {row.get('name')}: {row.get('description')}")
    workflows = list(snapshot.get("workflow_templates") or [])
    if workflows:
        lines.append("")
        lines.append("Workflow templates:")
        for row in workflows[:3]:
            status = "ready" if row.get("manifest_available") else "guide"
            lines.append(f"- {row.get('name')} [{status}]")
    bundles = list(snapshot.get("recommended_bundles") or [])
    if bundles:
        lines.append("")
        lines.append("Recommended bundles:")
        for row in bundles[:4]:
            lines.append(f"- {row.get('name')}: tools ready {row.get('tool_ready_count', 0)}/{row.get('tool_total', 0)}")
    lines.append("")
    lines.append("Try:")
    lines.append("- /recipe coding_builder")
    lines.append("- /recipe research_operator")
    return "\n".join(lines)


def _render_recipe_detail(recipe: dict[str, Any]) -> str:
    lines = [
        f"[Recipe] {recipe.get('name')}",
        f"- Primary surface: {recipe.get('primary_surface') or 'chat'}",
        f"- Description: {recipe.get('description') or ''}",
        f"- Tools ready: {recipe.get('tool_ready_count', 0)}/{len(list(recipe.get('tools') or []))}",
    ]
    guide_steps = [str(item) for item in list(recipe.get("guide_steps") or []) if str(item).strip()]
    if guide_steps:
        lines.append("")
        lines.append("Guide steps:")
        for step in guide_steps[:4]:
            lines.append(f"- {step}")
    quick_actions = [str(item) for item in list(recipe.get("quick_actions") or []) if str(item).strip()]
    if quick_actions:
        lines.append("")
        lines.append("Quick actions:")
        for action in quick_actions[:4]:
            lines.append(f"- {action}")
    starter_prompt = str(recipe.get("starter_prompt") or "").strip()
    if starter_prompt:
        lines.append("")
        lines.append("Starter prompt:")
        lines.append(starter_prompt)
    return "\n".join(lines)


def _handle_starter_command_or_intent(
    self,
    prompt: str,
    *,
    active_user_id: str,
    source: str = "chat",
) -> Dict[str, Any]:
    text = str(prompt or "").strip()
    lower = text.lower()
    service = getattr(self, "start_here_service", None)
    if service is None:
        return {"handled": False}

    if lower in {"/starthere", "/start-here", "/recipes", "start here", "show me starter recipes"}:
        snapshot = service.build_snapshot()
        return {
            "handled": True,
            "response": _render_start_here_snapshot(snapshot),
            "turn_status": "completed",
            "event_type": "starter_guide",
            "event_name": "starter_snapshot",
            "event_payload": {"source": str(source or "chat"), "user_id": str(active_user_id or "")},
            "metadata": {"starter_surface": "chat"},
        }

    if lower.startswith("/recipe "):
        recipe_id = text.split(None, 1)[1].strip()
        recipe = service.describe_recipe(recipe_id)
        if recipe is None:
            return {
                "handled": True,
                "response": f"I couldn't find a recipe named '{recipe_id}'. Try /starthere.",
                "turn_status": "failed",
                "event_type": "starter_guide",
                "event_name": "recipe_missing",
                "event_payload": {"recipe_id": recipe_id},
                "metadata": {"starter_surface": "chat"},
            }
        return {
            "handled": True,
            "response": _render_recipe_detail(recipe),
            "turn_status": "completed",
            "event_type": "starter_guide",
            "event_name": "recipe_detail",
            "event_payload": {"recipe_id": recipe_id},
            "metadata": {"starter_surface": "chat", "recipe_id": recipe_id},
        }

    return {"handled": False}
