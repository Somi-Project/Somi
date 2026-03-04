from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class QuerySpec:
    asset_class: str
    symbol: str
    query_type: str  # spot | historical
    interval: Optional[str] = None
    start: Optional[date] = None
    end: Optional[date] = None
    now_ts: Optional[datetime] = None


def normalize_query_spec(
    *,
    asset_class: str,
    symbol: str,
    query_type: str,
    interval: Optional[str] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    now_ts: Optional[datetime] = None,
) -> QuerySpec:
    qt = (query_type or "spot").strip().lower()
    ac = (asset_class or "equity").strip().lower()
    sym = (symbol or "").strip().upper()
    now = now_ts or datetime.utcnow()

    if qt == "spot":
        return QuerySpec(asset_class=ac, symbol=sym, query_type="spot", now_ts=now)

    hist_interval = (interval or "1d").strip()
    if not start or not end:
        today = now.date()
        end_date = end or today
        start_date = start or (end_date - timedelta(days=365))
    else:
        start_date = start
        end_date = end

    return QuerySpec(
        asset_class=ac,
        symbol=sym,
        query_type="historical",
        interval=hist_interval,
        start=start_date,
        end=end_date,
        now_ts=now,
    )
