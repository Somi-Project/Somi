"""Echo policy helpers.

Tier0 is mandatory: disable STT while speaking and only watch VAD/barge-in onset.
"""


def stt_allowed(state: str, policy: str) -> bool:
    if policy in {"tier0", "tier1"} and state == "SPEAKING":
        return False
    return True
