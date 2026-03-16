from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from workshop.toolbox.stacks.ocr_core.schema import schema_field_names, schema_required_fields


DATE_RE = re.compile(r"\b\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b")
PHONE_RE = re.compile(r"\+?[0-9][0-9\-\s]{6,}")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def unk_ratio(text: str) -> float:
    if not text:
        return 1.0
    tokens = text.split()
    if not tokens:
        return 1.0
    return sum(1 for t in tokens if t.strip().upper() == "[UNK]") / len(tokens)


def score_general(raw_text: str, metrics: Dict[str, Any]) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    score = 1.0
    if not raw_text.strip():
        score -= 0.7
        reasons.append("empty_text")
    u = unk_ratio(raw_text)
    if u > 0.05:
        score -= min(0.5, u)
        reasons.append("high_unk")
    if metrics.get("blur_score", 1.0) < 0.2:
        score -= 0.15
        reasons.append("blurry")
    if len(raw_text.strip()) < 20:
        score -= 0.2
        reasons.append("very_short")
    return max(0.0, min(1.0, score)), reasons


def score_structured(records: list[dict], schema: dict, raw_text: str, metrics: dict) -> Tuple[float, float, Dict[str, int], float, List[str]]:
    parse_failures: Dict[str, int] = {"date": 0, "number": 0, "phone": 0}
    reasons: List[str] = []
    fields = schema_field_names(schema)
    required = schema_required_fields(schema)
    target = required or fields

    filled = 0
    for r in records or []:
        for f in target:
            val = str(r.get(f, "")).strip()
            if val and val != "[UNK]":
                filled += 1
        for v in r.values():
            s = str(v).strip()
            if s == "[UNK]" or not s:
                continue
            if any(x in s.lower() for x in ["date", "dob"]):
                if not DATE_RE.search(s):
                    parse_failures["date"] += 1
            if s.replace(".", "", 1).isdigit() and not NUM_RE.match(s):
                parse_failures["number"] += 1
            if "phone" in s.lower() and not PHONE_RE.search(s):
                parse_failures["phone"] += 1

    denom = max(1, len(target) * max(1, len(records or [1])))
    coverage = filled / denom
    u = unk_ratio(raw_text)
    score = max(0.0, min(1.0, coverage * 0.75 + (1 - u) * 0.25 - 0.02 * sum(parse_failures.values())))
    if coverage < 0.7:
        reasons.append("low_coverage")
    if u > 0.05:
        reasons.append("high_unk")
    if sum(parse_failures.values()) > 0:
        reasons.append("parse_failures")
    if metrics.get("blur_score", 1.0) < 0.2:
        reasons.append("blurry")
    return coverage, u, parse_failures, score, reasons


def field_fill_rates(records: list[dict], schema: dict) -> Dict[str, float]:
    fields = schema_field_names(schema)
    if not fields:
        return {}
    total_records = max(1, len(records or []))
    coverage: Dict[str, float] = {}
    for field in fields:
        hits = 0
        for row in records or []:
            value = str(dict(row).get(field) or "").strip()
            if value and value != "[UNK]":
                hits += 1
        coverage[field] = round(hits / total_records, 4)
    return coverage


def field_confidence_map(records: list[dict], schema: dict, parse_failures: Dict[str, int], raw_text: str) -> Dict[str, float]:
    fill_rates = field_fill_rates(records, schema)
    penalty = min(0.35, 0.05 * sum(int(value or 0) for value in dict(parse_failures or {}).values()))
    unk_penalty = min(0.4, unk_ratio(raw_text) * 0.5)
    out: Dict[str, float] = {}
    for field, fill_rate in fill_rates.items():
        out[field] = round(max(0.05, min(0.99, float(fill_rate) * 0.9 + 0.1 - penalty - unk_penalty)), 4)
    return out


def table_shapes(records: list[dict], schema: dict) -> List[Dict[str, Any]]:
    fields = schema_field_names(schema)
    if not records:
        return []
    filled_columns = len([field for field in fields if any(str(dict(row).get(field) or "").strip() not in {"", "[UNK]"} for row in records)])
    return [{"rows": len(records), "columns": filled_columns, "schema_fields": len(fields)}]


def escalation_metadata(
    *,
    reasons: List[str],
    coverage: float,
    field_coverage: Dict[str, float],
) -> Tuple[str, bool, str]:
    required_review = bool(reasons)
    if not required_review:
        return "none", False, ""
    level = "warning"
    if coverage < 0.45 or any(float(value or 0.0) < 0.5 for value in field_coverage.values()):
        level = "critical"
    message = "Manual review recommended because: " + ", ".join(reasons[:4])
    return level, True, message


def should_escalate_structured(coverage: float, unk: float, parse_failures: Dict[str, int], metrics: Dict[str, Any], thresholds: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons = []
    if coverage < thresholds.get("min_coverage", 0.70):
        reasons.append("coverage_below_threshold")
    if unk > thresholds.get("max_unk_ratio", 0.05):
        reasons.append("unk_above_threshold")
    if sum(parse_failures.values()) > thresholds.get("max_parse_failures", 0):
        reasons.append("parse_failure_threshold")
    if metrics.get("blur_score", 1.0) < 0.15:
        reasons.append("image_quality_low")
    return bool(reasons), reasons


def should_escalate_general(score: float, unk: float, metrics: Dict[str, Any], thresholds: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons = []
    if score < thresholds.get("min_score", 0.65):
        reasons.append("score_below_threshold")
    if unk > thresholds.get("max_unk_ratio", 0.05):
        reasons.append("unk_above_threshold")
    if metrics.get("blur_score", 1.0) < 0.15:
        reasons.append("image_quality_low")
    return bool(reasons), reasons

