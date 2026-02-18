from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from speech.config import AGENT_NAME_DEFAULT, USE_STUDIES_DEFAULT, USER_ID_DEFAULT

_agent = None


def init_agent_bridge(
    agent_name: str = AGENT_NAME_DEFAULT,
    use_studies: bool = USE_STUDIES_DEFAULT,
    user_id: str = USER_ID_DEFAULT,
) -> None:
    """Initialize a singleton Agent used by speech."""
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


async def ask_agent_stream(prompt: str, user_id: str) -> AsyncIterator[str]:
    if _agent is None:
        init_agent_bridge()

    stream_fn = getattr(_agent, "generate_response_stream", None)
    if callable(stream_fn):
        async for fragment in stream_fn(prompt, user_id=user_id):
            if fragment:
                yield str(fragment)
        return

    # Emulated stream fallback preserves Somi's full response pipeline.
    final = await ask_agent(prompt, user_id=user_id)
    if not final:
        return

    step = 80
    for i in range(0, len(final), step):
        yield final[i : i + step]
        await asyncio.sleep(0)
