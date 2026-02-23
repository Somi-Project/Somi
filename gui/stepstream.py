from __future__ import annotations

from collections import deque

from runtime.stream import StepSink


class GuiStepSink(StepSink):
    def __init__(self):
        self.events = deque(maxlen=200)

    def emit(self, event):
        self.events.append(event)
