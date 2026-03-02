from __future__ import annotations


class ProactiveNotifier:
    def __init__(self):
        self.messages: list[dict] = []

    def send(self, channel: str, text: str, metadata: dict | None = None) -> dict:
        payload = {"channel": channel, "text": text, "metadata": dict(metadata or {})}
        self.messages.append(payload)
        return payload
