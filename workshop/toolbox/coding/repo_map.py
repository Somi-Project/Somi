from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_IGNORE_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".venv", "node_modules", ".next", "dist", "build"}
_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".scss",
    ".ps1",
    ".sh",
}
_PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\. ,]+))", re.MULTILINE)
_JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))""")
_PY_SYMBOL_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+function|function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\(|function)",
    re.MULTILINE,
)
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_ENTRYPOINT_HINTS = {
    "main.py",
    "app.py",
    "index.js",
    "index.ts",
    "server.js",
    "server.ts",
    "src/index.ts",
    "src/index.js",
    "index.html",
}
_CONFIG_HINTS = {"pyproject.toml", "requirements.txt", "package.json", "tsconfig.json", "setup.py"}


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(str(text or "").lower()) if len(token) > 2}


def _classify_file(rel_path: str) -> str:
    rel = str(rel_path or "").replace("\\", "/").lower()
    name = rel.rsplit("/", 1)[-1]
    if "/tests/" in f"/{rel}/" or name.startswith("test_") or name.endswith(".spec.ts") or name.endswith(".spec.js"):
        return "test"
    if name in _CONFIG_HINTS or name.endswith((".json", ".toml", ".yaml", ".yml")):
        return "config"
    if name.endswith(".md"):
        return "doc"
    if name.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss")):
        return "source"
    return "asset"


def _file_token_blob(rel_path: str, preview: str) -> set[str]:
    return _tokenize(rel_path) | _tokenize(preview)


def _safe_text(path: Path, *, max_chars: int = 4000) -> str:
    if path.suffix.lower() not in _TEXT_EXTENSIONS:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


def _parse_imports(path: Path, content: str) -> list[str]:
    imports: list[str] = []
    if path.suffix.lower() == ".py":
        for left, right in _PY_IMPORT_RE.findall(content):
            if left:
                imports.append(left.strip())
            if right:
                imports.extend(part.strip() for part in right.split(",") if part.strip())
    elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        for left, right in _JS_IMPORT_RE.findall(content):
            target = left or right
            if target:
                imports.append(target.strip())
    return list(dict.fromkeys(imports))


def _extract_symbols(path: Path, content: str) -> list[str]:
    rows: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".py":
        rows.extend(match.group(1) for match in _PY_SYMBOL_RE.finditer(content) if match.group(1))
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for match in _JS_SYMBOL_RE.finditer(content):
            symbol = match.group(1) or match.group(2)
            if symbol:
                rows.append(symbol)
    return list(dict.fromkeys([str(item).strip() for item in rows if str(item).strip()]))[:12]


def _dependency_kind(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if text.startswith("."):
        return "local"
    if "/" in text and not text.startswith("@"):
        return "local"
    return "external"


def _load_manifest_entrypoint(root_path: Path) -> str:
    manifest_path = root_path / ".somi_coding_workspace.json"
    if not manifest_path.exists():
        return ""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(dict(payload or {}).get("entrypoint") or "").strip()


def _local_module_names(rel_path: str) -> set[str]:
    rel = str(rel_path or "").replace("\\", "/")
    path = Path(rel)
    if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return set()
    names = {path.with_suffix("").as_posix().replace("/", ".")}
    if path.name == "__init__.py":
        parent = path.parent.as_posix().replace("/", ".").strip(".")
        if parent:
            names.add(parent)
    return {name.strip(".") for name in names if name.strip(".")}


def _is_local_dependency(dep: str, local_modules: set[str]) -> bool:
    text = str(dep or "").strip()
    if not text:
        return False
    if _dependency_kind(text) == "local":
        return True
    if text in local_modules:
        return True
    return any(text.startswith(f"{name}.") or name.startswith(f"{text}.") for name in local_modules)


def build_repo_map(root_path: Path, *, objective: str = "", limit: int = 120) -> dict[str, Any]:
    root = Path(root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Workspace root does not exist: {root}")

    objective_tokens = _tokenize(objective)
    manifest_entrypoint = _load_manifest_entrypoint(root)
    files: list[dict[str, Any]] = []
    external_dependencies: dict[str, int] = {}
    local_dependencies: dict[str, int] = {}
    entrypoints: list[str] = []
    source_count = 0
    test_count = 0
    config_count = 0
    doc_count = 0
    local_modules: set[str] = set()
    pending_imports: list[list[str]] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".somi_coding_workspace.json":
            continue
        if any(part in _IGNORE_PARTS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        kind = _classify_file(rel)
        if kind == "source":
            source_count += 1
        elif kind == "test":
            test_count += 1
        elif kind == "config":
            config_count += 1
        elif kind == "doc":
            doc_count += 1

        preview = _safe_text(path)
        imports = _parse_imports(path, preview)
        symbols = _extract_symbols(path, preview)
        local_modules.update(_local_module_names(rel))

        tokens = _file_token_blob(rel, preview[:1000])
        focus_hits = len(objective_tokens & tokens)
        if rel.lower() == manifest_entrypoint.lower() or rel.lower() in _ENTRYPOINT_HINTS:
            entrypoints.append(rel)
            focus_hits += 2
        elif path.name.lower() in {item.rsplit("/", 1)[-1] for item in _ENTRYPOINT_HINTS}:
            entrypoints.append(rel)

        files.append(
            {
                "path": rel,
                "kind": kind,
                "size": int(path.stat().st_size),
                "imports": imports[:12],
                "symbols": symbols,
                "symbol_count": len(symbols),
                "focus_score": int(focus_hits),
            }
        )
        pending_imports.append(imports[:12])

    for imports in pending_imports:
        for dep in imports:
            if _is_local_dependency(dep, local_modules):
                local_dependencies[dep] = int(local_dependencies.get(dep, 0) or 0) + 1
            else:
                external_dependencies[dep] = int(external_dependencies.get(dep, 0) or 0) + 1

    files.sort(key=lambda row: (-int(row.get("focus_score", 0)), row.get("kind") != "source", str(row.get("path") or "")))
    focus_files = [row["path"] for row in files if int(row.get("focus_score", 0)) > 0][:8]
    if not focus_files:
        focus_files = [row["path"] for row in files if str(row.get("kind") or "") in {"source", "test"}][:8]

    hotspot_files = sorted(files, key=lambda row: (-len(list(row.get("imports") or [])), -int(row.get("size", 0))))[:8]
    focus_symbol_rows = [
        {"path": str(row.get("path") or ""), "symbols": list(row.get("symbols") or [])[:8]}
        for row in files
        if int(row.get("focus_score", 0)) > 0 and list(row.get("symbols") or [])
    ][:8]
    if not focus_symbol_rows:
        focus_symbol_rows = [
            {"path": str(row.get("path") or ""), "symbols": list(row.get("symbols") or [])[:8]}
            for row in files
            if str(row.get("kind") or "") == "source" and list(row.get("symbols") or [])
        ][:8]
    summary_bits = [
        f"files={len(files)}",
        f"source={source_count}",
        f"tests={test_count}",
        f"config={config_count}",
    ]
    if focus_files:
        summary_bits.append(f"focus={', '.join(focus_files[:3])}")
    if entrypoints:
        summary_bits.append(f"entry={entrypoints[0]}")

    return {
        "workspace_root": str(root),
        "objective": str(objective or ""),
        "summary": " | ".join(summary_bits),
        "file_count": len(files),
        "source_file_count": int(source_count),
        "test_file_count": int(test_count),
        "config_file_count": int(config_count),
        "doc_file_count": int(doc_count),
        "entrypoints": list(dict.fromkeys(entrypoints))[:6],
        "focus_files": focus_files,
        "focus_symbols": focus_symbol_rows,
        "hotspot_files": hotspot_files,
        "external_dependencies": [
            {"name": name, "count": count}
            for name, count in sorted(external_dependencies.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
        "local_dependencies": [
            {"name": name, "count": count}
            for name, count in sorted(local_dependencies.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
        "files": files[: max(10, min(int(limit or 120), 200))],
    }


def build_project_context_memory(
    *,
    repo_map: dict[str, Any] | None,
    health: dict[str, Any] | None = None,
    active_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = dict(repo_map or {})
    health_payload = dict(health or {})
    job = dict(active_job or {})

    lines: list[str] = []
    if repo.get("summary"):
        lines.append(f"Repo map: {repo['summary']}")
    focus_files = [str(item) for item in list(repo.get("focus_files") or []) if str(item).strip()]
    if focus_files:
        lines.append("Focus files: " + ", ".join(focus_files[:5]))
    focus_symbols = [dict(item) for item in list(repo.get("focus_symbols") or []) if isinstance(item, dict)]
    if focus_symbols:
        labels: list[str] = []
        for row in focus_symbols[:3]:
            symbol_rows = [str(item).strip() for item in list(row.get("symbols") or []) if str(item).strip()]
            if symbol_rows:
                labels.append(f"{row.get('path')}: {', '.join(symbol_rows[:3])}")
        if labels:
            lines.append("Key symbols: " + " | ".join(labels))
    if health_payload.get("summary"):
        lines.append(f"Workspace health: {health_payload['summary']}")
    if job.get("scorecard"):
        scorecard = dict(job.get("scorecard") or {})
        lines.append(
            "Job loop: "
            f"status={job.get('status') or 'active'} "
            f"score={scorecard.get('finality_score') or 0} "
            f"steps={scorecard.get('successful_steps') or 0}/{scorecard.get('total_steps') or 0}"
        )
    return {
        "summary": " | ".join(lines[:3]),
        "lines": lines[:6],
        "focus_files": focus_files[:8],
        "focus_symbols": focus_symbols[:6],
    }
