from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import settings
from executive.life_modeling.artifact_store import ArtifactStore
from executive.life_modeling.calendar_snapshot import get_calendar_provider, get_snapshot
from executive.life_modeling.confirmation_queue import GoalLinkConfirmationQueue
from executive.life_modeling.context_pack import build_context_pack
from executive.life_modeling.enrichment import enrich_summary
from executive.life_modeling.goal_models import build_goal_link_proposals, derive_goal_candidates, link_projects_to_confirmed_goals
from executive.life_modeling.heartbeat_v2 import build_heartbeat_v2
from executive.life_modeling.indexer import Indexer
from executive.life_modeling.normalizers import normalize_artifact
from executive.life_modeling.patterns import detect_patterns
from executive.life_modeling.project_clustering import cluster_projects

logger = logging.getLogger(__name__)


class LifeModelingRunner:
    def __init__(self, artifacts_dir: str = "sessions/artifacts"):
        self.indexer = Indexer(artifacts_dir=artifacts_dir)
        self.store = ArtifactStore()
        self._debounce_path = Path("executive/index/phase7_debounce.json")
        self.confirmation_queue = GoalLinkConfirmationQueue(path=str(getattr(settings, "PHASE7_GOAL_LINK_QUEUE_PATH", "executive/index/goal_link_queue.json")))

    def should_run(self, *, debounce_seconds: int = 5) -> bool:
        now = datetime.now(timezone.utc)
        if not self._debounce_path.exists():
            return True
        try:
            raw = json.loads(self._debounce_path.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(str(raw.get("last_run_at") or "").replace("Z", "+00:00"))
            return (now - last).total_seconds() >= debounce_seconds
        except Exception:
            return True

    def mark_run(self) -> None:
        self._debounce_path.parent.mkdir(parents=True, exist_ok=True)
        self._debounce_path.write_text(json.dumps({"last_run_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")

    def _effective_min_items_per_project(self, item_count: int) -> tuple[int, bool]:
        base = int(getattr(settings, "PHASE7_MIN_ITEMS_PER_PROJECT", 2))
        enabled = bool(getattr(settings, "PHASE7_BOOTSTRAP_RELAXATION_ENABLED", True))
        if not enabled:
            return base, False
        threshold = int(getattr(settings, "PHASE7_BOOTSTRAP_RELAXATION_ITEM_THRESHOLD", 6))
        relaxed = int(getattr(settings, "PHASE7_BOOTSTRAP_RELAXED_MIN_ITEMS_PER_PROJECT", 1))
        if item_count <= max(1, threshold):
            return max(1, relaxed), True
        return base, False

    def run(self) -> dict[str, Any]:
        if not bool(getattr(settings, "PHASE7_ENABLED", True)):
            return {"phase7": "disabled"}

        try:
            self.indexer.build_or_update_index()
            items = self._load_normalized_items(days=int(getattr(settings, "PHASE7_FAST_WINDOW_DAYS", 30)))
            prev_clusters = self._latest_clusters()
            min_items_per_project, relaxation_used = self._effective_min_items_per_project(len(items))
            clusters, _state = cluster_projects(
                items,
                prev_clusters=prev_clusters,
                max_active_projects=int(getattr(settings, "PHASE7_MAX_ACTIVE_PROJECTS", 20)),
                assign_threshold=float(getattr(settings, "PHASE7_CLUSTER_ASSIGN_THRESHOLD", 0.42)),
                switch_margin=float(getattr(settings, "PHASE7_CLUSTER_SWITCH_MARGIN", 0.12)),
                switch_cooldown_hours=int(getattr(settings, "PHASE7_CLUSTER_SWITCH_COOLDOWN_HOURS", 72)),
                min_items_per_project=min_items_per_project,
                max_evidence_per_link=int(getattr(settings, "PHASE7_MAX_EVIDENCE_PER_LINK", 5)),
                weights=dict(getattr(settings, "PHASE7_CLUSTER_WEIGHTS", {"tag": 0.55, "co": 0.3, "recency": 0.15})),
                recency_decay_days=int(getattr(settings, "PHASE7_RECENCY_DECAY_DAYS", 21)),
            )
            for c in clusters:
                self.store.write("project_cluster", c)

            goal_models = list(self.store.iter_all("goal_model") or [])
            linked_goals = link_projects_to_confirmed_goals(clusters, goal_models)
            candidates = derive_goal_candidates(clusters)
            for cand in candidates:
                self.store.write("goal_candidate", cand)
            link_proposals = build_goal_link_proposals(clusters, linked_goals)
            for proposal in link_proposals:
                self.store.write("goal_link_proposal", proposal)
            queued = self.confirmation_queue.enqueue(link_proposals)

            patterns = detect_patterns(items, clusters)
            for p in patterns:
                self.store.write("pattern_insight", p)

            cal_provider = self._calendar_provider()
            cal = get_snapshot(
                datetime.now(timezone.utc),
                datetime.now(timezone.utc) + timedelta(days=int(getattr(settings, "PHASE7_CALENDAR_HORIZON_DAYS", 7))),
                provider=cal_provider,
                cache_path=str(getattr(settings, "PHASE7_CALENDAR_CACHE_PATH", "executive/index/calendar_cache.json")),
            )
            self.store.write("calendar_snapshot", cal)

            hb = build_heartbeat_v2(items, clusters, linked_goals, patterns, cal)
            mode = str(getattr(settings, "PHASE7_ENRICHMENT_MODE", "lite"))
            if not bool(getattr(settings, "PHASE7_ENRICHMENT_VALIDATE_FACT_LOCK", True)) and mode == "full":
                mode = "lite"
            hb_summary, ok = enrich_summary(hb.get("summary") or "", hb, mode=mode)
            hb["summary"] = hb_summary
            hb["enrichment_validation_passed"] = bool(ok)
            self.store.write("heartbeat_v2", hb)

            cp = build_context_pack(clusters, linked_goals, hb, patterns, cal)
            self.store.write("context_pack_v1", cp)
            self.mark_run()
            return {
                "projects": len(clusters),
                "goal_candidates": len(candidates),
                "goal_link_proposals": len(link_proposals),
                "goal_link_queue_added": int(queued),
                "patterns": len(patterns),
                "conflicts": len(list(cal.get("conflicts") or [])),
                "bootstrap_relaxation_used": bool(relaxation_used),
                "effective_min_items_per_project": int(min_items_per_project),
            }
        except Exception as exc:
            logger.exception("Phase7 run failed: %s", exc)
            return {"error": str(exc)}

    def _latest_clusters(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in list(self.store.iter_all("project_cluster") or []):
            pid = str(row.get("project_id") or "")
            if not pid:
                continue
            latest[pid] = row
        return list(latest.values())

    def _calendar_provider(self):
        return get_calendar_provider(settings)

    def _read_recent_jsonl_rows(self, path: Path, *, max_rows: int = 50) -> list[dict[str, Any]]:
        max_rows = max(1, int(max_rows))
        chunk_size = int(getattr(settings, "PHASE7_JSONL_TAIL_READ_BYTES", 262_144))
        chunk_size = max(8_192, chunk_size)
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                end = f.tell()
                size = min(end, chunk_size)
                f.seek(max(0, end - size))
                blob = f.read(size)
        except Exception:
            return []
        text = blob.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-max_rows:]:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except Exception:
                continue
            if isinstance(raw, dict):
                out.append(raw)
        return out

    def _load_normalized_items(self, *, days: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        compat_mode = str(getattr(settings, "PHASE7_INPUT_COMPAT_MODE", "lenient"))
        strict = compat_mode == "strict"
        for meta in self.indexer.iter_recent_artifacts(days, types=None):
            path = Path(str(meta.get("path") or ""))
            if not path.exists():
                continue
            for raw in self._read_recent_jsonl_rows(path, max_rows=int(getattr(settings, "PHASE7_MAX_ROWS_PER_FILE", 50))):
                try:
                    normalized = normalize_artifact(raw, strict=strict)
                    if normalized is not None:
                        out.append(normalized)
                except Exception:
                    if strict:
                        raise
        return out


_runner = LifeModelingRunner()


def run_phase7_if_enabled(reason: str = "manual") -> dict[str, Any]:
    if not bool(getattr(settings, "PHASE7_ENABLED", True)):
        return {"phase7": "disabled", "reason": reason}
    if not _runner.should_run():
        return {"phase7": "debounced", "reason": reason}
    return _runner.run()


def on_artifact_written(artifact_type: str) -> dict[str, Any] | None:
    at = str(artifact_type or "")
    if "task" in at or "thread" in at:
        return run_phase7_if_enabled(reason=f"artifact:{at}")
    return None


def list_pending_goal_link_proposals() -> list[dict[str, Any]]:
    return list_goal_link_proposals("pending")


def resolve_goal_link_proposal(proposal_id: str, *, approved: bool) -> bool:
    ok = _runner.confirmation_queue.resolve(proposal_id, approved=approved)
    if not ok or not approved:
        return ok

    row = _runner.confirmation_queue.get(proposal_id)
    if not row:
        return ok
    goal_id = str(row.get("goal_id") or "")
    project_id = str(row.get("project_id") or "")
    if not goal_id or not project_id:
        return ok

    goals = list(_runner.store.iter_all("goal_model") or [])
    latest_by_goal: dict[str, dict[str, Any]] = {}
    for g in goals:
        gid = str(g.get("goal_id") or "")
        if gid:
            latest_by_goal[gid] = g
    g = latest_by_goal.get(goal_id)
    if g is not None:
        links = sorted({str(x) for x in list(g.get("linked_project_ids") or []) if str(x)} | {project_id})
        updated = dict(g)
        updated["linked_project_ids"] = links
        _runner.store.write("goal_model", updated)
    return ok


def list_goal_link_proposals(status: str = "pending") -> list[dict[str, Any]]:
    return _runner.confirmation_queue.list_by_status(status)
