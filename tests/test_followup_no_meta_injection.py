from handlers.followup_sanitizer import sanitize_user_visible_prompt
from handlers.followup_resolver import FollowUpResolver
from handlers.routing import decide_route
from handlers.tool_context import ToolContextStore


INJECTION_MARKERS = (
    "previous query:",
    "previous top result:",
    "now answer this follow-up:",
    "decide whether to:",
)


def _contains_injection(text: str) -> bool:
    tl = (text or "").lower()
    return any(marker in tl for marker in INJECTION_MARKERS)


def test_followup_routing_text_uses_clean_rewrite_only():
    store = ToolContextStore(ttl_seconds=300)
    store.set(
        "u1",
        "finance",
        "whats the price of bitcoin",
        [{"title": "BTC", "url": "https://example.com/btc", "description": "..."}],
    )
    ctx = store.get("u1")

    r = FollowUpResolver().resolve("what was the price in 2021", ctx)
    assert r is not None
    assert r.action == "rewrite_query"
    assert r.rewritten_query == "bitcoin price 2021"
    assert not _contains_injection(r.rewritten_query)


def test_sanitize_user_visible_prompt_prevents_recursive_nesting():
    injected = (
        'Previous query: "x"\n'
        'Previous top result: "y"\n'
        "Now answer this follow-up: what was the price in 2021\n"
        "Decide whether to: websearch"
    )
    sanitized = sanitize_user_visible_prompt(injected)
    assert sanitized == "what was the price in 2021"
    assert not _contains_injection(sanitized)


def test_url_summarize_followup_routes_open_url_path():
    text = "summarize this URL: https://example.com"
    resolution = FollowUpResolver().resolve(text, None)
    assert resolution is not None
    assert resolution.action == "open_url_and_summarize"
    assert resolution.url == "https://example.com"

    decision = decide_route(text, agent_state={"has_tool_context": False, "last_tool_type": ""})
    assert decision.route == "websearch"
    assert decision.reason == "open_url_and_summarize"
