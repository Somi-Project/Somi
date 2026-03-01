from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any


def _det_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"


def derive_goal_candidates(projects: list[dict[str, Any]], *, allow_candidates: bool = True) -> list[dict[str, Any]]:
    if not allow_candidates:
        return []
    tag_hits: Counter[str] = Counter()
    evidence: dict[str, list[str]] = {}
    for proj in list(projects or []):
        pid = str(proj.get("project_id") or "")
        for tag in list(proj.get("tags") or []):
            t = str(tag or "").lower()
            if t.startswith("goal:"):
                tag_hits[t] += 2
                evidence.setdefault(t, []).append(pid)

    for proj in list(projects or []):
        if int(proj.get("open_items") or 0) >= 3:
            for tag in list(proj.get("tags") or [])[:2]:
                t = str(tag or "").lower()
                tag_hits[t] += 1
                evidence.setdefault(t, []).append(str(proj.get("project_id") or ""))

    out: list[dict[str, Any]] = []
    for tag, hits in tag_hits.items():
        if hits < 3:
            continue
        out.append(
            {
                "artifact_type": "goal_candidate",
                "candidate_id": _det_id("cand", tag),
                "title": tag.replace("goal:", "").replace("_", " ").strip() or tag,
                "evidence_artifact_ids": sorted({x for x in evidence.get(tag, []) if x})[:20],
                "requires_confirmation": True,
            }
        )
    return sorted(out, key=lambda x: str(x.get("candidate_id") or ""))


def build_goal_link_proposals(projects: list[dict[str, Any]], confirmed_goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Creates confirmation-only proposals; never auto-links based on semantic similarity."""
    goal_by_tag: dict[str, dict[str, Any]] = {}
    for g in list(confirmed_goals or []):
        gid = str(g.get("goal_id") or "")
        for t in list(g.get("tags") or []):
            tag = str(t or "").lower()
            if tag:
                goal_by_tag[tag] = g

    proposals: list[dict[str, Any]] = []
    for p in list(projects or []):
        pid = str(p.get("project_id") or "")
        tags = [str(t or "").lower() for t in list(p.get("tags") or [])]
        for tag in tags:
            goal = goal_by_tag.get(tag)
            if not goal:
                continue
            gid = str(goal.get("goal_id") or "")
            if not gid or pid in set(goal.get("linked_project_ids") or []):
                continue
            proposal_id = _det_id("glp", f"{pid}|{gid}|{tag}")
            proposals.append(
                {
                    "artifact_type": "goal_link_proposal",
                    "proposal_id": proposal_id,
                    "goal_id": gid,
                    "project_id": pid,
                    "evidence_artifact_ids": [pid, gid],
                    "reason_codes": ["explicit_tag_match"],
                    "requires_confirmation": True,
                }
            )
    return sorted(proposals, key=lambda x: str(x.get("proposal_id") or ""))


def link_projects_to_confirmed_goals(projects: list[dict[str, Any]], confirmed_goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed: dict[str, set[str]] = {}
    for goal in list(confirmed_goals or []):
        gid = str(goal.get("goal_id") or "")
        allowed[gid] = {str(x) for x in list(goal.get("linked_project_ids") or []) if str(x)}

    linked: list[dict[str, Any]] = []
    for goal in list(confirmed_goals or []):
        gid = str(goal.get("goal_id") or "")
        pids = sorted(allowed.get(gid) or [])
        linked.append({**goal, "linked_project_ids": pids})
    return linked
