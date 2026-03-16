from __future__ import annotations


def suggest_hello_intent() -> dict:
    return {"action": "create_tool", "payload": {"name": "hello_tool", "description": "Returns greeting + system time"}, "state": "PENDING"}
