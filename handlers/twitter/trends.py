def normalize_topic(topic: str) -> str:
    return " ".join((topic or "").strip().lower().split())


def unique_topics(topics):
    seen = set()
    result = []
    for topic in topics:
        key = normalize_topic(topic)
        if key and key not in seen:
            seen.add(key)
            result.append(topic)
    return result
