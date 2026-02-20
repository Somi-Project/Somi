from __future__ import annotations

import os
import sys

# Allow standalone execution without shadowing stdlib `types`
_THIS_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
if _THIS_DIR in sys.path:
    sys.path.remove(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import argparse
import asyncio
import shutil
from datetime import datetime, timedelta, timezone

from handlers.memory2.manager import Memory2Manager
from handlers.memory2.store import FACTS_PATH, SKILLS_PATH, load_facts, load_skills
from handlers.memory2.types import FactCandidate, SkillCandidate


def fail(msg: str) -> None:
    raise SystemExit(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if args.reset and os.path.exists("memory_store"):
        shutil.rmtree("memory_store", ignore_errors=True)

    m = Memory2Manager()

    m.upsert_fact(FactCandidate(key="output_format", value="don't output json", kind="preference", confidence=0.9))
    m.upsert_fact(FactCandidate(key="timezone", value="America/New_York", kind="profile", confidence=0.9))
    m.upsert_fact(FactCandidate(key="location", value="New York", kind="profile", confidence=0.8))
    m.upsert_fact(FactCandidate(key="location", value="Miami", kind="profile", confidence=0.8))
    m.upsert_fact(FactCandidate(key="preferred_name", value="Ace", kind="volatile", confidence=0.8, expires_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()))
    m.expire_volatiles()

    m.add_skill(SkillCandidate(trigger="fixed memory retrieval", steps=["open file", "patch logic", "run tests"], tags=["memory", "python"], confidence=0.7))

    rid = asyncio.run(m.add_reminder("default_user", "take pills", "in 1 seconds"))
    if not rid:
        fail("expected reminder id")
    due = asyncio.run(m.peek_due_reminders("default_user", limit=5))
    if due:
        pass

    facts = load_facts()
    skills = load_skills()
    m.reload()

    logical_active = list(m._active_by_entity_key.values())
    active_locations = [f for f in logical_active if f.get("key") == "location"]
    if len(active_locations) != 1:
        fail("expected one active location fact")
    if active_locations[0].get("value") != "Miami":
        fail("expected Miami as active location")

    expired = [f for f in facts if f.get("key") == "preferred_name" and f.get("status") == "expired"]
    if not expired:
        fail("expected volatile expiry tombstone")

    block = m.retrieve_context("what do i prefer and memory retrieval steps")
    if len(block) > 2200:
        fail("compiled memory block exceeds cap")
    if "Preferences:" not in block:
        fail("missing preferences section")
    if "don't output json" not in block.lower():
        fail("preference missing in context")
    if not skills:
        fail("expected at least one skill")

    if not os.path.exists(FACTS_PATH) or not os.path.exists(SKILLS_PATH):
        fail("store files missing")

    print("memory2 tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
