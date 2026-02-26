from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from handlers.toolbox_handler import dispatch_or_run
from config import toolboxsettings as tbs
from config import assistantsettings as aset
from runtime.risk import assess
from runtime.ticketing import ExecutionTicket, ticket_hash
from runtime.user_state import load_user_state, save_user_state

from .registry import build_registry_snapshot, settings_dict
from .types import SkillDoc

UNSAFE_VERBS = {"install", "delete", "remove", "--delete", "--force", "--create", "add", "complete"}
RECENT_SKILL_RUNS_PATH = Path("runtime/cache/skills_recent.json")
MAX_RECENT_SKILL_RUNS = 30
_RECENT_RUNS_LOCK = threading.Lock()


@dataclass
class SkillDispatchResult:
    handled: bool
    response: str = ""
    forced_skill_keys: list[str] | None = None


def _resolve_skill(name: str, eligible: dict[str, SkillDoc], ineligible: dict[str, tuple[SkillDoc, list[str]]]) -> tuple[SkillDoc | None, list[str]]:
    needle = (name or "").strip().lower()
    if not needle:
        return None, []
    pool = {**eligible, **{k: v[0] for k, v in ineligible.items()}}

    direct = next((k for k in pool.keys() if k.lower() == needle), None)
    if direct:
        return pool[direct], [direct]

    matches = [k for k, d in pool.items() if needle == d.name.lower()]
    if len(matches) == 1:
        return pool[matches[0]], matches
    if len(matches) > 1:
        return None, matches
    return None, []


def _is_unsafe(raw_args: str) -> bool:
    tokens = set((raw_args or "").lower().replace("=", " ").split())
    return any(v in tokens for v in UNSAFE_VERBS)


def _format_list(snapshot: dict[str, Any], include_all: bool, debug: bool) -> str:
    lines = ["Skills:"]
    for item in snapshot.get("eligible", []):
        emoji = item.get("emoji")
        prefix = f"{emoji} " if emoji else ""
        lines.append(f"- {prefix}{item['key']}: {item['desc']}")
        if debug and item.get("parse_warnings"):
            lines.append(f"  warnings: {'; '.join(item['parse_warnings'])}")
    if include_all:
        for item in snapshot.get("ineligible", []):
            lines.append(f"- {item['key']}: INELIGIBLE ({'; '.join(item.get('reasons', []))})")
            if debug and item.get("parse_warnings"):
                lines.append(f"  warnings: {'; '.join(item['parse_warnings'])}")
    if debug:
        for rej in snapshot.get("rejected", []):
            lines.append(f"- REJECTED {rej.get('path')}: {rej.get('reason')}")
    return "\n".join(lines)


def _skill_info(skill: SkillDoc, eligible: bool, reasons: list[str] | None = None) -> str:
    requires = skill.openclaw.get("requires", {}) if isinstance(skill.openclaw, dict) else {}
    install_hints = skill.openclaw.get("install") if isinstance(skill.openclaw, dict) else None
    lines = [
        f"Skill: {skill.name} ({skill.skill_key})",
        f"Description: {skill.description}",
        f"Eligible: {'yes' if eligible else 'no'}",
    ]
    if reasons:
        lines.append(f"Reasons: {'; '.join(reasons)}")
    if skill.homepage:
        lines.append(f"Homepage: {skill.homepage}")
    if requires:
        lines.append(f"Requirements: {requires}")
    if install_hints:
        lines.append(f"Install hints (not auto-run): {install_hints}")
    lines.append(f"Dispatch: dispatch={skill.command_dispatch} tool={skill.command_tool} mode={skill.command_arg_mode}")
    return "\n".join(lines)


def _pick_bin(skill: SkillDoc) -> str:
    requires = skill.openclaw.get("requires", {}) if isinstance(skill.openclaw, dict) else {}
    bins = list(requires.get("bins") or [])
    any_bins = list(requires.get("anyBins") or [])

    if bins:
        return str(bins[0])
    for bin_name in any_bins:
        if shutil.which(str(bin_name)):
            return str(bin_name)
    return str(any_bins[0]) if any_bins else ""


def _minimal_skill_env(skill: SkillDoc, cfg: dict, env: dict) -> dict[str, str]:
    safe_env = {
        "PATH": env.get("PATH", ""),
        "HOME": env.get("HOME", ""),
    }
    entry = (cfg.get("SKILLS_ENTRIES") or {}).get(skill.skill_key, {})
    for k, v in (entry.get("env") or {}).items():
        safe_env.setdefault(str(k), str(v))

    primary_env = str(skill.openclaw.get("primaryEnv") or "").strip()
    api_key = entry.get("apiKey")
    if primary_env and api_key and primary_env not in safe_env:
        safe_env[primary_env] = str(api_key)

    return safe_env


def _allowed_bins_for_skill(skill: SkillDoc, cfg: dict) -> list[str]:
    entry = (cfg.get("SKILLS_ENTRIES") or {}).get(skill.skill_key, {})
    allowed = entry.get("allowedBins")
    if isinstance(allowed, list) and allowed:
        return [str(x) for x in allowed]
    return [str(x) for x in (cfg.get("SKILLS_CLI_EXEC_SAFE_ALLOWLIST", []) or [])]


def _load_recent_runs_unlocked() -> list[dict[str, Any]]:
    if not RECENT_SKILL_RUNS_PATH.exists():
        return []
    try:
        data = json.loads(RECENT_SKILL_RUNS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def _save_recent_runs_unlocked(items: list[dict[str, Any]]) -> None:
    RECENT_SKILL_RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECENT_SKILL_RUNS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items[-MAX_RECENT_SKILL_RUNS:], indent=2) + "\n", encoding="utf-8")
    tmp.replace(RECENT_SKILL_RUNS_PATH)


def _load_recent_runs() -> list[dict[str, Any]]:
    with _RECENT_RUNS_LOCK:
        return _load_recent_runs_unlocked()


def _save_recent_runs(items: list[dict[str, Any]]) -> None:
    with _RECENT_RUNS_LOCK:
        _save_recent_runs_unlocked(items)


def _record_recent_run(skill: SkillDoc, raw_args: str, status: str, summary: str, confirmed: bool) -> None:
    with _RECENT_RUNS_LOCK:
        runs = _load_recent_runs_unlocked()
        runs.append(
            {
                "ts": int(time.time()),
                "skill_key": skill.skill_key,
                "skill_name": skill.name,
                "args": raw_args,
                "status": status,
                "summary": summary,
                "confirmed": bool(confirmed),
            }
        )
        _save_recent_runs_unlocked(runs)

def _format_recent_runs(limit: int = 10) -> str:
    runs = _load_recent_runs()
    if not runs:
        return "No recent /skill runs yet."
    lines = ["Recent skill runs:"]
    for item in runs[-limit:][::-1]:
        lines.append(_render_run(item))
    return "\n".join(lines)


def _summarize_result(result: Any) -> str:
    if isinstance(result, dict):
        if "ok" in result:
            return f"ok={result.get('ok')} exit_code={result.get('exit_code')}"
        return f"result_keys={','.join(sorted(result.keys())[:6])}"
    return str(result)[:160]


def _run_cli_skill(skill: SkillDoc, raw_args: str, cfg: dict, env: dict) -> dict[str, Any]:
    chosen = _pick_bin(skill)
    argv = shlex.split(raw_args or "", posix=(os.name != "nt"))

    return dispatch_or_run(
        "cli.exec",
        {
            "skill_key": skill.skill_key,
            "bin": chosen,
            "argv": argv,
            "env": _minimal_skill_env(skill=skill, cfg=cfg, env=env),
            "allowed_bins": _allowed_bins_for_skill(skill=skill, cfg=cfg),
            "pty": False,
        },
    )


def _build_skill_ticket(skill: SkillDoc, raw_args: str, user_id: str) -> ExecutionTicket:
    argv = shlex.split(raw_args or "", posix=(os.name != "nt"))
    cmds = [["skill.run", skill.skill_key, *argv]]
    low = " ".join(argv).lower()
    return ExecutionTicket(
        job_id=f"skill-{user_id}-{skill.skill_key}",
        action="skill_run",
        commands=cmds,
        cwd=".",
        allow_network=("http://" in low or "https://" in low or "curl" in low or "wget" in low),
        allow_delete=("delete" in low or "remove" in low or "--delete" in low),
        allow_system_wide=("system" in low and "wide" in low),
    )




def _bounded_pending_approvals(items: list[str]) -> list[str]:
    cap = max(1, int(getattr(aset, "MAX_UNRESOLVED_LOOPS", 20)))
    # keep newest approvals by insertion order
    return items[-cap:]

def _govern_skill_run(skill: SkillDoc, raw_args: str, confirm: bool, user_id: str) -> tuple[bool, str, str]:
    ticket = _build_skill_ticket(skill, raw_args, user_id)
    th = ticket_hash(ticket)
    state = load_user_state(user_id)
    report = assess(ticket)

    if not confirm:
        if th not in state.pending_approvals:
            state.pending_approvals.append(th)
            state.pending_approvals = _bounded_pending_approvals(state.pending_approvals)
            save_user_state(state)
        return False, th, (
            f"Proposed skill run '{skill.skill_key}' (risk={report.tier}, ticket={th[:10]}...). "
            "Review and re-run with --confirm to execute."
        )

    if th not in state.pending_approvals:
        return False, th, "No pending approval found for this exact skill run. Re-run without --confirm first."

    if tbs.normalized_mode() == tbs.MODE_SAFE:
        return False, th, "SAFE mode blocks skill execution; request remains proposal-only."

    state.pending_approvals = [x for x in state.pending_approvals if x != th]
    state.pending_approvals = _bounded_pending_approvals(state.pending_approvals)
    save_user_state(state)
    return True, th, "approved"


def _run_skill(skill: SkillDoc, raw_args: str, cfg: dict, env: dict) -> SkillDispatchResult:
    if skill.command_dispatch == "tool" and skill.command_tool:
        override = ((cfg.get("SKILLS_ENTRIES") or {}).get(skill.skill_key, {}) or {}).get("commandToolOverride")
        target = override or skill.command_tool
        payload: dict[str, Any]
        if skill.command_arg_mode == "raw":
            payload = {
                "command": raw_args,
                "commandName": skill.skill_key,
                "skillName": skill.name,
                "baseDir": skill.base_dir,
            }
        else:
            payload = {"argv": shlex.split(raw_args or "", posix=(os.name != "nt"))}
        result = dispatch_or_run(target, payload)
        recap = _summarize_result(result)
        return SkillDispatchResult(
            handled=True,
            response=f"Tool output: {result}\n\nRecap: Ran '{skill.skill_key}' with args '{raw_args}'. Result {recap}.",
        )

    requires = skill.openclaw.get("requires", {}) if isinstance(skill.openclaw, dict) else {}
    if (requires.get("bins") or requires.get("anyBins")):
        result = _run_cli_skill(skill, raw_args, cfg=cfg, env=env)
        recap = _summarize_result(result)
        return SkillDispatchResult(
            handled=True,
            response=f"Tool output: {result}\n\nRecap: Ran '{skill.skill_key}' with args '{raw_args}'. Result {recap}.",
        )

    if skill.disable_model_invocation:
        return SkillDispatchResult(
            handled=True,
            response=f"{skill.name} disables model invocation and has no dispatch target configured.",
        )

    return SkillDispatchResult(
        handled=True,
        response=(
            f"{skill.name} is a prompt-only skill. I'll apply its guidance on your next request."
        ),
        forced_skill_keys=[skill.skill_key],
    )


def _dry_run_warning(skill: SkillDoc, raw_args: str) -> str:
    return (
        "This looks state-changing, so I did NOT execute it yet (safe dry-run mode).\n"
        f"Planned skill: {skill.skill_key}\n"
        f"Planned args: {raw_args}\n"
        "If this is intentional, re-run with --confirm."
    )




def _redact_text(text: str) -> str:
    out = str(text or "")
    out = out.replace("\n", " ")
    out = out.replace("\r", " ")
    out = re.sub(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+", r"\1=[REDACTED]", out)
    out = re.sub(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b", "[redacted-key]", out)
    return out[:180]


def _render_run(item: dict[str, Any]) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(item.get("ts", 0))))
    args = _redact_text(item.get("args", ""))
    summary = _redact_text(item.get("summary", ""))
    return f"- [{stamp}] {item.get('skill_key')} args='{args}' status={item.get('status')} confirmed={item.get('confirmed')} :: {summary}"


def _format_last_run() -> str:
    runs = _load_recent_runs()
    if not runs:
        return "No recent /skill runs yet."
    return "Last skill run:\n" + _render_run(runs[-1])

def _normalize_nl_to_skill_command(text: str) -> str | None:
    t = (text or "").strip()
    tl = t.lower()
    if not t or tl.startswith("/"):
        return None

    if tl in {"list skills", "show skills", "skills list", "what skills do i have", "what skills are available"}:
        return "/skill list"
    if tl in {"recent skills", "skill recent", "show recent skills"}:
        return "/skill recent"
    if tl in {"last skill", "show last skill run", "last skill run"}:
        return "/skill last"

    if tl.startswith("skill info "):
        return "/skill info " + t[len("skill info "):].strip()
    if tl.startswith("show skill "):
        return "/skill info " + t[len("show skill "):].strip()

    # Natural language execution bridge: "run skill X ...", "use skill X ..."
    for prefix in ("run skill ", "use skill ", "execute skill "):
        if tl.startswith(prefix):
            rest = t[len(prefix):].strip()
            if not rest:
                return None
            confirm = " --confirm" if (" confirm" in tl or tl.endswith(" confirm")) else ""
            # split as: <name> [with|for|to|--] <args>
            parts = rest.split(maxsplit=1)
            skill_name = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            for sep in (" with ", " for ", " to ", " -- "):
                if sep in rest.lower():
                    idx = rest.lower().find(sep)
                    skill_name = rest[:idx].strip()
                    args = rest[idx + len(sep):].strip()
                    break
            if args:
                return f"/skill run {skill_name} -- {args}{confirm}"
            return f"/skill run {skill_name}{confirm}"

    return None


def handle_skill_command(message: str, env: dict | None = None) -> SkillDispatchResult:
    normalized = _normalize_nl_to_skill_command(message)
    if normalized:
        message = normalized
    if not message.strip().startswith("/"):
        return SkillDispatchResult(handled=False)

    cfg = settings_dict()
    if not cfg.get("SKILLS_ENABLED", True):
        return SkillDispatchResult(handled=False)

    env = env or dict(os.environ)
    user_id = str(env.get("SOMI_USER_ID", "default_user"))
    reg = build_registry_snapshot(cfg=cfg, env=env, force_refresh=True)
    eligible = reg["eligible"]
    ineligible = reg["ineligible"]
    snapshot = reg["snapshot"]

    text = message.strip()
    parts = text.split()

    if parts[0] == "/skill":
        if len(parts) == 1 or parts[1] == "list":
            include_all = "--all" in parts
            debug = "--debug" in parts
            return SkillDispatchResult(handled=True, response=_format_list(snapshot, include_all, debug))

        action = parts[1]
        if action == "recent":
            return SkillDispatchResult(handled=True, response=_format_recent_runs(limit=10))
        if action == "last":
            return SkillDispatchResult(handled=True, response=_format_last_run())

        if action in {"info", "show"}:
            if len(parts) < 3:
                return SkillDispatchResult(handled=True, response="Usage: /skill info <name>")
            skill, matches = _resolve_skill(parts[2], eligible, ineligible)
            if not skill and matches:
                return SkillDispatchResult(handled=True, response=f"Ambiguous skill. Matches: {', '.join(matches)}")
            if not skill:
                return SkillDispatchResult(handled=True, response="Skill not found")
            if action == "info":
                inel = next((r for _, (d, r) in ineligible.items() if d.skill_key == skill.skill_key), None)
                return SkillDispatchResult(handled=True, response=_skill_info(skill, skill.skill_key in eligible, inel))
            lines = skill.body_md.splitlines()
            return SkillDispatchResult(handled=True, response="\n".join(lines[:80]) or "(empty SKILL.md body)")

        if action == "run":
            if len(parts) < 3:
                return SkillDispatchResult(handled=True, response="Usage: /skill run <name> -- <args>")
            confirm = "--confirm" in parts
            stripped = re.sub(r"(?<!\S)--confirm(?!\S)", "", text).strip()
            stripped = re.sub(r"\s+", " ", stripped)
            after = stripped[len("/skill run ") :]
            if " -- " in after:
                target_name, raw_args = after.split(" -- ", 1)
            else:
                toks = after.split(maxsplit=1)
                target_name = toks[0]
                raw_args = toks[1] if len(toks) > 1 else ""

            skill, matches = _resolve_skill(target_name, eligible, ineligible)
            if not skill and matches:
                return SkillDispatchResult(handled=True, response=f"Ambiguous skill. Matches: {', '.join(matches)}")
            if not skill:
                return SkillDispatchResult(handled=True, response="Skill not found")
            if skill.skill_key in ineligible:
                return SkillDispatchResult(handled=True, response=f"Skill is ineligible: {'; '.join(ineligible[skill.skill_key][1])}")

            if _is_unsafe(raw_args):
                entry = (cfg.get("SKILLS_ENTRIES") or {}).get(skill.skill_key, {})
                if entry.get("allowActive") is False:
                    _record_recent_run(skill, raw_args, status="blocked", summary="Blocked by allowActive=false", confirmed=confirm)
                    return SkillDispatchResult(handled=True, response="This skill cannot perform active/state-changing actions (policy override).")

            allowed, th, msg = _govern_skill_run(skill, raw_args, confirm=confirm, user_id=user_id)
            if not allowed:
                _record_recent_run(skill, raw_args, status="dry_run" if not confirm else "blocked", summary=msg, confirmed=confirm)
                return SkillDispatchResult(handled=True, response=msg)

            try:
                result = _run_skill(skill=skill, raw_args=raw_args, cfg=cfg, env=env)
                _record_recent_run(skill, raw_args, status="ran", summary=f"ticket={th[:10]} completed", confirmed=confirm)
                return result
            except Exception as exc:
                _record_recent_run(skill, raw_args, status="error", summary=f"{type(exc).__name__}: {exc}", confirmed=confirm)
                return SkillDispatchResult(handled=True, response=f"Skill run failed: {type(exc).__name__}: {exc}")

    if parts[0].startswith("/") and len(parts[0]) > 1:
        alias = parts[0][1:]
        skill, _ = _resolve_skill(alias, eligible, ineligible)
        if skill and skill.user_invocable:
            args = text[len(parts[0]) :].strip()
            return handle_skill_command(f"/skill run {skill.skill_key} -- {args}", env=env)

    return SkillDispatchResult(handled=False)
