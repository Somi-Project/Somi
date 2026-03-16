from __future__ import annotations

import math
from typing import Any, Iterable


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _collect_series(candles: Iterable[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for row in candles:
        if not isinstance(row, dict):
            continue
        val = _finite_float(row.get(key))
        if val is None:
            continue
        out.append(val)
    return out


def compute_historical_summary(candles: Iterable[dict[str, Any]]) -> dict[str, float | None]:
    rows = list(candles or [])

    closes = _collect_series(rows, "close")
    lows = _collect_series(rows, "low")
    highs = _collect_series(rows, "high")

    first_close = closes[0] if closes else None
    last_close = closes[-1] if closes else None
    min_low = min(lows) if lows else None
    max_high = max(highs) if highs else None

    return_pct: float | None = None
    if first_close not in (None, 0.0) and last_close is not None:
        return_pct = ((last_close - first_close) / first_close) * 100.0

    return {
        "first_close": first_close,
        "last_close": last_close,
        "min_low": min_low,
        "max_high": max_high,
        "return_pct": return_pct,
    }



