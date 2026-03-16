from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class QuerySpec:
    asset_class: str
    symbol: str
    query_type: str
    start: date | None
    end: date | None
    interval: str


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.now(timezone.utc).date()


def normalize_query_spec(
    *,
    asset_class: str,
    symbol: str,
    query_type: str,
    now_ts: date | datetime | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    interval: str | None = None,
) -> QuerySpec:
    asset = str(asset_class or "equity").strip().lower() or "equity"
    ticker = str(symbol or "").strip().upper()
    qtype = str(query_type or "latest").strip().lower() or "latest"

    start_date = _to_date(start) if start is not None else None
    end_date = _to_date(end) if end is not None else None

    if qtype == "historical":
        today = _to_date(now_ts)
        end_date = end_date or today
        start_date = start_date or (end_date - timedelta(days=365))
        resolved_interval = (interval or "1d").strip() or "1d"
    else:
        resolved_interval = (interval or "1m").strip() or "1m"

    return QuerySpec(
        asset_class=asset,
        symbol=ticker,
        query_type=qtype,
        start=start_date,
        end=end_date,
        interval=resolved_interval,
    )



