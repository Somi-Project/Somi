from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SkillScanSeverity = str  # "info" | "warn" | "critical"


@dataclass(frozen=True)
class SkillScanFinding:
    rule_id: str
    severity: SkillScanSeverity
    file: str
    line: int
    message: str
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCANNABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".mjs",
    ".cjs",
    ".sh",
    ".ps1",
}

_DEFAULT_MAX_FILES = 500
_DEFAULT_MAX_FILE_BYTES = 1024 * 1024
_SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".venv", ".pytest_cache"}
_SEVERITY_ORDER: dict[str, int] = {"info": 1, "warn": 2, "critical": 3}


@dataclass(frozen=True)
class _LineRule:
    rule_id: str
    severity: SkillScanSeverity
    message: str
    pattern: re.Pattern[str]
    requires_context: re.Pattern[str] | None = None


@dataclass(frozen=True)
class _SourceRule:
    rule_id: str
    severity: SkillScanSeverity
    message: str
    pattern: re.Pattern[str]
    requires_context: re.Pattern[str] | None = None


_LINE_RULES: tuple[_LineRule, ...] = (
    _LineRule(
        rule_id="os-system-exec",
        severity="critical",
        message="Direct shell execution via os.system/os.popen detected",
        pattern=re.compile(r"\b(?:os\.system|os\.popen)\s*\("),
    ),
    _LineRule(
        rule_id="subprocess-shell",
        severity="critical",
        message="subprocess with shell=True detected",
        pattern=re.compile(
            r"\bsubprocess\.(?:run|Popen|call|check_call|check_output)\s*\(.*shell\s*=\s*True"
        ),
    ),
    _LineRule(
        rule_id="dynamic-code-exec",
        severity="critical",
        message="Dynamic code execution detected",
        pattern=re.compile(r"\b(?:eval|exec)\s*\("),
    ),
    _LineRule(
        rule_id="suspicious-network-send",
        severity="warn",
        message="Network send operation detected",
        pattern=re.compile(
            r"\b(?:requests\.(?:post|put|patch)|httpx\.(?:post|put|patch)|urllib\.request\.urlopen|websocket\.create_connection)\b"
        ),
    ),
)

_SOURCE_RULES: tuple[_SourceRule, ...] = (
    _SourceRule(
        rule_id="env-harvesting",
        severity="critical",
        message="Environment-variable access combined with network send detected",
        pattern=re.compile(r"\b(?:os\.environ|os\.getenv|process\.env)\b"),
        requires_context=re.compile(
            r"\b(?:requests\.(?:post|put|patch)|httpx\.(?:post|put|patch)|urllib\.request\.urlopen|websocket\.create_connection)\b"
        ),
    ),
    _SourceRule(
        rule_id="possible-exfiltration",
        severity="warn",
        message="File read + network send pattern detected",
        pattern=re.compile(
            r"\b(?:open\([^)]*\)\.read|Path\([^)]*\)\.(?:read_text|read_bytes)|read_text\(|read_bytes\()\b"
        ),
        requires_context=re.compile(
            r"\b(?:requests\.(?:post|put|patch)|httpx\.(?:post|put|patch)|urllib\.request\.urlopen|websocket\.create_connection)\b"
        ),
    ),
    _SourceRule(
        rule_id="obfuscated-code",
        severity="warn",
        message="Large encoded payload with decode primitive detected",
        pattern=re.compile(
            r"(?:base64\.b64decode|Buffer\.from|atob)\s*\(\s*['\"][A-Za-z0-9+/=]{200,}['\"]"
        ),
    ),
)


def _truncate(text: str, max_len: int = 140) -> str:
    t = str(text or "").strip()
    return t if len(t) <= max_len else f"{t[:max_len]}..."


def is_scannable(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in _SCANNABLE_EXTENSIONS


def scan_source(source: str, file_path: str) -> list[SkillScanFinding]:
    findings: list[SkillScanFinding] = []
    lines = source.splitlines()
    matched_line_rules: set[str] = set()

    for rule in _LINE_RULES:
        if rule.rule_id in matched_line_rules:
            continue
        if rule.requires_context and not rule.requires_context.search(source):
            continue
        for idx, line in enumerate(lines, start=1):
            if not rule.pattern.search(line):
                continue
            findings.append(
                SkillScanFinding(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    file=file_path,
                    line=idx,
                    message=rule.message,
                    evidence=_truncate(line),
                )
            )
            matched_line_rules.add(rule.rule_id)
            break

    matched_source_rules: set[str] = set()
    for rule in _SOURCE_RULES:
        if rule.rule_id in matched_source_rules:
            continue
        if not rule.pattern.search(source):
            continue
        if rule.requires_context and not rule.requires_context.search(source):
            continue
        line_no = 1
        evidence = ""
        for idx, line in enumerate(lines, start=1):
            if rule.pattern.search(line):
                line_no = idx
                evidence = line
                break
        findings.append(
            SkillScanFinding(
                rule_id=rule.rule_id,
                severity=rule.severity,
                file=file_path,
                line=line_no,
                message=rule.message,
                evidence=_truncate(evidence or source[:120]),
            )
        )
        matched_source_rules.add(rule.rule_id)

    return findings


def _walk_scannable_files(root: Path, *, max_files: int) -> list[Path]:
    out: list[Path] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            p = Path(base) / fn
            if not is_scannable(str(p)):
                continue
            out.append(p)
            if len(out) >= max_files:
                return out
    return out


def _severity_counts(findings: Iterable[SkillScanFinding]) -> dict[str, int]:
    counts = {"critical": 0, "warn": 0, "info": 0}
    for f in findings:
        key = str(f.severity or "info").lower()
        if key in counts:
            counts[key] += 1
    return counts


def should_block(findings: Iterable[SkillScanFinding | dict[str, Any]], block_on: str) -> bool:
    threshold = str(block_on or "").strip().lower()
    if threshold in {"", "off", "none", "disabled"}:
        return False
    if threshold not in _SEVERITY_ORDER:
        threshold = "critical"
    required = _SEVERITY_ORDER[threshold]
    for f in findings:
        sev = f.get("severity") if isinstance(f, dict) else getattr(f, "severity", "info")
        level = _SEVERITY_ORDER.get(str(sev or "info").lower(), 0)
        if level >= required:
            return True
    return False


def scan_directory_with_summary(
    root_dir: str | Path,
    *,
    max_files: int = _DEFAULT_MAX_FILES,
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    root = Path(root_dir)
    files = _walk_scannable_files(root, max_files=max(1, int(max_files)))
    findings: list[SkillScanFinding] = []
    scanned_files = 0

    for file_path in files:
        try:
            st = file_path.stat()
        except FileNotFoundError:
            continue
        if not file_path.is_file() or st.st_size > int(max_file_bytes):
            continue
        try:
            src = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned_files += 1
        findings.extend(scan_source(src, str(file_path)))

    counts = _severity_counts(findings)
    return {
        "scanned_files": scanned_files,
        "critical": counts["critical"],
        "warn": counts["warn"],
        "info": counts["info"],
        "findings": [f.as_dict() for f in findings],
    }
