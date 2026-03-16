from __future__ import annotations

import asyncio
from typing import Any


class MissingOllamaClient:
    """Async-compatible placeholder when ollama is unavailable."""

    async def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("ollama package is not installed")

    async def embeddings(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("ollama package is not installed")

    async def generate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("ollama package is not installed")


class ThreadedAsyncClient:
    """Wrap sync ollama.Client methods with asyncio.to_thread for async callers."""

    def __init__(self, sync_client: Any):
        self._sync_client = sync_client

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._sync_client, name)
        if not callable(attr):
            return attr

        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(attr, *args, **kwargs)

        return _wrapped


def create_async_client(**kwargs: Any) -> Any:
    """
    Return an async-compatible Ollama client across package versions.

    - Preferred: ollama.AsyncClient when available.
    - Fallback: wrap ollama.Client with async thread offloading.
    - Last resort: placeholder that raises a clear runtime error.
    """
    try:
        from ollama import AsyncClient as OllamaAsyncClient  # type: ignore

        return OllamaAsyncClient(**kwargs)
    except Exception:
        pass

    try:
        from ollama import Client as OllamaClient  # type: ignore

        return ThreadedAsyncClient(OllamaClient(**kwargs))
    except Exception:
        return MissingOllamaClient()
