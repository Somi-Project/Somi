from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass(frozen=True)
class CodingLanguageProfile:
    key: str
    display_name: str
    runtime_profile: str
    entrypoint: str
    hints: tuple[str, ...] = ()
    suggested_commands: tuple[str, ...] = ()
    starter_files: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    runtime_requirement_groups: tuple[tuple[str, ...], ...] = ()
    required_markers: tuple[str, ...] = ()
    benchmark_pack_ids: tuple[str, ...] = ("core_repo_tasks",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": str(self.key),
            "display_name": str(self.display_name),
            "runtime_profile": str(self.runtime_profile),
            "entrypoint": str(self.entrypoint),
            "hints": list(self.hints),
            "suggested_commands": list(self.suggested_commands),
            "starter_files": list(self.starter_files),
            "capabilities": list(self.capabilities),
            "tags": list(self.tags),
            "runtime_requirement_groups": [list(group) for group in self.runtime_requirement_groups],
            "required_markers": list(self.required_markers),
            "benchmark_pack_ids": list(self.benchmark_pack_ids),
        }


DEFAULT_CODING_LANGUAGE_PROFILES: tuple[CodingLanguageProfile, ...] = (
    CodingLanguageProfile(
        key="python",
        display_name="Python",
        runtime_profile="python",
        entrypoint="main.py",
        hints=("python", "pytest", "pandas", "fastapi", "flask", "script", "module", "package"),
        suggested_commands=("python main.py", "python -m pytest -q"),
        starter_files=("main.py", "tests/test_main.py"),
        capabilities=("read_files", "write_files", "run_python", "run_pytest", "scaffold_modules"),
        tags=("backend", "automation", "data"),
        runtime_requirement_groups=(("workspace_python", "python"),),
        required_markers=(),
    ),
    CodingLanguageProfile(
        key="javascript",
        display_name="JavaScript",
        runtime_profile="node",
        entrypoint="index.js",
        hints=("javascript", "node", "npm", "js", "express", "react"),
        suggested_commands=("node index.js", "npm test", "npm start"),
        starter_files=("index.js", "package.json", "tests/basic.test.js"),
        capabilities=("read_files", "write_files", "run_node", "run_npm_scripts", "scaffold_web_tools"),
        tags=("node", "web"),
        runtime_requirement_groups=(("node",),),
        required_markers=("node_project",),
    ),
    CodingLanguageProfile(
        key="typescript",
        display_name="TypeScript",
        runtime_profile="node",
        entrypoint="src/index.ts",
        hints=("typescript", "ts", "tsconfig", "tsx", "vite", "next"),
        suggested_commands=("npx tsc --noEmit", "npm test", "npm run build"),
        starter_files=("src/index.ts", "tsconfig.json", "package.json"),
        capabilities=("read_files", "write_files", "run_typescript_checks", "run_npm_scripts", "scaffold_web_tools"),
        tags=("node", "web"),
        runtime_requirement_groups=(("node",), ("npx", "npm", "pnpm", "bun", "workspace_tsc", "tsc")),
        required_markers=("node_project", "typescript_config"),
    ),
    CodingLanguageProfile(
        key="web",
        display_name="Web App",
        runtime_profile="web_static",
        entrypoint="index.html",
        hints=("html", "css", "frontend", "web app", "landing page", "site"),
        suggested_commands=("python -m http.server 8000", "npm run dev"),
        starter_files=("index.html", "styles.css", "app.js"),
        capabilities=("read_files", "write_files", "preview_static_site", "scaffold_ui"),
        tags=("ui", "web"),
        runtime_requirement_groups=(),
        required_markers=("web_entry",),
    ),
    CodingLanguageProfile(
        key="game",
        display_name="Browser Game",
        runtime_profile="web_static",
        entrypoint="index.html",
        hints=("game", "canvas", "pygame", "arcade", "platformer", "shooter", "rpg"),
        suggested_commands=("python -m http.server 8000", "python main.py"),
        starter_files=("index.html", "game.js", "styles.css"),
        capabilities=("read_files", "write_files", "preview_static_site", "prototype_gameplay"),
        tags=("interactive", "ui"),
        runtime_requirement_groups=(),
        required_markers=("web_entry",),
    ),
)


_PROFILE_INDEX = {profile.key: profile for profile in DEFAULT_CODING_LANGUAGE_PROFILES}


def list_language_profiles() -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in DEFAULT_CODING_LANGUAGE_PROFILES]


def get_language_profile(profile_key: str) -> CodingLanguageProfile:
    return _PROFILE_INDEX.get(str(profile_key or "").strip().lower(), _PROFILE_INDEX["python"])


def filter_suggested_commands(profile: CodingLanguageProfile, available_runtime_keys: set[str]) -> list[str]:
    keys = {str(key or "").strip().lower() for key in set(available_runtime_keys or set())}
    out: list[str] = []
    for command in profile.suggested_commands:
        if command.startswith("python ") and not ({"workspace_python", "python"} & keys):
            continue
        if command.startswith("node ") and "node" not in keys:
            continue
        if command.startswith("npm ") and "npm" not in keys:
            continue
        if command.startswith("npx ") and "npx" not in keys:
            continue
        out.append(command)
    return out or list(profile.suggested_commands[:2])


def infer_language_profile(objective: str, *, default_key: str = "python") -> CodingLanguageProfile:
    text = str(objective or "").strip().lower()
    if not text:
        return get_language_profile(default_key)

    if re.search(r"\b(html|css|landing page|website|frontend|web app)\b", text):
        if "game" in text or "canvas" in text:
            return get_language_profile("game")
        return get_language_profile("web")
    if re.search(r"\b(typescript|tsconfig|tsx|\\.ts\b|next.js|vite)\b", text):
        return get_language_profile("typescript")
    if re.search(r"\b(javascript|node|npm|express|react|vue|\\.js\b)\b", text):
        return get_language_profile("javascript")
    if re.search(r"\b(game|canvas|pygame|arcade|platformer|shooter|rpg)\b", text):
        return get_language_profile("game")
    if re.search(r"\b(python|pytest|pandas|fastapi|flask|script|module|package)\b", text):
        return get_language_profile("python")

    best = get_language_profile(default_key)
    best_score = 0
    for profile in DEFAULT_CODING_LANGUAGE_PROFILES:
        score = sum(1 for hint in profile.hints if hint in text)
        if score > best_score:
            best = profile
            best_score = score
    return best
