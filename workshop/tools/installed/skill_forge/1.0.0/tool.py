from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from workshop.skills.forge import SkillForgeService


def run(args: dict[str, object], ctx) -> dict[str, object]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()
    service = SkillForgeService()

    try:
        if action == "create_draft":
            capability = str(args.get("capability") or "").strip()
            objective = str(args.get("objective") or args.get("prompt") or "").strip()
            if not capability and not objective:
                return {"ok": False, "error": "capability or objective is required"}
            draft = service.create_draft(
                actor=str(args.get("actor") or "operator"),
                capability=capability or objective,
                skill_name=str(args.get("skill_name") or capability or "").strip(),
                description=str(args.get("description") or "").strip(),
                objective=objective or capability,
                template_id=str(args.get("template_id") or "").strip(),
                dependencies=dict(args.get("dependencies") or {}),
                dispatch=dict(args.get("dispatch") or {}),
                source=str(args.get("source") or "tool"),
            )
            return {"ok": True, "draft": draft}

        if action == "suggest_gap":
            suggestion = service.suggest_skill_gap(
                prompt=str(args.get("prompt") or ""),
                user_id=str(args.get("user_id") or "default_user"),
                source=str(args.get("source") or "tool"),
                capability=str(args.get("capability") or ""),
                profile_key=str(args.get("profile_key") or "python"),
            )
            return {"ok": True, "suggestion": suggestion or {}}

        if action == "review_draft":
            return {"ok": True, "review": service.review_draft(str(args.get("draft_id") or ""))}

        if action == "approve_install":
            return {"ok": True, "result": service.approve_install(str(args.get("draft_id") or ""), actor=str(args.get("actor") or "operator"))}

        if action == "reject_draft":
            return {
                "ok": True,
                "draft": service.reject_draft(
                    str(args.get("draft_id") or ""),
                    actor=str(args.get("actor") or "operator"),
                    reason=str(args.get("reason") or ""),
                ),
            }

        if action == "list_drafts":
            return {"ok": True, "drafts": service.list_drafts(limit=int(args.get("limit") or 12))}

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
