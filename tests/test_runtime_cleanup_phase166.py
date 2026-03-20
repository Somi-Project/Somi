from __future__ import annotations

import unittest
from unittest.mock import patch

from executive.memory.embedder import OllamaEmbedder
from runtime.ollama_compat import close_async_client


class _DummyAsyncClient:
    def __init__(self) -> None:
        self.closed = False
        self.calls = 0

    async def embeddings(self, *, model: str, prompt: str):
        del model, prompt
        self.calls += 1
        return {"embedding": [0.1, 0.2, 0.3]}

    async def aclose(self):
        self.closed = True


class _DummySyncClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self):
        self.closed = True


class RuntimeCleanupPhase166Tests(unittest.IsolatedAsyncioTestCase):
    async def test_embedder_closes_ephemeral_client_after_embedding(self) -> None:
        created: list[_DummyAsyncClient] = []

        def _factory():
            client = _DummyAsyncClient()
            created.append(client)
            return client

        with patch("executive.memory.embedder.create_async_client", side_effect=_factory):
            embedder = OllamaEmbedder(client=None, dim=3)
            vector = await embedder.embed("repair the generator")
            self.assertEqual(vector, [0.1, 0.2, 0.3])
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0].closed)

    async def test_close_async_client_handles_sync_close(self) -> None:
        client = _DummySyncClient()
        await close_async_client(client)
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
