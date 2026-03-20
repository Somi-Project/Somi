from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class BenchmarkCase:
    query: str
    kind: str
    must_domains: tuple[str, ...] = ()
    focus_terms: tuple[str, ...] = ()
    expected_modes: tuple[str, ...] = ()


BASELINE_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase("check out openclaw on github", "github", ("github.com",), ("openclaw",), ("github",)),
    BenchmarkCase("summarize this https://github.com/openclaw/openclaw", "github", ("github.com",), ("openclaw",), ("github",)),
    BenchmarkCase(
        "what are the latest hypertension guidelines",
        "medical_latest",
        ("acc.org", "heart.org", "ahajournals.org", "escardio.org", "who.int", "nice.org.uk"),
        ("hypertension", "guideline"),
        ("deep",),
    ),
    BenchmarkCase(
        "latest ACC/AHA hypertension guideline",
        "medical_latest",
        ("acc.org", "heart.org", "ahajournals.org"),
        ("acc", "aha", "hypertension", "guideline"),
        ("deep",),
    ),
    BenchmarkCase(
        "compare openclaw and deer-flow on github",
        "github_compare",
        ("github.com",),
        ("openclaw", "deer-flow"),
        ("github",),
    ),
    BenchmarkCase(
        "what changed in python 3.13 docs",
        "docs_change",
        ("docs.python.org", "github.com"),
        ("python", "3.13", "docs"),
        ("deep",),
    ),
    BenchmarkCase(
        "latest WHO dengue treatment guidance",
        "medical_latest",
        ("who.int", "paho.org", "cdc.gov"),
        ("who", "dengue", "guidance"),
        ("deep",),
    ),
)

_RISKY_TERMS = (
    "porn",
    "sex",
    "nude",
    "weapon",
    "weapons",
    "bomb",
    "explosive",
    "munitions",
    "suicide",
    "self-harm",
    "self harm",
    "meth",
    "cocaine",
    "heroin",
    "torrent",
    "pirated",
)

_STOPWORDS = {
    "a", "an", "and", "best", "buy", "current", "for", "guide", "guidance", "guideline",
    "guidelines", "how", "in", "is", "latest", "new", "of", "on", "out", "price", "show",
    "summarize", "the", "this", "today", "update", "what", "whats", "with",
}

WEATHER_LOCATIONS = (
    "San Francisco, CA", "New York, NY", "Miami, FL", "Chicago, IL", "Seattle, WA",
    "Austin, TX", "Boston, MA", "Atlanta, GA", "Denver, CO", "Phoenix, AZ",
    "Los Angeles, CA", "Toronto, Canada", "London, UK", "Madrid, Spain", "Tokyo, Japan",
    "Sydney, Australia", "Singapore", "Kingston, Jamaica", "Port of Spain, Trinidad and Tobago", "Barbados",
)
NEWS_TOPICS = (
    "artificial intelligence", "inflation", "climate change", "NASA", "Apple", "Google", "Microsoft",
    "Tesla", "Bitcoin", "Ethereum", "Premier League", "NBA", "NFL", "healthcare", "travel", "movies",
    "gaming", "cybersecurity", "renewable energy", "space exploration",
)
FINANCE_STEMS = (
    "AAPL stock price", "MSFT stock price", "NVDA stock price", "AMD stock price", "TSLA stock price",
    "AMZN stock price", "META stock price", "GOOGL stock price", "JPM stock price", "BRK.B stock price",
    "SPY price", "QQQ price", "VTI price", "VOO price", "Bitcoin price", "Ethereum price", "Solana price",
    "gold price", "oil price", "EUR USD exchange rate",
)
MEDICAL_TOPICS = (
    ("hypertension", ("heart.org", "ahajournals.org", "acc.org", "escardio.org", "nice.org.uk")),
    ("asthma", ("ginasthma.org", "nhlbi.nih.gov", "nice.org.uk")),
    ("diabetes", ("diabetesjournals.org", "who.int", "nice.org.uk", "cdc.gov")),
    ("heart failure", ("heart.org", "acc.org", "escardio.org")),
    ("COPD", ("goldcopd.org", "nice.org.uk", "nih.gov")),
    ("dengue", ("who.int", "cdc.gov", "paho.org")),
    ("obesity", ("who.int", "nice.org.uk", "nih.gov")),
    ("lipid management", ("ahajournals.org", "acc.org", "escardio.org")),
    ("depression", ("nice.org.uk", "who.int", "psychiatry.org")),
    ("migraine", ("nice.org.uk", "who.int")),
    ("osteoporosis", ("nice.org.uk", "nih.gov", "who.int")),
    ("atrial fibrillation", ("heart.org", "acc.org", "escardio.org")),
    ("chronic kidney disease", ("kdigo.org", "nice.org.uk", "nih.gov")),
    ("stroke prevention", ("heart.org", "stroke.org", "escardio.org")),
    ("insomnia", ("aasm.org", "nice.org.uk", "nih.gov")),
)
DOCS_TARGETS = (
    ("python 3.13", ("docs.python.org", "github.com"), ("python", "3.13", "docs")),
    ("node.js 22", ("nodejs.org", "github.com"), ("node", "22", "release")),
    ("react 19", ("react.dev", "github.com"), ("react", "19", "release")),
    ("next.js 15", ("nextjs.org", "github.com"), ("next", "15", "release")),
    ("typescript 5.8", ("typescriptlang.org", "github.com"), ("typescript", "5.8", "release")),
    ("postgres 17", ("postgresql.org", "github.com"), ("postgres", "17", "release")),
    ("django 5.2", ("docs.djangoproject.com", "github.com"), ("django", "5.2", "release")),
    ("fastapi", ("fastapi.tiangolo.com", "github.com"), ("fastapi", "release")),
    ("docker compose", ("docs.docker.com", "github.com"), ("docker", "compose")),
    ("kubernetes 1.32", ("kubernetes.io", "github.com"), ("kubernetes", "1.32", "release")),
    ("tailwind css 4", ("tailwindcss.com", "github.com"), ("tailwind", "4", "release")),
    ("playwright", ("playwright.dev", "github.com"), ("playwright", "release")),
    ("pandas 2.3", ("pandas.pydata.org", "github.com"), ("pandas", "2.3", "release")),
    ("pytest 8", ("docs.pytest.org", "github.com"), ("pytest", "8", "release")),
    ("rust 1.84", ("doc.rust-lang.org", "blog.rust-lang.org", "github.com"), ("rust", "1.84", "release")),
)
GITHUB_REPOS = (
    ("OpenClaw", "openclaw/openclaw"), ("Deer Flow", "bytedance/deer-flow"), ("OpenAI Python", "openai/openai-python"),
    ("TypeScript", "microsoft/TypeScript"), ("PyTorch", "pytorch/pytorch"), ("LangChain", "langchain-ai/langchain"),
    ("Requests", "psf/requests"), ("Flask", "pallets/flask"), ("Django", "django/django"), ("FastAPI", "fastapi/fastapi"),
    ("Next.js", "vercel/next.js"), ("React", "facebook/react"), ("VS Code", "microsoft/vscode"),
    ("Docker Compose", "docker/compose"), ("Kubernetes", "kubernetes/kubernetes"), ("Ollama", "ollama/ollama"),
    ("CPython", "python/cpython"), ("Node.js", "nodejs/node"), ("Pandas", "pandas-dev/pandas"), ("Playwright", "microsoft/playwright"),
)
GITHUB_COMPARE_PAIRS = (
    ("openclaw", "deer-flow"), ("react", "next.js"), ("django", "fastapi"), ("pytorch", "tensorflow"),
    ("requests", "httpx"), ("postgres", "mysql"), ("playwright", "selenium"), ("ollama", "llama.cpp"),
    ("tailwind css", "bootstrap"), ("vite", "webpack"), ("flask", "django"), ("langchain", "llamaindex"),
    ("docker compose", "kubernetes"), ("pandas", "polars"), ("redis", "memcached"),
)
TRAVEL_DESTINATIONS = (
    "Tokyo", "Paris", "Rome", "Kyoto", "Cancun", "Barbados", "Trinidad and Tobago", "New Orleans",
    "Lisbon", "Seoul", "Cape Town", "Vancouver", "Dubai", "Bangkok", "Iceland", "Costa Rica",
    "Miami", "San Juan", "Amsterdam", "Singapore",
)
SHOPPING_PAIRS = (
    ("iPhone 16", "Samsung Galaxy S25"), ("MacBook Air", "Dell XPS 13"), ("Kindle Paperwhite", "Kobo Clara"),
    ("Apple Watch", "Garmin Forerunner"), ("PlayStation 5", "Xbox Series X"), ("AirPods Pro", "Sony WF-1000XM5"),
    ("iPad Air", "iPad Pro"), ("Ninja Creami", "Cuisinart ice cream maker"), ("Roomba j9", "Roborock S8"),
    ("Dyson V15", "Shark Stratos"), ("Instant Pot", "Ninja Foodi"), ("Switch OLED", "Steam Deck"),
    ("Oura Ring", "Whoop"), ("Brother laser printer", "HP LaserJet"), ("GoPro Hero", "DJI Action"),
    ("Sony A7C II", "Canon R8"), ("Logitech MX Master 3S", "Magic Mouse"), ("Kindle Scribe", "reMarkable 2"),
    ("Bose QC Ultra", "AirPods Max"), ("Peloton Bike", "Echelon EX-5"),
)
GENERAL_FACT_QUERIES = (
    "benefits of walking every day", "how much protein do I need per day", "how to lower resting heart rate",
    "what is glycemic index", "what causes inflation", "how do solar panels work", "how to improve sleep quality",
    "what is creatine used for", "how much water should I drink daily", "what is cortisol",
    "how does compound interest work", "how many calories to lose weight", "how to clean cast iron",
    "how to start composting", "how to learn python effectively", "how to prepare for a job interview",
    "how to meal prep for the week", "how to train for a 5k", "what is VO2 max", "how to build credit history",
)
OFFICIAL_INFO_TOPICS = (
    ("passport renewal requirements", ("travel.state.gov", "usa.gov")),
    ("TSA ID requirements", ("tsa.gov", "usa.gov")),
    ("IRS mileage rate", ("irs.gov",)),
    ("FAFSA deadlines", ("studentaid.gov",)),
    ("CDC flu vaccine guidance", ("cdc.gov",)),
    ("WHO measles update", ("who.int",)),
    ("FDA peanut allergy label guidance", ("fda.gov",)),
    ("NOAA hurricane season outlook", ("noaa.gov", "weather.gov")),
    ("CDC travel vaccines for Brazil", ("cdc.gov",)),
    ("IRS tax brackets", ("irs.gov",)),
    ("USCIS fee schedule", ("uscis.gov",)),
    ("EPA air quality guidance", ("epa.gov", "airnow.gov")),
    ("CMS telehealth rules", ("cms.gov",)),
    ("OSHA heat guidance", ("osha.gov",)),
    ("NWS hurricane preparedness guidance", ("weather.gov", "ready.gov")),
)
DIRECT_URL_TARGETS = (
    ("https://docs.python.org/3/whatsnew/3.13.html", ("python", "3.13")),
    ("https://react.dev/blog", ("react", "blog")),
    ("https://developer.mozilla.org/en-US/docs/Web/JavaScript", ("javascript", "mdn")),
    ("https://docs.github.com/en/search-github/github-code-search/understanding-github-code-search-syntax", ("github", "code", "search")),
    ("https://fastapi.tiangolo.com/", ("fastapi",)),
    ("https://nextjs.org/blog", ("next.js", "blog")),
    ("https://www.python.org/dev/peps/pep-0703/", ("python", "pep", "703")),
    ("https://docs.docker.com/compose/", ("docker", "compose")),
    ("https://www.who.int/news/item/10-07-2025-new-who-guidelines-for-clinical-management-of-arboviral-diseases--dengue--chikungunya--zika-and-yellow-fever", ("who", "dengue", "guidelines")),
    ("https://playwright.dev/docs/intro", ("playwright", "docs")),
)


def _focus_terms(text: str, limit: int = 4) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9][a-z0-9.+/-]{1,}", str(text or "").lower())
    picked: list[str] = []
    for token in tokens:
        token = token.strip(".")
        if not token or token in _STOPWORDS or token in picked:
            continue
        picked.append(token)
        if len(picked) >= limit:
            break
    return tuple(picked)


def _is_safe(query: str) -> bool:
    ql = str(query or "").lower()
    return not any(term in ql for term in _RISKY_TERMS)


def _rr_merge(groups: Sequence[Sequence[BenchmarkCase]], limit: int) -> list[BenchmarkCase]:
    queues = [list(group) for group in groups if group]
    out: list[BenchmarkCase] = []
    seen: set[str] = set()
    while queues and len(out) < max(1, int(limit)):
        next_round: list[list[BenchmarkCase]] = []
        for queue in queues:
            if not queue:
                continue
            case = queue.pop(0)
            if case.query not in seen and _is_safe(case.query):
                out.append(case)
                seen.add(case.query)
                if len(out) >= limit:
                    break
            if queue:
                next_round.append(queue)
        queues = next_round
    return out


def _weather_cases() -> list[BenchmarkCase]:
    templates = ("weather in {x}", "today weather in {x}", "forecast for {x}", "will it rain in {x} today", "temperature in {x}")
    return [BenchmarkCase(t.format(x=city), "weather", focus_terms=_focus_terms(city)) for city in WEATHER_LOCATIONS for t in templates]


def _news_cases() -> list[BenchmarkCase]:
    templates = ("latest {x} news", "{x} headlines today", "what happened with {x} today", "recent {x} news update", "top {x} stories right now")
    return [BenchmarkCase(t.format(x=topic), "news", focus_terms=_focus_terms(topic)) for topic in NEWS_TOPICS for t in templates]


def _finance_cases() -> list[BenchmarkCase]:
    templates = ("{x}", "{x} today", "latest {x}", "show me {x}", "what is {x}")
    return [BenchmarkCase(t.format(x=stem), "finance", focus_terms=_focus_terms(stem)) for stem in FINANCE_STEMS for t in templates]


def _medical_cases() -> list[BenchmarkCase]:
    templates = ("latest {x} guidelines", "latest {x} treatment guidance", "what are the latest {x} recommendations", "summarize recent {x} guidelines", "official {x} guideline update")
    return [BenchmarkCase(t.format(x=topic), "medical_latest", domains, _focus_terms(topic + " guideline"), ("deep",)) for topic, domains in MEDICAL_TOPICS for t in templates]


def _docs_cases() -> list[BenchmarkCase]:
    templates = ("what changed in {x} docs", "latest {x} release notes", "what's new in {x}", "summarize {x} changelog", "official {x} documentation changes")
    return [BenchmarkCase(t.format(x=name), "docs_change", domains, terms, ("deep",)) for name, domains, terms in DOCS_TARGETS for t in templates]


def _github_cases() -> list[BenchmarkCase]:
    templates = ("check out {name} on github", "summarize this https://github.com/{slug}", "what is {name} github repo about", "inspect {name} on github")
    return [BenchmarkCase(t.format(name=name, slug=slug), "github", ("github.com",), _focus_terms(name), ("github",)) for name, slug in GITHUB_REPOS for t in templates]


def _github_compare_cases() -> list[BenchmarkCase]:
    templates = ("compare {a} and {b} on github", "github comparison between {a} and {b}", "check out {a} versus {b} on github")
    return [BenchmarkCase(t.format(a=a, b=b), "github_compare", ("github.com",), _focus_terms(f"{a} {b}"), ("github",)) for a, b in GITHUB_COMPARE_PAIRS for t in templates]


def _direct_url_cases() -> list[BenchmarkCase]:
    templates = ("summarize this {url}", "what is this page about {url}", "key points from {url}", "check this out {url}")
    return [BenchmarkCase(t.format(url=url), "direct_url", (url.split('/')[2].lower(),), terms, ("direct_url",)) for url, terms in DIRECT_URL_TARGETS for t in templates]


def _travel_cases() -> list[BenchmarkCase]:
    templates = ("best time to visit {x}", "what to do in {x}", "how many days in {x}", "is {x} expensive", "top things to do in {x}")
    return [BenchmarkCase(t.format(x=place), "travel", focus_terms=_focus_terms(place)) for place in TRAVEL_DESTINATIONS for t in templates]


def _planning_cases() -> list[BenchmarkCase]:
    templates = ("plan a 3 day trip to {x}", "weekend itinerary for {x}", "budget for 4 days in {x}", "family trip plan for {x}", "food itinerary for {x}")
    return [BenchmarkCase(t.format(x=place), "planning", focus_terms=_focus_terms(place), expected_modes=("deep",)) for place in TRAVEL_DESTINATIONS for t in templates]


def _shopping_cases() -> list[BenchmarkCase]:
    templates = ("compare {a} and {b}", "which is better {a} or {b}", "pros and cons of {a} vs {b}", "difference between {a} and {b}", "should I buy {a} or {b}")
    return [BenchmarkCase(t.format(a=a, b=b), "shopping_compare", focus_terms=_focus_terms(f"{a} {b}")) for a, b in SHOPPING_PAIRS for t in templates]


def _general_fact_cases() -> list[BenchmarkCase]:
    templates = ("{x}", "explain {x}", "quick summary of {x}", "research {x}", "what should I know about {x}")
    return [BenchmarkCase(t.format(x=subject), "general_factual", focus_terms=_focus_terms(subject)) for subject in GENERAL_FACT_QUERIES for t in templates]


def _official_info_cases() -> list[BenchmarkCase]:
    templates = ("latest {x}", "official {x} update", "current {x}", "summarize {x} guidance")
    return [BenchmarkCase(t.format(x=topic), "general_latest", domains, _focus_terms(topic), ("deep",)) for topic, domains in OFFICIAL_INFO_TOPICS for t in templates]


def build_everyday_corpus(limit: int = 1000) -> list[BenchmarkCase]:
    return _rr_merge(
        (
            _weather_cases(),
            _news_cases(),
            _finance_cases(),
            _medical_cases(),
            _docs_cases(),
            _github_cases(),
            _github_compare_cases(),
            _direct_url_cases(),
            _travel_cases(),
            _planning_cases(),
            _shopping_cases(),
            _general_fact_cases(),
            _official_info_cases(),
        ),
        limit=max(1, int(limit or 1000)),
    )


def build_research_smoke_corpus(limit: int = 50) -> list[BenchmarkCase]:
    return _rr_merge((BASELINE_CASES, _medical_cases(), _docs_cases(), _github_cases(), _github_compare_cases(), _direct_url_cases(), _official_info_cases()), limit=max(1, int(limit or 50)))


def build_hard_research_corpus(limit: int = 100) -> list[BenchmarkCase]:
    return _rr_merge(
        (
            BASELINE_CASES,
            _medical_cases(),
            _docs_cases(),
            _github_cases(),
            _github_compare_cases(),
            _direct_url_cases(),
            _planning_cases(),
            _official_info_cases(),
        ),
        limit=max(1, int(limit or 100)),
    )


def build_named_corpus(name: str) -> list[BenchmarkCase]:
    normalized = str(name or "default").strip().lower()
    if normalized in {"default", "baseline"}:
        return list(BASELINE_CASES)
    if normalized == "research50":
        return build_research_smoke_corpus(limit=50)
    if normalized == "researchhard25":
        return build_hard_research_corpus(limit=25)
    if normalized == "researchhard100":
        return build_hard_research_corpus(limit=100)
    if normalized == "everyday100":
        return build_everyday_corpus(limit=100)
    if normalized == "everyday250":
        return build_everyday_corpus(limit=250)
    if normalized == "everyday1000":
        return build_everyday_corpus(limit=1000)
    raise ValueError(f"Unknown corpus: {name}")


def slice_cases(cases: Sequence[BenchmarkCase], *, limit: int = 0, chunk_size: int = 0, chunk_index: int = 0) -> list[BenchmarkCase]:
    sliced = list(cases)
    if limit and limit > 0:
        sliced = sliced[:limit]
    if chunk_size and chunk_size > 0:
        start = max(0, int(chunk_index)) * int(chunk_size)
        sliced = sliced[start : start + int(chunk_size)]
    return sliced
