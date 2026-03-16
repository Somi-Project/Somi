from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workshop.toolbox.coding import preferred_python_command, resolve_workspace_path, resolve_workspace_root, run_command_in_workspace


def _string_list(items: Any) -> list[str]:
    return [str(x) for x in list(items or []) if str(x).strip()]


def run(args: dict[str, Any], ctx) -> dict[str, Any]:  # noqa: ARG001
    action = str(args.get("action") or "").strip().lower()

    try:
        root_path = resolve_workspace_root(
            workspace_root=str(args.get("workspace_root") or ""),
            session_id=str(args.get("session_id") or ""),
            user_id=str(args.get("user_id") or ""),
        )
        timeout_s = int(args.get("timeout_s") or 30)
        output_cap = int(args.get("output_cap") or 20000)

        if action == "run_python":
            inline_code = str(args.get("inline_code") or "")
            script_args = _string_list(args.get("script_args") or [])
            python_cmd = preferred_python_command(root_path)
            if inline_code:
                cmd = [*python_cmd, "-c", inline_code]
            else:
                script_path = resolve_workspace_path(root_path, str(args.get("script_path") or ""), require_exists=True)
                cmd = [*python_cmd, script_path.relative_to(root_path).as_posix(), *script_args]
            result = run_command_in_workspace(root_path, cmd, timeout_s=timeout_s, output_cap=output_cap)
            result["workspace_root"] = str(root_path)
            return result

        if action == "run_pytest":
            cmd = [*preferred_python_command(root_path), "-m", "pytest", "-q"]
            keyword = str(args.get("keyword") or "").strip()
            if keyword:
                cmd.extend(["-k", keyword])
            for item in _string_list(args.get("targets") or []):
                target = resolve_workspace_path(root_path, item, require_exists=True)
                cmd.append(target.relative_to(root_path).as_posix())
            result = run_command_in_workspace(root_path, cmd, timeout_s=timeout_s, output_cap=output_cap)
            result["workspace_root"] = str(root_path)
            return result

        return {"ok": False, "error": f"Unsupported action: {action}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
