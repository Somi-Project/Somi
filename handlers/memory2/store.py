from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from config.settings import MEMORY_STORE_DIR, MEMORY2_EVENT_LOG_ENABLED

EVENTS_PATH = os.path.join(MEMORY_STORE_DIR, "events.jsonl")
FACTS_PATH = os.path.join(MEMORY_STORE_DIR, "facts.jsonl")
SKILLS_PATH = os.path.join(MEMORY_STORE_DIR, "skills.jsonl")
REMINDERS_PATH = os.path.join(MEMORY_STORE_DIR, "reminders.jsonl")
STATE_PATH = os.path.join(MEMORY_STORE_DIR, "state.json")


def ensure_store_dir() -> None:
    os.makedirs(MEMORY_STORE_DIR, exist_ok=True)
    for p in (EVENTS_PATH, FACTS_PATH, SKILLS_PATH, REMINDERS_PATH):
        if not os.path.exists(p):
            with open(p, "a", encoding="utf-8"):
                pass


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    ensure_store_dir()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    ensure_store_dir()
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except Exception:
        return []
    return out


def atomic_write_json(path: str, obj: Dict[str, Any]) -> None:
    ensure_store_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_facts() -> List[Dict[str, Any]]:
    return read_jsonl(FACTS_PATH)


def load_skills() -> List[Dict[str, Any]]:
    return read_jsonl(SKILLS_PATH)


def load_events() -> List[Dict[str, Any]]:
    return read_jsonl(EVENTS_PATH)


def load_reminders() -> List[Dict[str, Any]]:
    return read_jsonl(REMINDERS_PATH)


def write_fact(fact: Dict[str, Any]) -> None:
    append_jsonl(FACTS_PATH, fact)


def write_skill(skill: Dict[str, Any]) -> None:
    append_jsonl(SKILLS_PATH, skill)


def write_event(event: Dict[str, Any]) -> None:
    if not MEMORY2_EVENT_LOG_ENABLED:
        return
    append_jsonl(EVENTS_PATH, event)


def write_reminder(reminder: Dict[str, Any]) -> None:
    append_jsonl(REMINDERS_PATH, reminder)
