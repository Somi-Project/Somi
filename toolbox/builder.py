from __future__ import annotations

from pathlib import Path

from runtime.fs_ops import FSOps


def _fill(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


class ToolBuilder:
    def __init__(self, fs: FSOps, templates_dir: str = "toolbox/templates") -> None:
        self.fs = fs
        self.templates = Path(templates_dir)

    def build(self, name: str, description: str, workspace: str = "tools/workspace") -> str:
        target = f"{workspace}/{name}"
        self.fs.mkdir(target)
        values = {"name": name, "description": description}
        self.fs.write_text(f"{target}/manifest.json", _fill((self.templates / "manifest_template.json").read_text(encoding="utf-8"), values))
        self.fs.write_text(f"{target}/tool.py", (self.templates / "tool_skeleton.py").read_text(encoding="utf-8"))
        self.fs.write_text(f"{target}/test_tool.py", (self.templates / "test_template.py").read_text(encoding="utf-8"))
        self.fs.write_text(f"{target}/README.md", _fill((self.templates / "readme_template.md").read_text(encoding="utf-8"), values))
        return target
