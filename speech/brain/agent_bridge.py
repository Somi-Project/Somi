from __future__ import annotations

from typing import Optional

from speech.config import AGENT_NAME_DEFAULT, USE_STUDIES_DEFAULT, USER_ID_DEFAULT

_agent = None


def init_agent_bridge(
    agent_name: str = AGENT_NAME_DEFAULT,
    use_studies: bool = USE_STUDIES_DEFAULT,
    user_id: str = USER_ID_DEFAULT,
) -> None:
    """Initialize a singleton Agent used by speech.

    The speech stack depends on agents.py, never the reverse.
    """
    global _agent
    if _agent is None:
        from agents import Agent

        _agent = Agent(name=agent_name, use_studies=use_studies, user_id=user_id)


def get_agent() -> Optional[object]:
    return _agent


async def ask_agent(text: str, user_id: str) -> str:
    if _agent is None:
        init_agent_bridge()
    return await _agent.generate_response(text, user_id=user_id)
