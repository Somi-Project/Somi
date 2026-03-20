from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REQUIRED_DOC_FILES = (
    "docs/architecture/CONTRIBUTOR_MAP.md",
    "docs/architecture/NEWCOMER_CHECKLIST.md",
    "agent_methods/README.md",
    "execution_backends/README.md",
    "gateway/README.md",
    "ops/README.md",
    "search/README.md",
    "somicontroller_parts/README.md",
    "state/README.md",
    "tests/README.md",
    "workflow_runtime/README.md",
    "workshop/toolbox/agent_core/README.md",
    "workshop/toolbox/browser/README.md",
    "workshop/toolbox/coding/README.md",
    "workshop/toolbox/research_supermode/README.md",
    "workshop/toolbox/stacks/README.md",
    "workshop/toolbox/stacks/web_core/README.md",
    "workshop/toolbox/stacks/research_core/README.md",
)

CORE_LINK_HOSTS = (
    "docs/architecture/README.md",
    "README.md",
    "workshop/README.md",
    "gui/README.md",
    "runtime/README.md",
)

LINK_SCAN_FILES = REQUIRED_DOC_FILES + (
    "docs/architecture/README.md",
    "workshop/README.md",
    "workshop/toolbox/README.md",
    "gui/README.md",
    "runtime/README.md",
)

_ABS_LINK_PATTERN = re.compile(r"\[[^\]]+\]\((/C:/somex/[^)]+)\)")


def _file_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return {
        "path": str(path),
        "line_count": len(text.strip().splitlines()),
        "text": text,
    }


def run_docs_integrity(root_dir: str | Path = ".") -> dict[str, Any]:
    root = Path(root_dir).resolve()

    missing_files: list[str] = []
    short_files: list[str] = []
    core_link_gaps: list[str] = []
    broken_links: list[dict[str, str]] = []

    for relative in REQUIRED_DOC_FILES:
        path = root / relative
        if not path.exists():
            missing_files.append(relative)
            continue
        summary = _file_summary(path)
        if int(summary["line_count"]) < 8:
            short_files.append(relative)

    for relative in CORE_LINK_HOSTS:
        path = root / relative
        if not path.exists():
            core_link_gaps.append(relative)
            continue
        text = path.read_text(encoding="utf-8")
        if "CONTRIBUTOR_MAP" not in text:
            core_link_gaps.append(relative)

    for relative in LINK_SCAN_FILES:
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for target in _ABS_LINK_PATTERN.findall(text):
            target_path = Path(target.replace("/C:/", "C:/"))
            if not target_path.exists():
                broken_links.append({"source": relative, "target": target})

    ok = not missing_files and not short_files and not core_link_gaps and not broken_links
    return {
        "ok": ok,
        "root_dir": str(root),
        "required_files": list(REQUIRED_DOC_FILES),
        "missing_files": missing_files,
        "short_files": short_files,
        "core_link_gaps": core_link_gaps,
        "broken_links": broken_links,
    }


def format_docs_integrity(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "[Somi Docs Integrity]",
            f"- ok: {bool(report.get('ok', False))}",
            f"- missing_files: {len(list(report.get('missing_files') or []))}",
            f"- short_files: {len(list(report.get('short_files') or []))}",
            f"- core_link_gaps: {len(list(report.get('core_link_gaps') or []))}",
            f"- broken_links: {len(list(report.get('broken_links') or []))}",
        ]
    )
