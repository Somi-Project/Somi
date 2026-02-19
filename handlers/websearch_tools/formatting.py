# handlers/websearch_tools/formatting.py
"""
Deterministic formatting utilities for Somi websearch + research pipelines.

Hard guarantees:
- Never throws due to missing/invalid fields in results.
- Handles heterogeneous result shapes (Agentpedia/research + DDG/news/general).
- Produces stable citation keys (cite_id) for prompt-friendly referencing.
- Caps output length so prompts don't explode.
- Dependency-free (stdlib only). No LLM use.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Tiny utils (defensive)
# -----------------------------
def _to_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    # common: numbers, bools, etc.
    try:
        return str(x)
    except Exception:
        return ""


def _norm_space(s: Any) -> str:
    t = _to_str(s).strip()
    if not t:
        return ""
    t = t.replace("\r", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _safe_trim(s: Any, n: int) -> str:
    t = _norm_space(s)
    if not t:
        return ""
    if len(t) <= n:
        return t
    return t[:n].rstrip() + "…"


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _sha1_short(s: str, k: int = 10) -> str:
    try:
        h = hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()
        return h[:k]
    except Exception:
        return "0000000000"[:k]


def _pick(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        v = d.get(k, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
        # allow non-str but meaningful (e.g., ints)
        if v is not None and not isinstance(v, (dict, list, tuple, set)):
            s = _to_str(v).strip()
            if s:
                return s
    return default


def _flatten_spans(x: Any) -> List[str]:
    """
    evidence_spans may be:
    - list[str]
    - str
    - list[mixed]
    - nested lists
    This returns a clean list[str].
    """
    out: List[str] = []

    def rec(v: Any) -> None:
        if v is None:
            return
        if isinstance(v, str):
            s = _norm_space(v)
            if s:
                out.append(s)
            return
        if isinstance(v, (list, tuple)):
            for it in v:
                rec(it)
            return
        # ignore dict/set except as string
        s = _norm_space(v)
        if s:
            out.append(s)

    rec(x)
    return out


# -----------------------------
# Normalization
# -----------------------------
def _make_cite_id(r: Dict[str, Any]) -> str:
    """
    Stable-ish cite id, consistent across formatting calls.
    Prefer (domain,source,id_type,id) when available; else url hash; else title hash.
    """
    domain = _pick(r, "domain", default="web")
    source = _pick(r, "source", default=_pick(r, "category", default=domain or "web"))
    id_type = _pick(r, "id_type")
    rid = _pick(r, "id")
    url = _pick(r, "url")
    title = _pick(r, "title")

    if id_type and rid:
        base = f"{domain}:{source}:{id_type}:{rid}"
    elif url:
        base = f"{domain}:{source}:url:{url}"
    else:
        base = f"{domain}:{source}:title:{title}"

    return f"{domain.upper()}-{_sha1_short(base, 10)}"


def _normalize_result(r: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert heterogeneous result dict into a common safe shape:
      title, url, source, domain, published, evidence_level,
      evidence(list[str]), cite_id, intent_alignment, volatile
    """
    title = _safe_trim(_pick(r, "title"), 180) or "Untitled result"
    url = _pick(r, "url")
    source = _pick(r, "source", default=_pick(r, "category", default="web"))
    domain = _pick(r, "domain", default=_pick(r, "category", default="web"))

    published = _pick(r, "published")
    evidence_level = _pick(r, "evidence_level", default="other")

    desc = _safe_trim(_pick(r, "description"), 800)
    content = _safe_trim(_pick(r, "content"), 2400)

    spans = _flatten_spans(r.get("evidence_spans"))
    evidence: List[str] = [_safe_trim(s, 500) for s in spans if s]

    # Fallback evidence if none provided
    if not evidence:
        if desc:
            evidence = [desc]
        elif content:
            evidence = [_safe_trim(content, 500)]
        else:
            evidence = []

    # If evidence exists but title is generic, keep it anyway (sentinel handling is upstream)
    cite_id = _make_cite_id(r)

    intent_alignment = _as_float(r.get("intent_alignment"), 0.0)
    # clamp 0..1
    intent_alignment = max(0.0, min(1.0, intent_alignment))

    volatile = bool(r.get("volatile", False))

    return {
        "title": title,
        "url": url,
        "source": source or "web",
        "domain": domain or "web",
        "published": published,
        "evidence_level": evidence_level or "other",
        "snippet": desc,
        "content": content,
        "evidence": evidence,
        "cite_id": cite_id,
        "intent_alignment": intent_alignment,
        "volatile": volatile,
    }


def normalize_results(results: Any) -> List[Dict[str, Any]]:
    """
    Accepts anything: list[dict], list[mixed], dict, None.
    Returns normalized list[dict].
    """
    out: List[Dict[str, Any]] = []
    if not results:
        return out

    if isinstance(results, dict):
        out.append(_normalize_result(results))
        return out

    if not isinstance(results, list):
        return out

    for r in results:
        if isinstance(r, dict):
            out.append(_normalize_result(r))
        else:
            # If it's not a dict, wrap it as a minimal result rather than dropping
            s = _safe_trim(r, 200)
            if s:
                out.append(_normalize_result({"title": s, "url": "", "description": s}))
    return out


# -----------------------------
# Dedupe + sort
# -----------------------------
def dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dedupe by url else title.
    If duplicates exist, keep the one with more evidence.
    """
    best: Dict[str, Dict[str, Any]] = {}

    def key(it: Dict[str, Any]) -> str:
        u = _norm_space(it.get("url"))
        if u:
            return f"url::{u.lower()}"
        t = _norm_space(it.get("title"))
        return f"title::{t.lower()}" if t else ""

    for it in items:
        k = key(it)
        if not k:
            continue
        if k not in best:
            best[k] = it
        else:
            # prefer more evidence bullets; then longer snippet
            a = best[k]
            if len(it.get("evidence", [])) > len(a.get("evidence", [])):
                best[k] = it
            elif len(it.get("evidence", [])) == len(a.get("evidence", [])):
                if len(_norm_space(it.get("snippet"))) > len(_norm_space(a.get("snippet"))):
                    best[k] = it

    return list(best.values())


def sort_for_context(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic sort:
    - higher intent_alignment
    - evidence count
    - has url
    - has published
    """
    def k(it: Dict[str, Any]) -> Tuple[float, int, int, int]:
        ia = float(it.get("intent_alignment") or 0.0)
        evn = len(it.get("evidence") or [])
        has_url = 1 if _norm_space(it.get("url")).startswith("http") else 0
        has_pub = 1 if _norm_space(it.get("published")) else 0
        return (ia, evn, has_url, has_pub)

    return sorted(items, key=k, reverse=True)


# -----------------------------
# Public: build blocks
# -----------------------------
def build_context_block(
    results: Any,
    *,
    max_items: int = 8,
    max_evidence_bullets: int = 3,
    max_bullet_len: int = 220,
    include_meta: bool = True,
) -> str:
    """
    Tight evidence block for LLM prompt input.
    Never throws.
    """
    items = normalize_results(results)
    items = dedupe_items(items)
    items = sort_for_context(items)
    items = items[: max(1, int(max_items))]

    if not items:
        return "## Evidence (curated)\n- [WEB-0000000000] No usable sources were returned."

    lines: List[str] = ["## Evidence (curated)"]

    for it in items:
        cite = it.get("cite_id") or "WEB-0000000000"
        title = _safe_trim(it.get("title") or "", 140) or "Untitled result"
        url = _norm_space(it.get("url"))
        src = _safe_trim(it.get("source") or "web", 40)
        dom = _safe_trim(it.get("domain") or "web", 40)
        pub = _safe_trim(it.get("published") or "", 20)
        lvl = _safe_trim(it.get("evidence_level") or "other", 20)

        lines.append(f"- [{cite}] {title}")
        if url:
            lines.append(f"  url: {url}")

        if include_meta:
            meta_bits = [f"src={src}", f"dom={dom}", f"level={lvl}"]
            if pub:
                meta_bits.append(f"date={pub}")
            lines.append(f"  meta: {', '.join(meta_bits)}")

        ev = it.get("evidence") or []
        ev = [e for e in ev if _norm_space(e)]
        if ev:
            for b in ev[: max(1, int(max_evidence_bullets))]:
                lines.append(f"  • {_safe_trim(b, int(max_bullet_len))}")

    return "\n".join(lines).strip()


def build_human_digest(results: Any, *, max_items: int = 10) -> str:
    """
    Debug-friendly digest for terminal/log UI.
    Never throws.
    """
    items = normalize_results(results)
    items = dedupe_items(items)
    items = sort_for_context(items)
    items = items[: max(1, int(max_items))]

    if not items:
        return "No usable sources were returned."

    lines: List[str] = []
    for it in items:
        lines.append(f"- {it.get('title','').strip()}")
        lines.append(f"  cite: {it.get('cite_id')}")
        lines.append(f"  url: {it.get('url')}")
        lines.append(f"  src/domain: {it.get('source')}/{it.get('domain')}")
        if it.get("published"):
            lines.append(f"  date: {it.get('published')}")
        if it.get("evidence_level"):
            lines.append(f"  level: {it.get('evidence_level')}")
        ev = it.get("evidence") or []
        if ev:
            lines.append(f"  evidence: {_safe_trim(ev[0], 240)}")
        lines.append("")
    return "\n".join(lines).rstrip()
