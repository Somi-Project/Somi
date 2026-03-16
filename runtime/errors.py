from __future__ import annotations


class CapabilityError(Exception):
    pass


class PrivilegeError(Exception):
    pass


class SandboxError(Exception):
    pass


class ShellError(Exception):
    pass


class VerifyError(Exception):
    pass


class InstallError(Exception):
    pass


class PolicyError(Exception):
    pass


class RateLimitError(Exception):
    pass


class CancelledError(Exception):
    pass
