from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    INSTALLED = "INSTALLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass
class Job:
    job_id: str
    objective: str
    state: JobState = JobState.PENDING
