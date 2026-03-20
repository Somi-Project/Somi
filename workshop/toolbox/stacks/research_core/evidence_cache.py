from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc_iso(value: str) -> Optional[datetime]:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def canonicalize_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        return ""
    try:
        parsed = urlparse(clean)
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.netloc or "").lower()
        if ":" in host:
            name, port = host.rsplit(":", 1)
            if port.isdigit() and ((scheme == "http" and port == "80") or (scheme == "https" and port == "443")):
                host = name
        path = parsed.path or "/"
        if path.endswith(("/index.html", "/index.htm", "/index.php")):
            path = path[: path.rfind("/")] or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        kept = []
        for key, value in parse_qsl(parsed.query or "", keep_blank_values=True):
            if key.lower() in _TRACKING_KEYS:
                continue
            kept.append((key, value))
        query = urlencode(sorted(kept), doseq=True)
        return urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return clean


def cache_identity(query: str, *, mode: str, domain: str) -> str:
    normalized_query = " ".join(str(query or "").lower().split())
    basis = f"{str(domain or 'general').strip().lower()}::{str(mode or 'deep').strip().lower()}::{normalized_query}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


class EvidenceCacheStore:
    def __init__(
        self,
        root: str | Path = "state/research_cache",
        *,
        ttl_seconds: int = 1800,
        max_records: int = 256,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(60, int(ttl_seconds or 1800))
        self.max_records = max(32, int(max_records or 256))

    def _path_for(self, query: str, *, mode: str, domain: str) -> Path:
        return self.root / f"{cache_identity(query, mode=mode, domain=domain)}.json"

    def load(self, query: str, *, mode: str, domain: str = "general") -> Optional[Dict[str, Any]]:
        path = self._path_for(query, mode=mode, domain=domain)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        expires_at = parse_utc_iso(str((payload or {}).get("expires_at") or ""))
        if expires_at and datetime.now(timezone.utc) > expires_at:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return payload if isinstance(payload, dict) else None

    def save(self, query: str, payload: Dict[str, Any], *, mode: str, domain: str = "general") -> Path:
        record = dict(payload or {})
        now = datetime.now(timezone.utc).replace(microsecond=0)
        saved_at = parse_utc_iso(str(record.get("saved_at") or "")) or now
        expires_at = parse_utc_iso(str(record.get("expires_at") or "")) or (saved_at + timedelta(seconds=self.ttl_seconds))
        record["query"] = str(record.get("query") or query or "").strip()
        record["mode"] = str(record.get("mode") or mode or "deep").strip().lower()
        record["domain"] = str(record.get("domain") or domain or "general").strip().lower()
        record["saved_at"] = saved_at.isoformat()
        record["expires_at"] = expires_at.isoformat()
        path = self._path_for(query, mode=mode, domain=domain)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        self._prune()
        return path

    def age_seconds(self, payload: Dict[str, Any]) -> Optional[float]:
        saved_at = parse_utc_iso(str((payload or {}).get("saved_at") or ""))
        if not saved_at:
            return None
        return max(0.0, (datetime.now(timezone.utc) - saved_at).total_seconds())

    def _prune(self) -> None:
        paths = sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in paths[self.max_records :]:
            try:
                stale.unlink()
            except OSError:
                pass
