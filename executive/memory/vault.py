from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from .store import SQLiteMemoryStore, utcnow_iso

TEXT_SUFFIXES = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".ps1",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
IGNORED_DIRS = {".git", ".venv", "__pycache__", "backups", "node_modules"}


def _clip(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class KnowledgeVaultService:
    def __init__(
        self,
        *,
        store: SQLiteMemoryStore | None = None,
        embed_text: Callable[[str], Any] | Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.store = store or SQLiteMemoryStore()
        self._embed_text = embed_text

    async def _embed_safe(self, text: str) -> list[float] | None:
        if self._embed_text is None or not str(text or "").strip():
            return None
        try:
            result = self._embed_text(text)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, list):
                return [float(item) for item in result]
        except Exception:
            return None
        return None

    def _source_id(self, *, user_id: str, source_type: str, title: str, location: str) -> str:
        basis = f"{user_id}|{source_type}|{title}|{location}".encode("utf-8")
        return f"vault-{hashlib.sha256(basis).hexdigest()[:24]}"

    def _chunk_text(self, text: str, *, max_chars: int = 680, overlap: int = 120) -> list[str]:
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []

        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        if not paragraphs:
            paragraphs = [normalized]

        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current.strip())
            if len(paragraph) <= max_chars:
                current = paragraph
                continue

            words = paragraph.split()
            running = ""
            for word in words:
                test = f"{running} {word}".strip()
                if len(test) <= max_chars:
                    running = test
                    continue
                if running:
                    chunks.append(running.strip())
                tail = running[-min(overlap, len(running)) :] if overlap > 0 and running else ""
                running = f"{tail} {word}".strip()
            current = running
        if current:
            chunks.append(current.strip())
        return [_clip(chunk, limit=max_chars) for chunk in chunks if chunk.strip()]

    def _read_text_file(self, path: Path, *, max_chars: int = 120000) -> str:
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            return ""
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        if suffix in {".json", ".jsonl"}:
            try:
                parsed = json.loads(raw)
                raw = json.dumps(parsed, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return raw[: max(0, int(max_chars or 120000))]

    async def ingest_text(
        self,
        *,
        user_id: str,
        title: str,
        text: str,
        location: str = "",
        source_type: str = "note",
        content_type: str = "text/plain",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        chunks = self._chunk_text(text)
        source_id = self._source_id(
            user_id=str(user_id or "default_user"),
            source_type=str(source_type or "note"),
            title=str(title or "Untitled"),
            location=str(location or ""),
        )
        source = self.store.upsert_source(
            {
                "source_id": source_id,
                "user_id": str(user_id or "default_user"),
                "source_type": str(source_type or "note"),
                "title": str(title or "Untitled"),
                "location": str(location or ""),
                "content_type": str(content_type or "text/plain"),
                "item_count": len(chunks),
                "status": "active",
                "metadata": dict(metadata or {}),
                "updated_at": utcnow_iso(),
            }
        )

        written = 0
        for index, chunk in enumerate(chunks, start=1):
            slot_key = f"vault.{source_id}.{index}"
            current = self.store.active_by_slot(str(user_id or "default_user"), slot_key)
            if current:
                self.store.set_status(str(current.get("id")), "superseded")
            item_id = hashlib.sha256(f"{slot_key}:{utcnow_iso()}".encode("utf-8")).hexdigest()
            payload = {
                "id": item_id,
                "user_id": str(user_id or "default_user"),
                "lane": "vault",
                "type": "vault_chunk",
                "entity": "knowledge",
                "mkey": str(source_type or "note"),
                "value": _clip(title, limit=120),
                "kind": "vault",
                "bucket": "knowledge",
                "importance": 0.74,
                "text": chunk,
                "tags": " ".join(["vault", str(source_type or "note")] + [str(tag) for tag in list(tags or [])[:8]]),
                "confidence": 0.72,
                "status": "active",
                "expires_at": None,
                "scope": "vault",
                "mem_type": "vault_document",
                "entities_json": json.dumps(
                    {
                        "source_id": source_id,
                        "title": str(title or "Untitled"),
                        "location": str(location or ""),
                        "content_type": str(content_type or "text/plain"),
                        "chunk_index": index,
                        "chunk_total": len(chunks),
                        "metadata": dict(metadata or {}),
                    },
                    ensure_ascii=False,
                ),
                "tags_json": json.dumps(["vault", str(source_type or "note")] + [str(tag) for tag in list(tags or [])[:8]], ensure_ascii=False),
                "slot_key": slot_key,
                "created_at": utcnow_iso(),
                "updated_at": utcnow_iso(),
            }
            embedding = await self._embed_safe(chunk)
            self.store.write_item(payload, embedding=embedding)
            written += 1

        self.store.log_event(
            str(user_id or "default_user"),
            "vault_ingest",
            source_id,
            {
                "source_type": str(source_type or "note"),
                "title": str(title or "Untitled"),
                "location": str(location or ""),
                "written_items": written,
            },
        )
        return {
            "ok": True,
            "source_id": source_id,
            "title": str(title or "Untitled"),
            "written_items": written,
            "chunk_total": len(chunks),
            "source": source,
        }

    async def ingest_file(
        self,
        path: str | os.PathLike[str],
        *,
        user_id: str,
        title: str = "",
        source_type: str = "document",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            return {"ok": False, "reason": "missing_file", "path": str(file_path)}
        text = self._read_text_file(file_path)
        if not text.strip():
            return {"ok": False, "reason": "unsupported_or_empty", "path": str(file_path)}
        return await self.ingest_text(
            user_id=user_id,
            title=str(title or file_path.name),
            text=text,
            location=str(file_path),
            source_type=source_type,
            content_type="text/plain",
            metadata={"path": str(file_path), **dict(metadata or {})},
            tags=list(tags or []) or [file_path.suffix.lstrip(".") or "text"],
        )

    async def ingest_workspace(
        self,
        path: str | os.PathLike[str],
        *,
        user_id: str,
        limit_files: int = 24,
        include_suffixes: set[str] | None = None,
    ) -> dict[str, Any]:
        root = Path(path)
        if not root.exists() or not root.is_dir():
            return {"ok": False, "reason": "missing_workspace", "path": str(root)}

        suffixes = {str(item).lower() for item in (include_suffixes or TEXT_SUFFIXES)}
        results: list[dict[str, Any]] = []
        skipped: list[str] = []
        for file_path in sorted(root.rglob("*")):
            if len(results) >= max(1, int(limit_files or 24)):
                break
            if not file_path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in file_path.parts):
                continue
            if file_path.suffix.lower() not in suffixes:
                skipped.append(str(file_path))
                continue
            result = await self.ingest_file(
                file_path,
                user_id=user_id,
                title=file_path.name,
                source_type="workspace_file",
                metadata={"workspace_root": str(root)},
                tags=["workspace", file_path.suffix.lstrip(".") or "text"],
            )
            if result.get("ok"):
                results.append(result)
            else:
                skipped.append(str(file_path))
        return {
            "ok": True,
            "workspace_root": str(root),
            "ingested_count": len(results),
            "sources": results,
            "skipped": skipped[:12],
        }

    def list_sources(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.list_sources(str(user_id or "default_user"), limit=max(1, int(limit or 20)))

    def source_summary(self, user_id: str) -> dict[str, Any]:
        return self.store.source_summary(str(user_id or "default_user"))
