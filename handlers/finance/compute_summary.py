from __future__ import annotations

from typing import Any, Dict, List


def compute_historical_summary(candles: List[Dict[str, Any]]) -> Dict[str, float]:
    if not candles:
        raise ValueError("NoDataError")

    first_close = float(candles[0]["close"])
    last_close = float(candles[-1]["close"])
    min_low = min(float(c["low"]) for c in candles)
    max_high = max(float(c["high"]) for c in candles)
    ret = 0.0 if first_close == 0 else ((last_close - first_close) / first_close) * 100.0

    return {
        "first_close": first_close,
        "last_close": last_close,
        "min_low": min_low,
        "max_high": max_high,
        "return_pct": ret,
    }
