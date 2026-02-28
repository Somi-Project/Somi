from __future__ import annotations

import executive.engine as eng


def test_tick_returns_rate_limited_payload_when_budget_exceeded(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    e = eng.ExecutiveEngine()

    class _Budget:
        def allow_intent(self):
            raise eng.RateLimitError("limit")

    e.budgets = _Budget()
    out = e.tick()
    assert out.get("error") == "rate_limited"
