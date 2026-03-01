from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GOOGLE_CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
MSGRAPH_CALENDAR_READ_SCOPE = "Calendars.Read"


@dataclass
class NullCalendarProvider:
    def get_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return []


@dataclass
class JsonCalendarProvider:
    """Read-only local provider reading events from JSON file."""

    path: str

    def get_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        p = Path(self.path)
        if not p.exists():
            return []
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in list(rows or []):
            evt = _normalize_event(row)
            if not evt:
                continue
            st_dt = _parse_iso(evt["start"])
            ed_dt = _parse_iso(evt["end"])
            if not st_dt or not ed_dt:
                continue
            if ed_dt < start or st_dt > end:
                continue
            out.append(evt)
        return out


@dataclass
class GoogleCalendarProvider:
    access_token: str
    calendar_id: str = "primary"

    def get_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.access_token:
            return []
        params = urllib.parse.urlencode(
            {
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeMin": start.astimezone(timezone.utc).isoformat(),
                "timeMax": end.astimezone(timezone.utc).isoformat(),
            }
        )
        cal_id = urllib.parse.quote(self.calendar_id, safe="")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.access_token}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in list(payload.get("items") or []):
            evt = {
                "id": str(row.get("id") or ""),
                "title": str(row.get("summary") or "event")[:160],
                "start": str((row.get("start") or {}).get("dateTime") or (row.get("start") or {}).get("date") or ""),
                "end": str((row.get("end") or {}).get("dateTime") or (row.get("end") or {}).get("date") or ""),
            }
            n = _normalize_event(evt)
            if n:
                out.append(n)
        return out


@dataclass
class MsGraphCalendarProvider:
    access_token: str

    def get_events(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.access_token:
            return []
        params = urllib.parse.urlencode(
            {
                "startDateTime": start.astimezone(timezone.utc).isoformat(),
                "endDateTime": end.astimezone(timezone.utc).isoformat(),
            }
        )
        url = f"https://graph.microsoft.com/v1.0/me/calendarView?{params}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.access_token}"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in list(payload.get("value") or []):
            evt = {
                "id": str(row.get("id") or ""),
                "title": str(row.get("subject") or "event")[:160],
                "start": str((row.get("start") or {}).get("dateTime") or ""),
                "end": str((row.get("end") or {}).get("dateTime") or ""),
            }
            n = _normalize_event(evt)
            if n:
                out.append(n)
        return out


def get_calendar_provider(settings_module: Any) -> Any:
    mode = str(getattr(settings_module, "PHASE7_CALENDAR_PROVIDER", "null")).strip().lower()
    if mode == "json":
        return JsonCalendarProvider(path=str(getattr(settings_module, "PHASE7_CALENDAR_JSON_PATH", "sessions/calendar/events.json")))
    if mode == "google":
        return GoogleCalendarProvider(
            access_token=str(getattr(settings_module, "PHASE7_GOOGLE_CALENDAR_ACCESS_TOKEN", "")),
            calendar_id=str(getattr(settings_module, "PHASE7_GOOGLE_CALENDAR_ID", "primary")),
        )
    if mode in {"msgraph", "microsoft"}:
        return MsGraphCalendarProvider(access_token=str(getattr(settings_module, "PHASE7_MSGRAPH_ACCESS_TOKEN", "")))
    return NullCalendarProvider()


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _normalize_event(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    st = str(row.get("start") or "").strip()
    ed = str(row.get("end") or "").strip()
    st_dt = _parse_iso(st)
    ed_dt = _parse_iso(ed)
    if not st_dt or not ed_dt:
        return None
    return {
        "id": str(row.get("id") or f"cal_{abs(hash(st + ed)) % 1_000_000}"),
        "title": str(row.get("title") or "event")[:160],
        "start": st_dt.isoformat(),
        "end": ed_dt.isoformat(),
    }


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return str(a.get("start") or "") < str(b.get("end") or "") and str(b.get("start") or "") < str(a.get("end") or "")


def _write_cache(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_snapshot(start: datetime, end: datetime, provider: Any | None = None, *, cache_path: str | None = None) -> dict[str, Any]:
    provider = provider or NullCalendarProvider()
    events = sorted(list(provider.get_events(start, end) or []), key=lambda x: str(x.get("start") or ""))
    conflicts: list[dict[str, Any]] = []
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if _overlap(events[i], events[j]):
                conflicts.append(
                    {
                        "event_ids": [events[i].get("id"), events[j].get("id")],
                        "start": max(str(events[i].get("start") or ""), str(events[j].get("start") or "")),
                        "end": min(str(events[i].get("end") or ""), str(events[j].get("end") or "")),
                    }
                )
    snapshot = {
        "artifact_type": "calendar_snapshot",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "events": events,
        "conflicts": conflicts,
    }
    _write_cache(cache_path, snapshot)
    return snapshot
