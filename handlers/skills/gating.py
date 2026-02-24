from __future__ import annotations

import shutil
from typing import Any

from .types import SkillDoc


def get_by_dotpath(payload: dict[str, Any], dotpath: str) -> Any:
    cur: Any = payload
    for part in str(dotpath or "").split("."):
        if not part:
            continue
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur.get(part)
    return cur


def _merged_env(skill: SkillDoc, env: dict[str, str], entries: dict[str, dict]) -> dict[str, str]:
    merged = dict(env or {})
    override = entries.get(skill.skill_key, {}) if isinstance(entries, dict) else {}
    for k, v in (override.get("env") or {}).items():
        if k not in merged and v is not None:
            merged[str(k)] = str(v)
    primary_env = str(skill.openclaw.get("primaryEnv") or "").strip()
    api_key = override.get("apiKey")
    if primary_env and api_key and primary_env not in merged:
        merged[primary_env] = str(api_key)
    return merged


def check_eligibility(skill: SkillDoc, cfg: dict, env: dict, platform: str) -> tuple[bool, list[str]]:
    oc = skill.openclaw if isinstance(skill.openclaw, dict) else {}
    reasons: list[str] = []
    entries = cfg.get("SKILLS_ENTRIES", {}) if isinstance(cfg, dict) else {}
    env_view = _merged_env(skill, env or {}, entries)

    if oc.get("always") is True:
        return True, reasons

    os_req = oc.get("os")
    if os_req:
        wants = os_req if isinstance(os_req, list) else [os_req]
        wants = [str(x).lower() for x in wants]
        if str(platform).lower() not in wants:
            reasons.append(f"OS mismatch: requires {', '.join(wants)}, current {platform}")

    requires = oc.get("requires", {}) if isinstance(oc.get("requires"), dict) else {}
    bins = requires.get("bins") if isinstance(requires.get("bins"), list) else []
    any_bins = requires.get("anyBins") if isinstance(requires.get("anyBins"), list) else []
    req_env = requires.get("env") if isinstance(requires.get("env"), list) else []
    req_cfg = requires.get("config") if isinstance(requires.get("config"), list) else []

    for bin_name in bins:
        if not shutil.which(str(bin_name)):
            reasons.append(f"Missing required binary: {bin_name}")

    if any_bins and not any(shutil.which(str(bin_name)) for bin_name in any_bins):
        reasons.append(f"Missing any-of binaries: {', '.join(map(str, any_bins))}")

    for key in req_env:
        if not env_view.get(str(key)):
            reasons.append(f"Missing required env var: {key}")

    for dotpath in req_cfg:
        if not get_by_dotpath(cfg, str(dotpath)):
            reasons.append(f"Missing/false required config: {dotpath}")

    return len(reasons) == 0, reasons
