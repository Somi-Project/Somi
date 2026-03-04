import sys
import types


# Some local test environments may not include optional runtime deps.
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.ModuleType("httpx")

from handlers.research import searxng


def test_domain_profiles_present_for_research_router_domains():
    expected = {
        "biomed",
        "engineering",
        "nutrition",
        "religion",
        "entertainment",
        "business_administrator",
        "journalism_communication",
    }
    assert expected.issubset(set(searxng._DOMAIN_TO_PROFILE.keys()))

    for domain, profile in searxng._DOMAIN_TO_PROFILE.items():
        assert profile in searxng._PROFILES
        assert searxng._PROFILES[profile].domain == domain
