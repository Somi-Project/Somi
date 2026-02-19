# handlers/websearch_tools/routing.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .utils import (
    normalize_query,
    looks_like_weather,
    looks_like_medical,
    looks_like_definition,
    looks_like_papers,
    looks_like_cs_ml,
    looks_like_coding,
    extract_location_simple,
)

@dataclass
class RouteDecision:
    route: str
    reason: str
    location: Optional[str] = None

def decide_vertical_route(query: str) -> RouteDecision:
    q = normalize_query(query)

    # Weather ONLY if location is present
    if looks_like_weather(q):
        loc = extract_location_simple(q)
        if loc:
            return RouteDecision("weather", "weather keywords + location detected", loc)
        return RouteDecision("general", "weather keywords but no location; avoid weather tool")

    if looks_like_medical(q):
        return RouteDecision("medical", "medical markers detected")
    if looks_like_definition(q):
        return RouteDecision("definition", "definition intent detected")
    if looks_like_coding(q):
        return RouteDecision("coding", "coding markers detected")
    if looks_like_papers(q):
        if looks_like_cs_ml(q):
            return RouteDecision("cs_ml", "cs/ml + paper markers detected")
        return RouteDecision("papers", "paper/citation markers detected")
    if looks_like_cs_ml(q):
        return RouteDecision("cs_ml", "cs/ml markers detected")

    return RouteDecision("general", "default")
