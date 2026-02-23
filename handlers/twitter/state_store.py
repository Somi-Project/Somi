import json
import time
from datetime import datetime
from pathlib import Path
from threading import Lock


class StateStore:
    def __init__(self, path: str = "twitter_state.json"):
        self.path = Path(path)
        self._lock = Lock()
        self.state = self._load()
        self._cleanup()

    def _default_state(self):
        return {
            "processed_tweets": {},
            "per_user_hour": {},
            "hourly_actions": {},
            "daily_counts": {},
            "failure_streak": 0,
            "observe_only_until": 0,
            "last_trend_scan_day": "",
        }

    def _load(self):
        if not self.path.exists():
            return self._default_state()
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            return self._default_state()
        merged = self._default_state()
        merged.update(data)
        return merged

    def save(self):
        with self._lock:
            self.path.write_text(json.dumps(self.state, indent=2))

    def _cleanup(self):
        now = time.time()
        self.state["processed_tweets"] = {
            k: v for k, v in self.state["processed_tweets"].items()
            if now - float(v.get("timestamp", now)) <= 48 * 3600
        }
        current_hour = datetime.utcnow().strftime("%Y-%m-%d-%H")
        self.state["per_user_hour"] = {
            k: v for k, v in self.state["per_user_hour"].items() if k.startswith(current_hour)
        }
        self.state["hourly_actions"] = {
            k: v for k, v in self.state["hourly_actions"].items() if k.startswith(current_hour)
        }
        self.save()

    def seen(self, tweet_id: str) -> bool:
        return str(tweet_id) in self.state["processed_tweets"]

    def mark_processed(self, tweet_id: str, kind: str):
        self.state["processed_tweets"][str(tweet_id)] = {"timestamp": time.time(), "kind": kind}
        self.save()

    def in_observe_only(self) -> bool:
        return time.time() < float(self.state.get("observe_only_until", 0))

    def set_observe_only(self, seconds: int):
        self.state["observe_only_until"] = time.time() + max(0, int(seconds))
        self.save()

    def register_failure(self):
        self.state["failure_streak"] = int(self.state.get("failure_streak", 0)) + 1
        self.save()

    def clear_failures(self):
        self.state["failure_streak"] = 0
        self.save()

    def get_failure_streak(self) -> int:
        return int(self.state.get("failure_streak", 0))

    def _hour_key(self):
        return datetime.utcnow().strftime("%Y-%m-%d-%H")

    def _day_key(self):
        return datetime.utcnow().strftime("%Y-%m-%d")

    def can_reply_user(self, username: str, cap: int) -> bool:
        key = f"{self._hour_key()}::{username.lower()}"
        return int(self.state["per_user_hour"].get(key, 0)) < int(cap)

    def mark_reply_user(self, username: str):
        key = f"{self._hour_key()}::{username.lower()}"
        self.state["per_user_hour"][key] = int(self.state["per_user_hour"].get(key, 0)) + 1
        self.save()

    def can_take_hourly_action(self, cap: int) -> bool:
        key = self._hour_key()
        return int(self.state["hourly_actions"].get(key, 0)) < int(cap)

    def mark_hourly_action(self):
        key = self._hour_key()
        self.state["hourly_actions"][key] = int(self.state["hourly_actions"].get(key, 0)) + 1
        self.save()

    def get_daily_count(self, action: str) -> int:
        day = self._day_key()
        return int(self.state["daily_counts"].get(day, {}).get(action, 0))

    def mark_daily_count(self, action: str):
        day = self._day_key()
        self.state["daily_counts"].setdefault(day, {})
        self.state["daily_counts"][day][action] = int(self.state["daily_counts"][day].get(action, 0)) + 1
        self.save()
