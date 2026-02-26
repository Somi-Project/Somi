"""Toolbox safety settings and mode guardrails."""

MODE_SAFE = "SAFE"
MODE_GUIDED = "GUIDED"
MODE_SYSTEM_AGENT = "SYSTEM_AGENT"

TOOLBOX_MODE = MODE_SAFE

# High-friction system agent opt-in.
ENABLE_SYSTEM_AGENT_MODE = False
SYSTEM_AGENT_I_ACCEPT_RISK = ""
SYSTEM_AGENT_REQUIRED_PHRASE = "I ACKNOWLEDGE SYSTEM_AGENT RISK"

ALLOW_EXTERNAL_APPS = False
ALLOW_SYSTEM_WIDE_ACTIONS = False
ALLOW_NETWORK = False
ALLOW_DELETE_ACTIONS = False
DEFAULT_EMAIL_ACTION = "archive"
REQUIRE_TARGETSET_PREVIEW_FOR_BULK = True
REQUIRE_DRY_RUN_FOR_BULK = True
MAX_BULK_ITEMS = 200
REQUIRE_TYPED_CONFIRM_FOR_CRITICAL = True

PROTECTED_PATHS = [
    "~",
    "~/Documents",
    "~/Desktop",
    "~/Downloads",
    "~/.ssh",
    "~/.gnupg",
    "~/.config/google-chrome",
    "~/.config/chromium",
    "~/.mozilla",
    "/etc",
    "/usr",
    "/var",
    "C:/Windows",
    "C:/Users",
]

SAFE_ALLOWED_COMMANDS = []
EXEC_TIMEOUT_SECONDS = 30
MAX_OUTPUT_KB = 512

NEVER_DO_PATTERNS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
]


def normalized_mode() -> str:
    return str(TOOLBOX_MODE or MODE_SAFE).strip().upper()


def assert_mode_safety() -> None:
    """Runtime guardrails; comments are not safety controls."""
    mode = normalized_mode()
    if mode == MODE_SYSTEM_AGENT:
        if not ENABLE_SYSTEM_AGENT_MODE:
            raise RuntimeError(
                "SYSTEM_AGENT mode requires ENABLE_SYSTEM_AGENT_MODE=True"
            )
        if SYSTEM_AGENT_I_ACCEPT_RISK != SYSTEM_AGENT_REQUIRED_PHRASE:
            raise RuntimeError("SYSTEM_AGENT mode requires exact typed risk phrase")
