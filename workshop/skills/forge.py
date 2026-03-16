from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import skillssettings

from .forge_store import SkillForgeStore
from .forge_templates import _slug, build_template_files, choose_template
from .gating import check_eligibility
from .manager import SkillManager
from .parser import SkillParseError, parse_skill_md
from .registry import settings_dict, sys_platform
from .security_scanner import scan_directory_with_summary, should_block


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _friendly_name(capability: str) -> str:
    text = str(capability or "").strip()
    return text.title() if text else "Skill Draft"


class SkillForgeService:
    def __init__(
        self,
        *,
        cfg: dict[str, Any] | None = None,
        store: SkillForgeStore | None = None,
        manager: SkillManager | None = None,
    ) -> None:
        self.cfg = dict(cfg or settings_dict())
        self.store = store or SkillForgeStore(
            root_dir=self.cfg.get("SKILLS_FORGE_ROOT", getattr(skillssettings, "SKILLS_FORGE_ROOT", "sessions/skills/forge")),
            drafts_dir=self.cfg.get("SKILLS_DRAFTS_DIR", getattr(skillssettings, "SKILLS_DRAFTS_DIR", "sessions/skills/forge/workspace")),
        )
        self.manager = manager or SkillManager(cfg=self.cfg)

    def suggest_skill_gap(
        self,
        *,
        prompt: str,
        user_id: str = "default_user",
        source: str = "chat",
        capability: str = "",
        profile_key: str = "python",
        available_runtime_keys: set[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        if str(capability or "").strip():
            hint = {
                "capability": str(capability).strip(),
                "skill_name": _friendly_name(capability),
                "description": f"Draft skill for {str(capability).strip()}.",
                "profile_key": str(profile_key or "python"),
            }
        else:
            from workshop.toolbox.coding.skill_drafts import detect_skill_gap

            hint = detect_skill_gap(
                prompt,
                profile_key=str(profile_key or "python"),
                available_runtime_keys=available_runtime_keys or set(),
            )
        if not isinstance(hint, dict) or not str(hint.get("capability") or "").strip():
            return None

        signal = self.store.record_gap_signal(
            user_id=str(user_id or "default_user"),
            capability=str(hint.get("capability") or ""),
            prompt=str(prompt or ""),
            source=str(source or "chat"),
        )
        threshold = max(1, int(self.cfg.get("SKILLS_FORGE_PROPOSAL_THRESHOLD", getattr(skillssettings, "SKILLS_FORGE_PROPOSAL_THRESHOLD", 2)) or 2))
        proposal_ready = bool(force or int(signal.get("count") or 0) >= threshold)
        return {
            **dict(hint),
            "times_seen": int(signal.get("count") or 0),
            "proposal_ready": proposal_ready,
            "message": (
                f"I've seen this capability gap {int(signal.get('count') or 0)} time(s). "
                f"{'A dedicated skill draft is ready for review.' if proposal_ready else 'I will wait for one more repeat before prompting.'}"
            ),
        }

    def create_draft(
        self,
        *,
        actor: str,
        capability: str,
        objective: str,
        skill_name: str = "",
        description: str = "",
        template_id: str = "",
        dependencies: dict[str, Any] | None = None,
        dispatch: dict[str, Any] | None = None,
        source: str = "chat",
    ) -> dict[str, Any]:
        draft_id = f"draft_{uuid.uuid4().hex[:12]}"
        capability_text = str(capability or "general capability").strip() or "general capability"
        skill_name_text = str(skill_name or _friendly_name(capability_text)).strip() or _friendly_name(capability_text)
        skill_key = _slug(skill_name_text)
        template = str(template_id or choose_template(dispatch_mode=str(dict(dispatch or {}).get("mode") or ""), capability=capability_text, dependencies=dependencies)).strip()
        workspace_name = f"{skill_key}__{draft_id[-4:]}"
        root_path = self.store.drafts_dir / workspace_name
        root_path.mkdir(parents=True, exist_ok=True)
        provenance = {
            "draft_id": draft_id,
            "created_by": str(actor or "operator"),
            "source": str(source or "chat"),
            "created_at": _now_iso(),
        }
        files = build_template_files(
            skill_name=skill_name_text,
            skill_key=skill_key,
            description=str(description or f"Draft skill for {capability_text}."),
            capability=capability_text,
            objective=str(objective or ""),
            template_id=template,
            dependencies=dependencies,
            dispatch=dispatch,
            provenance=provenance,
        )
        created_files: list[str] = []
        for relative_path, content in files.items():
            path = root_path / relative_path
            if not path.exists():
                path.write_text(content, encoding="utf-8")
                created_files.append(relative_path)
        payload = {
            "draft_id": draft_id,
            "skill_key": skill_key,
            "skill_name": skill_name_text,
            "capability": capability_text,
            "description": str(description or f"Draft skill for {capability_text}."),
            "template_id": template,
            "root_path": str(root_path),
            "status": "draft",
            "created_by": str(actor or "operator"),
            "source": str(source or "chat"),
            "objective": str(objective or ""),
            "dependencies": dict(dependencies or {}),
            "dispatch": dict(dispatch or {}),
            "created_files": created_files,
            "history": [
                {
                    "timestamp": _now_iso(),
                    "action": "create_draft",
                    "actor": str(actor or "operator"),
                    "source": str(source or "chat"),
                }
            ],
            "provenance": provenance,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        return self.store.write_draft(payload)

    def _load_json(self, root_path: Path, filename: str) -> dict[str, Any]:
        path = root_path / filename
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def review_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.store.load_draft(draft_id)
        if not isinstance(draft, dict):
            raise ValueError(f"Unknown skill draft: {draft_id}")
        root_path = Path(str(draft.get("root_path") or "")).resolve()
        findings: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        manifest = self._load_json(root_path, "skill_manifest.json")
        regression = self._load_json(root_path, "regression_checks.json")

        try:
            doc = parse_skill_md(root_path)
            checks.append({"id": "skill_parse", "ok": True, "detail": doc.skill_key})
        except (SkillParseError, FileNotFoundError, ValueError) as exc:
            checks.append({"id": "skill_parse", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
            findings.append({"severity": "critical", "message": f"Skill draft parsing failed: {type(exc).__name__}: {exc}"})
            doc = None

        security = scan_directory_with_summary(
            root_path,
            max_files=int(self.cfg.get("SKILLS_SECURITY_SCAN_MAX_FILES", 500) or 500),
            max_file_bytes=int(self.cfg.get("SKILLS_SECURITY_SCAN_MAX_FILE_BYTES", 1024 * 1024) or (1024 * 1024)),
        )
        blocked = should_block(
            list(security.get("findings") or []),
            str(self.cfg.get("SKILLS_SECURITY_SCAN_BLOCK_ON_SEVERITY", "critical") or "critical"),
        )
        checks.append(
            {
                "id": "security_scan",
                "ok": not blocked,
                "detail": f"critical={security.get('critical', 0)} warn={security.get('warn', 0)} info={security.get('info', 0)}",
            }
        )
        if blocked:
            findings.append({"severity": "critical", "message": "Security scan flagged blocking findings."})

        dispatch_manifest = dict(manifest.get("dispatch") or {})
        expected_mode = str(dispatch_manifest.get("mode") or "").strip().lower()
        actual_mode = str(getattr(doc, "command_dispatch", "") or "").strip().lower() if doc else ""
        consistency_ok = True
        if expected_mode == "tool" and actual_mode != "tool":
            consistency_ok = False
            findings.append({"severity": "warn", "message": "Manifest expects tool dispatch but SKILL.md does not."})
        if expected_mode == "cli" and actual_mode not in {"cli", ""}:
            consistency_ok = False
            findings.append({"severity": "warn", "message": "Manifest expects CLI dispatch but SKILL.md differs."})
        checks.append({"id": "manifest_consistency", "ok": consistency_ok, "detail": expected_mode or "prompt_only"})

        eligibility: dict[str, Any] = {"ok": False, "reasons": ["skill_parse_failed"]}
        if doc is not None:
            ok, reasons = check_eligibility(doc, cfg=self.cfg, env=dict(os.environ), platform=sys_platform())
            eligibility = {"ok": ok, "reasons": reasons}
            checks.append({"id": "eligibility_preview", "ok": ok, "detail": "; ".join(reasons) if reasons else "ready"})

        review = {
            "draft_id": str(draft.get("draft_id") or draft_id),
            "status": "approved" if not blocked and all(bool(item.get("ok")) for item in checks if item.get("id") in {"skill_parse", "security_scan"}) else "blocked",
            "checks": checks,
            "findings": findings,
            "security": security,
            "eligibility": eligibility,
            "regression": regression,
            "reviewed_at": _now_iso(),
        }
        history = [dict(item) for item in list(draft.get("history") or []) if isinstance(item, dict)]
        history.append({"timestamp": _now_iso(), "action": "review_draft", "status": review["status"]})
        draft["history"] = history[-max(1, int(self.cfg.get("SKILLS_FORGE_HISTORY_LIMIT", getattr(skillssettings, "SKILLS_FORGE_HISTORY_LIMIT", 40)) or 40)) :]
        draft["latest_review"] = review
        draft["updated_at"] = _now_iso()
        self.store.write_draft(draft)
        return review

    def approve_install(self, draft_id: str, *, actor: str = "operator") -> dict[str, Any]:
        draft = self.store.load_draft(draft_id)
        if not isinstance(draft, dict):
            raise ValueError(f"Unknown skill draft: {draft_id}")
        review = dict(draft.get("latest_review") or {})
        if not review:
            review = self.review_draft(draft_id)
        if str(review.get("status") or "").lower() != "approved":
            raise ValueError("Skill draft review has blocking findings.")

        provenance = {
            "draft_id": str(draft.get("draft_id") or ""),
            "template_id": str(draft.get("template_id") or ""),
            "capability": str(draft.get("capability") or ""),
            "created_by": str(draft.get("created_by") or ""),
            "approved_by": str(actor or "operator"),
        }
        install = self.manager.install_skill(
            str(draft.get("root_path") or ""),
            actor=str(actor or "operator"),
            mode="approve_install",
            provenance=provenance,
        )
        history = [dict(item) for item in list(draft.get("history") or []) if isinstance(item, dict)]
        history.append({"timestamp": _now_iso(), "action": "approve_install", "actor": str(actor or "operator"), "skill_key": install.get("skill_key")})
        draft["history"] = history[-max(1, int(self.cfg.get("SKILLS_FORGE_HISTORY_LIMIT", getattr(skillssettings, "SKILLS_FORGE_HISTORY_LIMIT", 40)) or 40)) :]
        draft["status"] = "installed"
        draft["install_result"] = install
        draft["updated_at"] = _now_iso()
        self.store.write_draft(draft)
        return {"draft": draft, "install": install}

    def reject_draft(self, draft_id: str, *, actor: str = "operator", reason: str = "") -> dict[str, Any]:
        draft = self.store.load_draft(draft_id)
        if not isinstance(draft, dict):
            raise ValueError(f"Unknown skill draft: {draft_id}")
        history = [dict(item) for item in list(draft.get("history") or []) if isinstance(item, dict)]
        history.append({"timestamp": _now_iso(), "action": "reject_draft", "actor": str(actor or "operator"), "reason": str(reason or "")})
        draft["history"] = history[-max(1, int(self.cfg.get("SKILLS_FORGE_HISTORY_LIMIT", getattr(skillssettings, "SKILLS_FORGE_HISTORY_LIMIT", 40)) or 40)) :]
        draft["status"] = "rejected"
        draft["rejection_reason"] = str(reason or "")
        draft["updated_at"] = _now_iso()
        return self.store.write_draft(draft)

    def list_drafts(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.store.list_drafts(limit=limit)
