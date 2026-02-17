"""Memory façade.

Legacy imports use `from memory import MemoryManager`.
Implementation now lives under `handlers.memory`.
"""

from handlers.memory import MemoryManager

__all__ = ["MemoryManager"]
