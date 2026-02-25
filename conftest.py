"""Repository-level pytest collection guards.

Prevents utility/template scripts from being collected as unit tests in CI.
"""

collect_ignore_glob = [
    "toolbox/templates/test_template.py",
    "tools/workspace/**/test_*.py",
    "tools/installed/**/test_*.py",
    "speech/tools/test_stack.py",
    "speech/tools/test_tts.py",
]
