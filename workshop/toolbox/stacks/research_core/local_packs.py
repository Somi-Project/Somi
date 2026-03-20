from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_REQUIRED_CATEGORIES = ("repair", "survival", "infrastructure")
_DOC_SUFFIXES = {".md", ".txt"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "with",
}


def knowledge_pack_root(root_dir: str | Path = ".") -> Path:
    return Path(root_dir) / "knowledge_packs"


def _read_manifest(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return clean.strip("-") or "pack"


def _query_tokens(query: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", str(query or "").lower())
    seen: set[str] = set()
    out: List[str] = []
    for token in tokens:
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _heading(text: str) -> str:
    for line in str(text or "").splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean
    return ""


def _excerpt(text: str, *, limit: int = 360) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _pack_directories(root_dir: str | Path = ".") -> List[Path]:
    root = knowledge_pack_root(root_dir)
    if not root.exists():
        return []
    return [path for path in sorted(root.iterdir()) if path.is_dir()]


def _normalized_manifest(pack_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = str(manifest.get("id") or pack_dir.name).strip() or pack_dir.name
    return {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id.replace("_", " ").title()).strip(),
        "category": str(manifest.get("category") or pack_id).strip().lower(),
        "summary": str(manifest.get("summary") or "").strip(),
        "tags": [str(item).strip() for item in list(manifest.get("tags") or []) if str(item).strip()],
        "status": str(manifest.get("status") or "ready").strip().lower(),
        "schema_version": max(1, int(manifest.get("schema_version") or 1)),
        "variant": str(manifest.get("variant") or "compact").strip().lower() or "compact",
        "trust": str(manifest.get("trust") or "bundled_local").strip().lower() or "bundled_local",
        "updated_at": str(manifest.get("updated_at") or "").strip(),
    }


def scan_local_packs(
    root_dir: str | Path = ".",
    *,
    required_categories: Iterable[str] = DEFAULT_REQUIRED_CATEGORIES,
) -> Dict[str, Any]:
    root = knowledge_pack_root(root_dir)
    packs: List[Dict[str, Any]] = []
    categories_present: List[str] = []
    total_bytes = 0
    total_docs = 0
    broken_manifests: List[str] = []
    schema_versions: List[int] = []
    variants_present: List[str] = []
    for pack_dir in _pack_directories(root_dir):
        manifest_path = pack_dir / "manifest.json"
        manifest = _read_manifest(manifest_path)
        if not manifest:
            broken_manifests.append(str(manifest_path))
        normalized = _normalized_manifest(pack_dir, manifest)
        pack_id = str(normalized.get("id") or pack_dir.name).strip() or pack_dir.name
        name = str(normalized.get("name") or pack_id.replace("_", " ").title()).strip()
        category = str(normalized.get("category") or pack_id).strip().lower()
        summary = str(normalized.get("summary") or "").strip()
        tags = [str(item).strip() for item in list(normalized.get("tags") or []) if str(item).strip()]
        docs = [path for path in sorted(pack_dir.iterdir()) if path.is_file() and path.suffix.lower() in _DOC_SUFFIXES]
        doc_rows: List[Dict[str, Any]] = []
        for doc in docs:
            text = _read_text(doc)
            total_bytes += doc.stat().st_size if doc.exists() else 0
            total_docs += 1
            doc_rows.append(
                {
                    "name": doc.name,
                    "path": str(doc),
                    "title": _heading(text) or doc.stem.replace("_", " ").title(),
                    "excerpt": _excerpt(text, limit=180),
                    "bytes": doc.stat().st_size if doc.exists() else 0,
                    "sha256": _sha256_text(text),
                }
            )
        if category and category not in categories_present:
            categories_present.append(category)
        schema_version = int(normalized.get("schema_version") or 1)
        variant = str(normalized.get("variant") or "compact").strip().lower()
        if schema_version not in schema_versions:
            schema_versions.append(schema_version)
        if variant and variant not in variants_present:
            variants_present.append(variant)
        pack_integrity = _sha256_text(
            json.dumps(normalized, sort_keys=True, ensure_ascii=False) + "|" + "|".join(str(doc.get("sha256") or "") for doc in doc_rows)
        )
        packs.append(
            {
                "id": pack_id,
                "name": name,
                "category": category,
                "summary": summary,
                "tags": tags,
                "status": str(normalized.get("status") or ("ready" if docs else "empty")).strip().lower(),
                "manifest_path": str(manifest_path),
                "schema_version": schema_version,
                "variant": variant,
                "trust": str(normalized.get("trust") or "bundled_local"),
                "updated_at": str(normalized.get("updated_at") or ""),
                "integrity": pack_integrity,
                "doc_count": len(doc_rows),
                "documents": doc_rows,
            }
        )
    missing = [str(item).strip().lower() for item in required_categories if str(item).strip().lower() not in categories_present]
    readiness = "ready" if packs and not missing else ("partial" if packs else "blocked")
    recommendations: List[str] = []
    if missing:
        recommendations.append(f"Add bundled local packs for the missing offline categories: {', '.join(missing)}.")
    if broken_manifests:
        recommendations.append("Repair invalid pack manifests so offline pack metadata stays trustworthy.")
    if not packs:
        recommendations.append("Add at least one bundled local pack so Somi can keep helping when connectivity drops.")
    return {
        "ok": readiness != "blocked",
        "readiness": readiness,
        "pack_root": str(root),
        "pack_count": len(packs),
        "document_count": total_docs,
        "total_megabytes": round(total_bytes / (1024.0 * 1024.0), 3),
        "schema_versions": sorted(schema_versions),
        "variants_present": variants_present,
        "categories_present": categories_present,
        "missing_categories": missing,
        "broken_manifests": broken_manifests,
        "recommendations": recommendations,
        "packs": packs,
    }


def search_local_pack_rows(root_dir: str | Path, query: str, *, limit: int = 4) -> List[Dict[str, Any]]:
    root = knowledge_pack_root(root_dir)
    if not root.exists():
        return []

    query_text = " ".join(str(query or "").split()).strip()
    query_lower = query_text.lower()
    tokens = _query_tokens(query_text)
    rows: List[Dict[str, Any]] = []
    for pack in list(scan_local_packs(root_dir).get("packs") or []):
        pack_id = str(pack.get("id") or "").strip()
        pack_name = str(pack.get("name") or pack_id).strip()
        pack_category = str(pack.get("category") or "").strip()
        tags = [str(item).strip().lower() for item in list(pack.get("tags") or []) if str(item).strip()]
        for doc in list(pack.get("documents") or []):
            doc_path = Path(str(doc.get("path") or ""))
            text = _read_text(doc_path)
            blob = " ".join(
                item
                for item in (
                    pack_name,
                    pack_category,
                    " ".join(tags),
                    str(pack.get("summary") or ""),
                    str(doc.get("title") or ""),
                    text,
                )
                if str(item or "").strip()
            ).lower()
            score = 0
            if query_lower and query_lower in blob:
                score += 8
            for token in tokens:
                if token in str(doc.get("title") or "").lower():
                    score += 3
                if token in pack_name.lower() or token in pack_category:
                    score += 2
                if token in tags:
                    score += 2
                if token in blob:
                    score += 1
            if score <= 0:
                continue
            doc_slug = _slug(doc_path.stem)
            rows.append(
                {
                    "title": str(doc.get("title") or doc_path.stem.replace("_", " ").title()).strip(),
                    "url": f"local://knowledge-pack/{pack_id}/{doc_slug}",
                    "description": _excerpt(str(doc.get("excerpt") or pack.get("summary") or ""), limit=320),
                    "content": _excerpt(text, limit=760),
                    "source": "local_pack",
                    "provider": "bundled_local_pack",
                    "knowledge_origin": "bundled_local_pack",
                    "pack_id": pack_id,
                    "pack_category": pack_category,
                    "pack_variant": str(pack.get("variant") or "compact"),
                    "local_path": str(doc_path),
                    "score": score,
                    "category": "general",
                    "volatile": False,
                }
            )
    rows.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("title") or "")))
    return rows[: max(1, int(limit or 4))]


def resolve_local_pack_url(root_dir: str | Path, url: str) -> Dict[str, Any]:
    raw = str(url or "").strip()
    if not raw.startswith("local://knowledge-pack/"):
        return {}
    parts = [segment for segment in raw.replace("local://knowledge-pack/", "", 1).split("/") if segment]
    if len(parts) < 2:
        return {}
    pack_id, doc_slug = parts[0], parts[1]
    for pack in list(scan_local_packs(root_dir).get("packs") or []):
        if str(pack.get("id") or "") != pack_id:
            continue
        for doc in list(pack.get("documents") or []):
            path = Path(str(doc.get("path") or ""))
            if _slug(path.stem) != doc_slug:
                continue
            text = _read_text(path)
            return {
                "pack_id": pack_id,
                "title": str(doc.get("title") or path.stem.replace("_", " ").title()).strip(),
                "path": str(path),
                "content": text,
                "integrity": str(pack.get("integrity") or ""),
                "sha256": str(doc.get("sha256") or ""),
                "variant": str(pack.get("variant") or "compact"),
                "trust": str(pack.get("trust") or "bundled_local"),
            }
    return {}
