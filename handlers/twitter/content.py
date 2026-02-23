import random

REPLY_TEMPLATES = [
    "Specific point on {topic}: {insight}. Curious—what tradeoff are you seeing?",
    "Quick framework for {topic}: signal, constraint, next-step. Which part is hardest right now?",
    "Slightly contrarian take: {insight}. Could be wrong—what data would change your view?",
    "I like the angle on {topic}. One nuance: {insight}. How are you testing this?",
]


def generate_high_signal_reply(topic: str, insight: str) -> str:
    return random.choice(REPLY_TEMPLATES).format(topic=topic, insight=insight)
