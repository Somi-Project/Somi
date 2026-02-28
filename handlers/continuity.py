from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from handlers.contracts.base import build_base

RESUME_PHRASES = ["continue", "resume", "as before", "same thing"]
TASK_SIGNAL_PHRASES = ["what's left", "whats left", "status", "open tasks"]
THREAD_STOPWORDS = {"a", "an", "the", "and", "or", "to", "for", "of", "on", "in", "with", "please", "lets", "let", "s", "as", "before", "same", "thing", "continue", "resume"}
TASK_TOKEN_SYNONYMS = {
    "documentation": "docs",
    "document": "docs",
    "docs": "docs",
    "release": "ship",
    "deploy": "ship",
    "shipping": "ship",
    "tests": "test",
    "testing": "test",
    "qa": "test",
    "fixes": "fix",
}


@dataclass
class ContinuityResult:
    artifact: Optional[Dict[str, Any]]
    confidence: float


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    t = str(value or "").strip()
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        return datetime.fromisoformat(t)
    except Exception:
        return None


def normalize_tags(tags: List[str]) -> List[str]:
    out: List[str] = []
    for tag in tags:
        t = " ".join(str(tag or "").strip().lower().split())
        t = re.sub(r"[^a-z0-9 _-]", "", t).replace(" ", "-")
        if not t or len(t) > 32 or t in out:
            continue
        out.append(t)
        if len(out) >= 20:
            break
    return out


def suggest_tags(*, user_text: str, artifact_type: str, existing: Optional[List[str]] = None, strong_continuity: bool = False) -> List[str]:
    if existing:
        return normalize_tags(existing)
    supported = {"plan", "meeting_summary", "decision_matrix", "task_state", "artifact_continuity"}
    if artifact_type not in supported and not strong_continuity:
        return []
    text = str(user_text or "").lower()
    candidates = [
        "somi", "toolbox", "tts", "ocr", "twitter", "registry", "bugfix", "deployment", "docs", "security", "performance",
    ]
    tags = [t for t in candidates if t in text]
    if artifact_type and artifact_type not in tags:
        tags.append(artifact_type)
    return normalize_tags(tags[:7])


def _normalize_thread_seed(seed_text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]{2,}", str(seed_text or "").lower()) if w not in THREAD_STOPWORDS]
    normalized = " ".join(words[:40])
    return normalized or "general"


def derive_thread_id(seed_text: str) -> str:
    text = _normalize_thread_seed(seed_text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"thr_{digest[:16]}"


def choose_thread_id_for_request(user_text: str, signals: Dict[str, Any], idx: Dict[str, Any]) -> str:
    explicit = str(signals.get("thread_id") or "").strip()
    if explicit:
        return explicit
    ranked = _rank_candidates(user_text, idx, signals)
    if ranked:
        top = ranked[0]
        top_tid = str(top.get("thread_id") or "").strip()
        if top_tid and (float(top.get("_score") or 0.0) >= 0.45 or _is_resume_text(user_text)):
            return top_tid
    return derive_thread_id(user_text)


def _task_title_key(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]{2,}", str(title or "").lower()))[:180]


def _normalized_tokens(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-z0-9]{2,}", str(text or "").lower()):
        out.append(TASK_TOKEN_SYNONYMS.get(w, w))
    return out


def _task_similarity(a: str, b: str) -> float:
    ta = set(_normalized_tokens(a))
    tb = set(_normalized_tokens(b))
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb) / max(1, len(ta | tb))
    if a.strip().lower() == b.strip().lower():
        overlap = max(overlap, 1.0)
    return overlap


def _find_best_previous_task(title: str, prev_map: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], float]:
    best = {}
    best_score = 0.0
    for _, prev in prev_map.items():
        pt = str(prev.get("title") or "")
        score = _task_similarity(title, pt)
        if score > best_score:
            best = prev
            best_score = score
    return best, best_score


def _infer_status_from_text(task_title: str, status_hint_text: str) -> Optional[str]:
    if not status_hint_text:
        return None
    hint_raw = str(status_hint_text).lower()
    tokens = [t for t in _normalized_tokens(task_title) if len(t) >= 3]
    if not tokens:
        return None

    clauses = [c.strip() for c in re.split(r"[.;,\n]+", hint_raw) if c.strip()]
    if not clauses:
        clauses = [hint_raw]

    matched_clause = None
    for clause in clauses:
        c_tokens = set(_normalized_tokens(clause))
        if c_tokens and any(t in c_tokens for t in tokens[:5]):
            matched_clause = clause
            break
    if not matched_clause:
        return None

    if re.search(r"\b(done|completed|finished|shipped|resolved)\b", matched_clause):
        return "done"
    if re.search(r"\b(in progress|working on|doing|ongoing)\b", matched_clause):
        return "in_progress"
    if re.search(r"\b(blocked|stuck|waiting on|dependency)\b", matched_clause):
        return "blocked"
    if re.search(r"\b(todo|next|open|pending)\b", matched_clause):
        return "open"
    return None


def _keyword_similarity(a: str, b: str) -> float:
    wa = {x for x in re.findall(r"[a-z0-9]{3,}", a.lower())}
    wb = {x for x in re.findall(r"[a-z0-9]{3,}", b.lower())}
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    union = len(wa | wb)
    return inter / max(1, union)


def _is_resume_text(user_text: str) -> bool:
    text = str(user_text or "").lower()
    return any(p in text for p in RESUME_PHRASES)


def score_continuity(
    *,
    user_text: str,
    ui_thread_id: Optional[str],
    tag_overlap: float,
    same_type: bool,
    stale_90d: bool,
) -> float:
    score = 0.0
    if _is_resume_text(user_text):
        score += 0.35
    if ui_thread_id:
        score += 0.25
    if tag_overlap >= 0.5:
        score += 0.15
    if same_type:
        score += 0.10
    if stale_90d and not _is_resume_text(user_text):
        score -= 0.20
    return max(0.0, min(1.0, score))


def _rank_candidates(user_text: str, idx: Dict[str, Any], signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = str(user_text or "")
    requested_type = str(signals.get("artifact_intent") or "")
    user_tags = set(normalize_tags(list(signals.get("tags") or [])))
    user_thread = str(signals.get("thread_id") or "").strip()

    pools: List[Dict[str, Any]] = []
    pools.extend(list(idx.get("recent_open_threads") or [])[:100])
    if user_thread:
        pools.extend(list((idx.get("by_thread_id") or {}).get(user_thread) or [])[:100])
    for tag in list(user_tags)[:7]:
        pools.extend(list((idx.get("by_tag") or {}).get(tag) or [])[:60])

    # de-dup by artifact id while preserving deterministic order
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for rec in pools:
        aid = str((rec or {}).get("artifact_id") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        deduped.append(dict(rec))

    candidates: List[Dict[str, Any]] = []
    for rec in deduped[:200]:
        title = str(rec.get("title") or "")
        score = 0.0
        tag_set = set(rec.get("tags") or [])
        tag_overlap = 0.0
        if user_tags and tag_set:
            tag_overlap = len(user_tags & tag_set) / max(1, len(user_tags | tag_set))
            score += 0.35 * tag_overlap
        if rec.get("type") in {"plan", "task_state"}:
            score += 0.2
        ts = _parse_ts(rec.get("updated_at"))
        if ts and ts >= _now() - timedelta(days=30):
            score += 0.2
        score += 0.25 * _keyword_similarity(text, title)
        if requested_type and rec.get("type") == requested_type:
            score += 0.1
        if user_thread and rec.get("thread_id") == user_thread:
            score += 0.2
        out = dict(rec)
        out["_tag_overlap"] = round(tag_overlap, 6)
        out["_score"] = round(score, 6)
        candidates.append(out)
    candidates.sort(key=lambda x: (x.get("_score", 0.0), x.get("updated_at") or ""), reverse=True)
    return candidates[:10]


def maybe_emit_continuity_artifact(user_text: str, signals: Dict[str, Any], idx: Dict[str, Any]) -> ContinuityResult:
    candidates = _rank_candidates(user_text, idx, signals)
    top = candidates[0] if candidates else {}
    top_tags = set(top.get("tags") or [])
    signal_tags = set(normalize_tags(list(signals.get("tags") or [])))
    overlap = float(top.get("_tag_overlap") or ((len(top_tags & signal_tags) / max(1, len(top_tags | signal_tags))) if (top_tags or signal_tags) else 0.0))
    stale_90d = False
    ts = _parse_ts(top.get("updated_at"))
    if ts and ts < _now() - timedelta(days=90):
        stale_90d = True

    conf = score_continuity(
        user_text=user_text,
        ui_thread_id=signals.get("thread_id"),
        tag_overlap=overlap if top.get("type") in {"plan", "task_state"} else 0.0,
        same_type=bool(signals.get("artifact_intent") and signals.get("artifact_intent") == top.get("type")),
        stale_90d=stale_90d,
    )
    threshold = 0.35 if _is_resume_text(user_text) else 0.55
    if conf < threshold:
        return ContinuityResult(artifact=None, confidence=conf)

    thread_id = str(signals.get("thread_id") or top.get("thread_id") or derive_thread_id(user_text))
    reasons = []
    if _is_resume_text(user_text):
        reasons.append("explicit_resume_phrase")
    if signals.get("thread_id"):
        reasons.append("ui_thread_id")
    if overlap >= 0.5:
        reasons.append("high_tag_overlap")
    if signals.get("artifact_intent") and signals.get("artifact_intent") == top.get("type"):
        reasons.append("same_requested_artifact_type")
    if stale_90d:
        reasons.append("stale_over_90d")

    stale_flags = []
    if ts and ts < _now() - timedelta(days=30):
        stale_flags.append("older_than_30d")
    if not top:
        stale_flags.append("context_missing")

    suggested = list(signals.get("suggested_next_steps") or [])[:7]
    if not suggested:
        suggested = [
            "Confirm the current objective and success criteria.",
            "Update task statuses for open and blocked items.",
            "Pick the next highest-priority step to execute.",
        ]

    top_related = [
        {
            "artifact_id": x.get("artifact_id"),
            "type": x.get("type"),
            "title": x.get("title"),
            "status": x.get("status") or "unknown",
            "updated_at": x.get("updated_at"),
        }
        for x in candidates[:10]
        if x.get("artifact_id")
    ]

    artifact = build_base(
        artifact_type="artifact_continuity",
        inputs={"user_query": user_text, "route": str(signals.get("route") or "llm_only")},
        content={
            "thread_id": thread_id,
            "top_related_artifacts": top_related,
            "current_state_summary": f"Resuming thread {thread_id} using {len(top_related)} related artifacts.",
            "suggested_next_steps": suggested[:7],
            "assumptions": ["No actions have been executed automatically.", "Continuity output is suggestion-only."],
            "questions": list(signals.get("questions") or [])[:5],
            "safety": {"no_autonomy": True, "no_execution": True},
        },
        confidence=conf,
        trigger_reason={
            "explicit_request": _is_resume_text(user_text),
            "matched_phrases": reasons,
            "structural_signals": ["continuity"],
            "tie_break": None,
        },
        metadata={"derived_from": "continuity_engine"},
    )
    artifact["thread_id"] = thread_id
    artifact["related_artifact_ids"] = [x.get("artifact_id") for x in top_related if x.get("artifact_id")][:20]
    artifact["tags"] = suggest_tags(user_text=user_text, artifact_type="artifact_continuity", strong_continuity=True)
    artifact["status"] = "in_progress"
    artifact["continuity"] = {
        "resume_reasons": reasons,
        "resume_confidence": conf,
        "suggested_next_steps": suggested[:7],
        "stale_flags": stale_flags,
        "candidate_artifact_ids": [x.get("artifact_id") for x in top_related if x.get("artifact_id")][:20],
        "no_autonomy": True,
    }
    return ContinuityResult(artifact=artifact, confidence=conf)


def should_emit_task_state(user_text: str, explicit_request: bool = False) -> bool:
    if explicit_request:
        return True
    text = str(user_text or "").lower()
    return any(p in text for p in TASK_SIGNAL_PHRASES)


def build_task_state_from_artifact(*, source_artifact: Dict[str, Any], thread_id: str, previous_task_state: Dict[str, Any] | None = None, status_hint_text: str | None = None) -> Dict[str, Any]:
    at = str(source_artifact.get("artifact_type") or source_artifact.get("contract_name") or "")
    data = dict(source_artifact.get("data") or source_artifact.get("content") or {})
    tasks = []
    prev_map: Dict[str, Dict[str, Any]] = {}
    prev_data = dict((previous_task_state or {}).get("data") or (previous_task_state or {}).get("content") or {})
    prev_thread = str((previous_task_state or {}).get("thread_id") or prev_data.get("thread_id") or "")
    if previous_task_state and prev_thread == thread_id:
        for row in list(prev_data.get("tasks") or []):
            if isinstance(row, dict):
                k = _task_title_key(str(row.get("title") or ""))
                if k:
                    prev_map[k] = row
    if at == "plan":
        for step in list(data.get("steps") or []):
            title = str(step).strip()
            if not title:
                continue
            task_id = hashlib.sha256(f"{thread_id}|{title}|{source_artifact.get('artifact_id')}".encode("utf-8")).hexdigest()[:16]
            prev_exact = prev_map.get(_task_title_key(title), {})
            prev, sim = (prev_exact, 1.0) if prev_exact else _find_best_previous_task(title, prev_map)
            if sim < 0.55:
                prev = {}
            tasks.append({
                "task_id": str(prev.get("task_id") or task_id),
                "title": title[:240],
                "status": str(prev.get("status") or "open"),
                "owner": str(prev.get("owner") or "Unassigned")[:80],
                "source_artifact_id": str(source_artifact.get("artifact_id") or ""),
            })
    elif at == "meeting_summary":
        for row in list(data.get("action_items") or []):
            if not isinstance(row, dict):
                continue
            title = str(row.get("task") or "").strip()
            if not title:
                continue
            task_id = hashlib.sha256(f"{thread_id}|{title}|{source_artifact.get('artifact_id')}".encode("utf-8")).hexdigest()[:16]
            prev_exact = prev_map.get(_task_title_key(title), {})
            prev, sim = (prev_exact, 1.0) if prev_exact else _find_best_previous_task(title, prev_map)
            if sim < 0.55:
                prev = {}
            item = {
                "task_id": str(prev.get("task_id") or task_id),
                "title": title[:240],
                "status": str(prev.get("status") or "open"),
                "owner": str(prev.get("owner") or row.get("owner") or "Unassigned")[:80],
                "source_artifact_id": str(source_artifact.get("artifact_id") or ""),
            }
            if row.get("due"):
                item["due_date"] = row.get("due")
            tasks.append(item)
    counts = {"open": 0, "in_progress": 0, "done": 0, "blocked": 0}
    for t in tasks:
        if t["status"] in counts:
            counts[t["status"]] += 1

    suggested_updates = []
    for t in tasks:
        title = str(t.get("title") or "")
        prev_exact = prev_map.get(_task_title_key(title), {})
        prev, sim = (prev_exact, 1.0) if prev_exact else _find_best_previous_task(title, prev_map)
        if sim < 0.55:
            prev = {}
        prev_status = str(prev.get("status") or "")
        cur_status = str(t.get("status") or "open")
        if prev_status and prev_status != cur_status:
            suggested_updates.append({
                "task_id": t.get("task_id"),
                "suggested_status": cur_status,
                "reason": f"Carry-forward status from prior task_state ({prev_status} -> {cur_status}).",
            })
        inferred = _infer_status_from_text(title, status_hint_text or "")
        if inferred and inferred != cur_status:
            suggested_updates.append({
                "task_id": t.get("task_id"),
                "suggested_status": inferred,
                "reason": "Status keyword inferred from latest user/request context.",
            })

    return build_base(
        artifact_type="task_state",
        inputs={"user_query": "task status", "route": "llm_only"},
        content={
            "thread_id": thread_id,
            "tasks": tasks,
            "rollups": {
                "open_count": counts["open"],
                "in_progress_count": counts["in_progress"],
                "done_count": counts["done"],
                "blocked_count": counts["blocked"],
            },
            "suggested_updates": suggested_updates[:50],
        },
        confidence=0.72,
        metadata={"derived_from": at},
    )
