from __future__ import annotations

from typing import Any

from workshop.toolbox.stacks._async import run_coro_sync


def run_image_tooling(args: dict[str, Any], *, user_id: str = "default_user") -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()

    if action == "generate":
        spec = dict(args.get("spec") or {})
        if not spec:
            return {"ok": False, "error": "spec is required"}
        try:
            from workshop.toolbox.stacks.image_core.image_generate import generate_image

            attachments = generate_image(spec)
            return {"ok": True, "attachments": attachments or []}
        except Exception as exc:
            return {"ok": False, "error": f"image generation failed: {exc}"}

    if action == "analyze":
        image_path = str(args.get("image_path") or "").strip()
        if not image_path:
            return {"ok": False, "error": "image_path is required"}
        caption = str(args.get("caption") or "")

        try:
            from agents import Agent

            agent = Agent("Name: Somi")
            content = run_coro_sync(
                agent.analyze_image(
                    image_path=image_path,
                    caption=caption,
                    user_id=str(user_id or "default_user"),
                )
            )
            return {"ok": True, "content": content}
        except Exception as exc:
            return {"ok": False, "error": f"image analysis failed: {exc}"}

    return {"ok": False, "error": f"unsupported action: {action}"}

