from __future__ import annotations

from typing import Any

from workflow_runtime import WorkflowManifestStore
from workshop.toolbox.registry import ToolRegistry

from .manager import SkillManager
from .recipe_packs import get_recipe_pack, list_recipe_packs

AGENT_TEMPLATES = (
    {
        "id": "assistant_operator",
        "name": "Assistant Operator",
        "description": "General local operator for planning, reminders, and steady day-to-day help.",
        "best_for": ["chat", "control_room"],
        "starter_prompt": "Help me get organized for today and show me the best next actions.",
    },
    {
        "id": "research_operator",
        "name": "Research Operator",
        "description": "Grounded research profile for current questions, follow-up links, and reusable evidence trails.",
        "best_for": ["chat", "control_room"],
        "starter_prompt": "Research this topic with current sources and give me the grounded answer plus links.",
    },
    {
        "id": "coding_builder",
        "name": "Coding Builder",
        "description": "Local coding profile for scaffolds, patch loops, verification, and safe self-expansion.",
        "best_for": ["coding_studio", "chat"],
        "starter_prompt": "/code build a Python utility that solves a real local task and verify it before finishing",
    },
    {
        "id": "document_intake",
        "name": "Document Intake",
        "description": "Structured extraction profile for OCR, forms, and document intelligence workflows.",
        "best_for": ["gui", "chat"],
        "starter_prompt": "Help me extract the key fields from this document and tell me what needs manual review.",
    },
)

WORKFLOW_TEMPLATES = (
    {
        "id": "research_digest",
        "name": "Research Digest",
        "manifest_id": "research_digest",
        "description": "Reusable evidence-gathering workflow for compact grounded summaries.",
        "starter_prompt": "Run the research digest workflow for this topic and keep the result concise.",
    },
    {
        "id": "workspace_bootstrap",
        "name": "Workspace Bootstrap",
        "manifest_id": "",
        "description": "A guided coding session start for creating a managed local workspace and health baseline.",
        "starter_prompt": "/code bootstrap a fresh workspace for this task and tell me the next checks.",
    },
)

SKILL_BUNDLES = (
    {
        "id": "operator_core",
        "name": "Operator Core",
        "description": "Friendly day-one bundle for chat, memory, automation, and light browser inspection.",
        "skills": [],
        "toolsets": ["safe-chat", "automation", "ops"],
        "tools": ["browser.runtime"],
    },
    {
        "id": "research_core",
        "name": "Research Core",
        "description": "Grounded research bundle for web evidence, artifacts, and controlled browser reads.",
        "skills": [],
        "toolsets": ["research", "safe-chat", "automation"],
        "tools": ["web.intelligence", "research.artifact", "browser.runtime"],
    },
    {
        "id": "coding_core",
        "name": "Coding Core",
        "description": "Local coding bundle for workspace, files, runtime checks, and skill drafts.",
        "skills": [],
        "toolsets": ["developer", "ops"],
        "tools": ["coding.workspace", "coding.fs", "coding.python", "coding.runtime", "coding.scaffold"],
    },
    {
        "id": "document_core",
        "name": "Document Core",
        "description": "Document bundle for OCR, extraction, and workspace-backed intake flows.",
        "skills": [],
        "toolsets": ["research", "field"],
        "tools": ["ocr.extract", "browser.runtime"],
    },
)


def _tool_ready(registry: ToolRegistry, tool_name: str) -> bool:
    entry = registry.find(tool_name)
    if not entry:
        return False
    availability = registry.availability(entry)
    return bool(availability.get("ok", False))


def _starter_prompt(item: dict[str, Any]) -> str:
    prompt = str(item.get("starter_prompt") or "").strip()
    if prompt:
        return prompt
    quick_actions = [str(row) for row in list(item.get("quick_actions") or []) if str(row).strip()]
    return quick_actions[0] if quick_actions else ""


class StarterStudioService:
    def __init__(
        self,
        *,
        skill_manager: SkillManager | None = None,
        tool_registry: ToolRegistry | None = None,
        workflow_manifest_store: WorkflowManifestStore | None = None,
    ) -> None:
        self.skill_manager = skill_manager or SkillManager()
        self.tool_registry = tool_registry or ToolRegistry()
        self.workflow_manifest_store = workflow_manifest_store or WorkflowManifestStore()

    def _recipe_rows(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for recipe in list_recipe_packs():
            tools = [str(name) for name in list(recipe.get("tools") or []) if str(name).strip()]
            ready_count = sum(1 for name in tools if _tool_ready(self.tool_registry, name))
            row = dict(recipe)
            row["kind"] = "recipe"
            row["starter_prompt"] = _starter_prompt(recipe)
            row["tool_total"] = len(tools)
            row["tool_ready_count"] = ready_count
            row["tool_ready_ratio"] = round((ready_count / max(1, len(tools))), 2) if tools else 0.0
            row["featured"] = bool(recipe.get("featured", False))
            rows.append(row)
        rows.sort(key=lambda item: (-int(bool(item.get("featured", False))), -float(item.get("tool_ready_ratio", 0.0)), str(item.get("name") or "")))
        return rows

    def _workflow_rows(self) -> list[dict[str, Any]]:
        manifests = {item.manifest_id: item.to_dict() for item in self.workflow_manifest_store.list_manifests()}
        rows: list[dict[str, Any]] = []
        for template in WORKFLOW_TEMPLATES:
            row = dict(template)
            manifest_id = str(row.get("manifest_id") or "").strip()
            manifest = dict(manifests.get(manifest_id) or {})
            row["kind"] = "workflow_template"
            row["manifest_available"] = bool(manifest) if manifest_id else False
            row["allowed_tools"] = list(manifest.get("allowed_tools") or [])
            rows.append(row)
        return rows

    def _bundle_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for bundle in SKILL_BUNDLES:
            row = dict(bundle)
            tools = [str(name) for name in list(row.get("tools") or []) if str(name).strip()]
            ready_count = sum(1 for name in tools if _tool_ready(self.tool_registry, name))
            row["kind"] = "bundle"
            row["tool_total"] = len(tools)
            row["tool_ready_count"] = ready_count
            row["starter_prompt"] = _starter_prompt(row)
            rows.append(row)
        return rows

    def build_snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        catalog = self.skill_manager.catalog(force_refresh=force_refresh)
        recipe_rows = self._recipe_rows(force_refresh=force_refresh)
        workflow_rows = self._workflow_rows()
        bundle_rows = self._bundle_rows()
        agent_rows = [dict(item, kind="agent_template") for item in AGENT_TEMPLATES]
        featured = recipe_rows[:4]
        return {
            "recipes": recipe_rows,
            "featured_recipes": featured,
            "agent_templates": agent_rows,
            "workflow_templates": workflow_rows,
            "recommended_bundles": bundle_rows,
            "catalog_summary": {
                "skill_count": int(catalog.get("count", 0) or 0),
                "status_counts": dict(catalog.get("status_counts") or {}),
                "trust_labels": list(catalog.get("trust_labels") or []),
            },
        }

    def describe_recipe(self, recipe_id: str) -> dict[str, Any] | None:
        row = get_recipe_pack(recipe_id)
        if not row:
            return None
        recipe = dict(row)
        recipe["starter_prompt"] = _starter_prompt(recipe)
        recipe["tool_ready_count"] = sum(1 for name in list(recipe.get("tools") or []) if _tool_ready(self.tool_registry, str(name)))
        return recipe
