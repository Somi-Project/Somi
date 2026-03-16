from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from speech.config import AGENT_NAME_DEFAULT, USE_STUDIES_DEFAULT, USER_ID_DEFAULT
from speech.metrics.log import logger

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

    logger.info("Agent stream start: user_id=%s prompt_chars=%s", user_id, len(prompt or ""))
    stream_fn = getattr(_agent, "generate_response_stream", None)
    if callable(stream_fn):
        emitted = 0
        async for fragment in stream_fn(prompt, user_id=user_id):
            if fragment:
                emitted += 1
                yield str(fragment)
        logger.info("Agent stream done (native): user_id=%s fragments=%s", user_id, emitted)
        return

    # Emulated stream fallback preserves Somi's full response pipeline.
    final = await ask_agent(prompt, user_id=user_id)
    if not final:
        logger.info("Agent stream done (fallback): user_id=%s empty_response=1", user_id)
        return

    step = 80
    emitted = 0
    for i in range(0, len(final), step):
        emitted += 1
        yield final[i : i + step]
        await asyncio.sleep(0)
    logger.info("Agent stream done (fallback): user_id=%s fragments=%s", user_id, emitted)
