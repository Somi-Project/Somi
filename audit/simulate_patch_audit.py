from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _compile_check() -> dict:
    targets = [
        "agents.py",
        "config/settings.py",
        "config/skillssettings.py",
        "runtime/tool_loop_detection.py",
        "runtime/transcript_hygiene.py",
        "runtime/history_compaction.py",
        "workshop/skills/security_scanner.py",
        "workshop/skills/registry.py",
        "workshop/skills/dispatch.py",
        "workshop/skills/types.py",
    ]
    cmd = [sys.executable, "-m", "py_compile", *targets]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stderr": (proc.stderr or "").strip(),
        "targets": targets,
    }


def _skill_scanner_check() -> dict:
    from workshop.skills.security_scanner import scan_directory_with_summary, should_block

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "skill.py"
        p.write_text("import os\nos.system('echo risky')\n", encoding="utf-8")
        summary = scan_directory_with_summary(td)
        blocked = should_block(summary.get("findings", []), block_on="critical")

    return {
        "ok": bool(summary.get("critical", 0) >= 1 and blocked),
        "critical": int(summary.get("critical", 0)),
        "warn": int(summary.get("warn", 0)),
        "blocked": bool(blocked),
    }


def _loop_detection_check() -> dict:
    from runtime.tool_loop_detection import (
        ToolLoopConfig,
        detect_tool_loop,
        record_tool_call,
        record_tool_call_outcome,
    )

    cfg = ToolLoopConfig(
        enabled=True,
        history_size=20,
        warning_threshold=2,
        critical_threshold=3,
        global_circuit_breaker_threshold=4,
        detect_generic_repeat=True,
        detect_no_progress=True,
        detect_ping_pong=True,
    )
    history: list[dict] = []
    args = {"query": "same"}

    for _ in range(3):
        record_tool_call(history, tool_name="web.intelligence", args=args, cfg=cfg)
        record_tool_call_outcome(
            history,
            tool_name="web.intelligence",
            args=args,
            result={"formatted": "same", "results": [{"title": "x"}]},
            cfg=cfg,
        )

    pre = detect_tool_loop(history, tool_name="web.intelligence", args=args, cfg=cfg)
    return {
        "ok": bool(pre.stuck and pre.level == "critical"),
        "stuck": bool(pre.stuck),
        "level": pre.level,
        "detector": pre.detector,
        "count": int(pre.count),
    }


def _transcript_hygiene_check() -> dict:
    from runtime.transcript_hygiene import sanitize_history_messages

    raw = [
        {"role": "user", "content": "hello\x00 world"},
        {"role": "assistant", "content": "ok\x07 done"},
        {"role": "badrole", "content": "still kept"},
        {"role": "user", "content": "   "},
    ]
    cleaned = sanitize_history_messages(raw, max_messages=10, max_message_chars=200)
    bad_chars = any("\x00" in m["content"] or "\x07" in m["content"] for m in cleaned)
    normalized_role = any(m["role"] == "user" and m["content"] == "still kept" for m in cleaned)
    return {
        "ok": bool(not bad_chars and normalized_role and len(cleaned) == 3),
        "cleaned_len": len(cleaned),
        "bad_chars": bool(bad_chars),
        "normalized_role": bool(normalized_role),
    }


def _compaction_check() -> dict:
    from runtime.history_compaction import COMPACTION_PREFIX, build_compaction_summary

    msgs = [
        {"role": "user", "content": "I need a deployment checklist for service A"},
        {"role": "assistant", "content": "Sure. I listed preflight and rollback steps."},
        {"role": "user", "content": "Also include post-deploy smoke tests."},
        {"role": "assistant", "content": "Added API, DB, and UI smoke checks."},
    ]
    summary = build_compaction_summary(msgs, max_items=4, max_chars=500)
    return {
        "ok": bool(summary.startswith(COMPACTION_PREFIX) and "User asked:" in summary),
        "has_prefix": bool(summary.startswith(COMPACTION_PREFIX)),
        "length": len(summary),
    }


def _integration_hook_check() -> dict:
    txt = (ROOT / "agents.py").read_text(encoding="utf-8")
    required = [
        "from runtime.tool_loop_detection import",
        "from runtime.transcript_hygiene import sanitize_history_messages, sanitize_text",
        "from runtime.history_compaction import COMPACTION_PREFIX, build_compaction_summary",
        "def _history_for_prompt(",
        "def _compact_history_if_needed(",
        "_run_tool_with_loop_guard(",
        "tool_name=\"web.intelligence\"",
    ]
    missing = [r for r in required if r not in txt]
    return {
        "ok": len(missing) == 0,
        "missing": missing,
    }


def main() -> int:
    checks = {
        "compile": _compile_check(),
        "step1_skill_scanner": _skill_scanner_check(),
        "step2_loop_detection": _loop_detection_check(),
        "step3_transcript_hygiene": _transcript_hygiene_check(),
        "step4_history_compaction": _compaction_check(),
        "step5_integration_hooks": _integration_hook_check(),
    }

    overall_ok = all(v.get("ok") for v in checks.values())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    lines = []
    lines.append("# Simulated Patch Audit")
    lines.append("")
    lines.append(f"- Timestamp (UTC): {stamp}")
    lines.append(f"- Overall: {'PASS' if overall_ok else 'FAIL'}")
    lines.append("")
    for name, payload in checks.items():
        status = "PASS" if payload.get("ok") else "FAIL"
        lines.append(f"## {name} [{status}]")
        lines.append("```json")
        lines.append(json.dumps(payload, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")

    out_path = ROOT / "audit" / "patch_audit_report.md"
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print(json.dumps({"overall_ok": overall_ok, "report": str(out_path)}, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


