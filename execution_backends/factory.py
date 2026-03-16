from __future__ import annotations

from runtime.security_guard import normalize_execution_backend

from .base import BackendExecutionRequest, BackendExecutionResult, ExecutionBackendError
from .local_backend import LocalExecutionBackend


class _UnsupportedExecutionBackend:
    def __init__(self, name: str) -> None:
        self.name = str(name or "unknown")

    def execute(self, request: BackendExecutionRequest) -> BackendExecutionResult:  # noqa: ARG002
        raise ExecutionBackendError(
            f"Execution backend '{self.name}' is not available yet in Somi. "
            "Use 'local' for now."
        )


class ExecutionBackendRegistry:
    def __init__(self) -> None:
        self._backends = {
            "local": LocalExecutionBackend(),
        }

    def get(self, name: str):
        backend_name = normalize_execution_backend(name)
        return self._backends.get(backend_name) or _UnsupportedExecutionBackend(backend_name)

    def list_backends(self) -> list[dict[str, object]]:
        return [
            {"name": "local", "available": True, "kind": "subprocess"},
            {"name": "docker", "available": False, "kind": "container"},
            {"name": "remote", "available": False, "kind": "remote"},
            {"name": "gpu", "available": False, "kind": "worker"},
        ]


DEFAULT_BACKEND_REGISTRY = ExecutionBackendRegistry()
