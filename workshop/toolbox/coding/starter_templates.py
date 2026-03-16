from __future__ import annotations

import json
import re
from pathlib import Path

from workshop.toolbox.coding.profiles import CodingLanguageProfile

_PYTHON_STARTER_MAIN = (
    "def main() -> None:\n"
    "    print('Hello from Somi coding mode.')\n\n\n"
    "if __name__ == '__main__':\n"
    "    main()\n"
)

_PYTHON_STARTER_TEST_LEGACY = (
    "from main import main\n\n\n"
    "def test_main_exists() -> None:\n"
    "    assert callable(main)\n"
)

_PYTHON_STARTER_TEST = (
    "from pathlib import Path\n\n\n"
    "def test_workspace_contains_python_source() -> None:\n"
    "    project_root = Path(__file__).resolve().parents[1]\n"
    "    source_files = [\n"
    "        path for path in project_root.rglob('*.py')\n"
    "        if 'tests' not in path.parts and path.name != '__init__.py'\n"
    "    ]\n"
    "    assert source_files\n"
)


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower()).strip("._-")
    return text or "somi-coding-workspace"


def build_starter_file_map(profile: CodingLanguageProfile, *, title: str) -> dict[str, str]:
    project_slug = _slugify(title)
    if profile.key == "javascript":
        return {
            "index.js": "function main() {\n  console.log(\"Hello from Somi coding mode.\");\n}\n\nmain();\n",
            "package.json": json.dumps(
                {
                    "name": project_slug,
                    "version": "0.1.0",
                    "private": True,
                    "main": "index.js",
                    "scripts": {
                        "start": "node index.js",
                        "test": "node --test",
                    },
                },
                indent=2,
            )
            + "\n",
            "tests/basic.test.js": (
                "const test = require('node:test');\n"
                "const assert = require('node:assert/strict');\n\n"
                "test('workspace boots', () => {\n"
                "  assert.equal(typeof require('../index.js'), 'object');\n"
                "});\n"
            ),
        }
    if profile.key == "typescript":
        return {
            "src/index.ts": "export function main(): void {\n  console.log(\"Hello from Somi coding mode.\");\n}\n\nmain();\n",
            "package.json": json.dumps(
                {
                    "name": project_slug,
                    "version": "0.1.0",
                    "private": True,
                    "type": "module",
                    "scripts": {
                        "build": "tsc",
                        "test": "tsc --noEmit",
                        "start": "node dist/index.js",
                    },
                    "devDependencies": {
                        "typescript": "^5.7.0",
                    },
                },
                indent=2,
            )
            + "\n",
            "tsconfig.json": json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2022",
                        "module": "ES2022",
                        "moduleResolution": "Bundler",
                        "strict": True,
                        "outDir": "dist",
                    },
                    "include": ["src"],
                },
                indent=2,
            )
            + "\n",
        }
    if profile.key == "web":
        return {
            "index.html": (
                "<!doctype html>\n"
                "<html lang=\"en\">\n"
                "  <head>\n"
                "    <meta charset=\"utf-8\">\n"
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                f"    <title>{title}</title>\n"
                "    <link rel=\"stylesheet\" href=\"styles.css\">\n"
                "  </head>\n"
                "  <body>\n"
                "    <main class=\"shell\">\n"
                "      <h1>Somi Coding Workspace</h1>\n"
                "      <p>Start shaping the interface from here.</p>\n"
                "      <button id=\"pulse\">Pulse</button>\n"
                "    </main>\n"
                "    <script src=\"app.js\"></script>\n"
                "  </body>\n"
                "</html>\n"
            ),
            "styles.css": (
                ":root {\n"
                "  color-scheme: dark;\n"
                "  --bg: #07111f;\n"
                "  --panel: rgba(13, 27, 42, 0.86);\n"
                "  --edge: rgba(121, 192, 255, 0.22);\n"
                "  --text: #e6f4ff;\n"
                "  --accent: #6dd3ff;\n"
                "}\n\n"
                "body {\n"
                "  margin: 0;\n"
                "  min-height: 100vh;\n"
                "  display: grid;\n"
                "  place-items: center;\n"
                "  background: radial-gradient(circle at top, #0f2740, var(--bg));\n"
                "  color: var(--text);\n"
                "  font-family: 'Segoe UI', sans-serif;\n"
                "}\n\n"
                ".shell {\n"
                "  padding: 2rem;\n"
                "  border: 1px solid var(--edge);\n"
                "  border-radius: 24px;\n"
                "  background: var(--panel);\n"
                "  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);\n"
                "}\n"
            ),
            "app.js": (
                "const pulse = document.getElementById('pulse');\n"
                "pulse?.addEventListener('click', () => {\n"
                "  pulse.textContent = pulse.textContent === 'Pulse' ? 'Live' : 'Pulse';\n"
                "});\n"
            ),
        }
    if profile.key == "game":
        return {
            "index.html": (
                "<!doctype html>\n"
                "<html lang=\"en\">\n"
                "  <head>\n"
                "    <meta charset=\"utf-8\">\n"
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
                f"    <title>{title}</title>\n"
                "    <link rel=\"stylesheet\" href=\"styles.css\">\n"
                "  </head>\n"
                "  <body>\n"
                "    <canvas id=\"stage\" width=\"960\" height=\"540\"></canvas>\n"
                "    <script src=\"game.js\"></script>\n"
                "  </body>\n"
                "</html>\n"
            ),
            "styles.css": "body { margin: 0; background: #050816; display: grid; place-items: center; min-height: 100vh; }\ncanvas { border: 1px solid #6dd3ff; background: linear-gradient(180deg, #091a2d, #030711); }\n",
            "game.js": (
                "const canvas = document.getElementById('stage');\n"
                "const ctx = canvas?.getContext('2d');\n"
                "let x = 48;\n\n"
                "function frame() {\n"
                "  if (!ctx || !canvas) return;\n"
                "  ctx.clearRect(0, 0, canvas.width, canvas.height);\n"
                "  ctx.fillStyle = '#6dd3ff';\n"
                "  ctx.fillRect(x, 220, 48, 48);\n"
                "  x = (x + 2) % canvas.width;\n"
                "  requestAnimationFrame(frame);\n"
                "}\n\n"
                "frame();\n"
            ),
        }
    return {
        "main.py": _PYTHON_STARTER_MAIN,
        "tests/test_main.py": _PYTHON_STARTER_TEST,
    }


def scaffold_workspace(root_path: Path, profile: CodingLanguageProfile, *, title: str) -> list[str]:
    created: list[str] = []
    desired_map = build_starter_file_map(profile, title=title)
    for relative_path, content in desired_map.items():
        target = root_path / relative_path
        if target.exists():
            if relative_path == "tests/test_main.py":
                try:
                    existing = target.read_text(encoding="utf-8")
                except OSError:
                    existing = ""
                if existing == _PYTHON_STARTER_TEST_LEGACY:
                    target.write_text(_PYTHON_STARTER_TEST, encoding="utf-8")
            if profile.key == "typescript" and relative_path == "package.json":
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
                scripts = dict(existing.get("scripts") or {})
                changed = False
                if scripts.get("test") != "tsc --noEmit":
                    scripts["test"] = "tsc --noEmit"
                    changed = True
                if scripts.get("build") != "tsc":
                    scripts["build"] = "tsc"
                    changed = True
                if changed:
                    existing["scripts"] = scripts
                    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(relative_path.replace("\\", "/"))
    gitignore = root_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n.pytest_cache/\n.venv/\nnode_modules/\ndist/\ncoverage/\n", encoding="utf-8")
        created.append(".gitignore")
    return created
