from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Literal
from urllib.parse import urlparse


_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.IGNORECASE)

_RECENCY_TERMS = (
    "latest",
    "current",
    "today",
    "now",
    "right now",
    "updated",
    "newest",
    "most recent",
    "recent",
)
_CITATION_TERMS = (
    "source",
    "sources",
    "citation",
    "citations",
    "cite",
    "link",
    "links",
    "verify",
    "confirm",
)
_DEEP_TERMS = (
    "compare",
    "versus",
    " vs ",
    "which is better",
    "should i buy",
    "difference between",
    "pros and cons",
    "check out",
    "look into",
    "analyze",
    "analyse",
    "walk me through",
    "what changed",
    "summarize",
    "summarise",
    "overview",
    "guideline",
    "guidelines",
    "guidance",
    "official",
    "roadmap",
    "issues",
    "release notes",
    "changelog",
    "what's new",
    "whats new",
    "itinerary",
    "trip plan",
    "plan a",
    "weekend itinerary",
)
_SOFTWARE_CHANGE_TERMS = (
    "release notes",
    "changelog",
    "what changed",
    "documentation changes",
    "docs changes",
    "what's new",
    "whats new",
)
_GITHUB_EXPLICIT_TERMS = (
    "github",
    "repo",
    "repository",
    "readme",
    "pull request",
    "stars",
    "forks",
)
_GITHUB_CONTEXT_TERMS = (
    "release",
    "releases",
    "changelog",
    "open source",
    "issues",
)
_SOFTWARE_TERMS = (
    "docs",
    "documentation",
    "package",
    "library",
    "framework",
    "sdk",
    "install",
    "installation",
    "usage",
    "example",
    "examples",
)
_SOFTWARE_PROJECT_DOMAINS = {
    "node.js": ("nodejs.org",),
    "next.js": ("nextjs.org",),
    "react": ("react.dev",),
    "typescript": ("typescriptlang.org",),
    "django": ("docs.djangoproject.com", "djangoproject.com"),
    "fastapi": ("fastapi.tiangolo.com",),
    "docker compose": ("docs.docker.com",),
    "kubernetes": ("kubernetes.io",),
    "rust": ("blog.rust-lang.org", "doc.rust-lang.org", "rust-lang.org"),
    "playwright": ("playwright.dev",),
    "pandas": ("pandas.pydata.org",),
    "pytest": ("docs.pytest.org", "pytest.org"),
    "tailwind css": ("tailwindcss.com",),
}
_SOFTWARE_PROJECT_HINTS = {
    "node.js": ("node.js", "nodejs"),
    "next.js": ("next.js", "nextjs"),
    "react": ("react",),
    "typescript": ("typescript",),
    "django": ("django",),
    "fastapi": ("fastapi",),
    "docker compose": ("docker compose",),
    "kubernetes": ("kubernetes",),
    "rust": ("rust",),
    "playwright": ("playwright",),
    "pandas": ("pandas",),
    "pytest": ("pytest",),
    "tailwind css": ("tailwind css", "tailwindcss"),
}
_LEADING_ACTION_RE = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:check out|look into|look up|summarize|summarise|research|analyze|analyse|compare|tell me about|what is|what's|who is|who's)\s+",
    re.IGNORECASE,
)
_TRAILING_GITHUB_RE = re.compile(r"\s+(?:on|from|at)\s+github\s*$", re.IGNORECASE)
_COMPARE_SPLIT_RE = re.compile(r"\s+(?:and|or|vs\.?|versus)\s+", re.IGNORECASE)
_COMPARE_PREFIX_RE = re.compile(
    r"^(?:compare|which is better|should i buy|difference between|pros and cons of)\s+",
    re.IGNORECASE,
)
_TRAVEL_DEST_RE = re.compile(
    r"(?:trip\s+to|itinerary\s+for|days\s+in|visit|for)\s+([a-z0-9][a-z0-9 ,.'&/-]+)$",
    re.IGNORECASE,
)
_GITHUB_RESERVED_PATHS = {
    "about",
    "account",
    "blog",
    "codespaces",
    "collections",
    "contact",
    "customers",
    "enterprise",
    "events",
    "explore",
    "features",
    "issues",
    "login",
    "marketplace",
    "models",
    "new",
    "notifications",
    "orgs",
    "organizations",
    "pricing",
    "pulls",
    "readme",
    "search",
    "security",
    "settings",
    "site",
    "sponsors",
    "stars",
    "topics",
    "trending",
}


@dataclass
class BrowsePlan:
    mode: Literal["quick", "deep", "github", "direct_url"]
    query: str
    query_variants: List[str] = field(default_factory=list)
    direct_urls: List[str] = field(default_factory=list)
    needs_recency: bool = False
    needs_citations: bool = False
    official_preferred: bool = False
    cleanup_downloads: bool = True
    reason: str = ""


def extract_urls(text: str) -> List[str]:
    raw = str(text or "")
    seen: set[str] = set()
    out: List[str] = []
    for match in _URL_RE.findall(raw):
        url = match.rstrip(".,)")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    for term in needles:
        needle = str(term or "").lower()
        if not needle:
            continue
        if needle != needle.strip():
            if needle in haystack:
                return True
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        if re.search(pattern, haystack) is not None:
            return True
    return False


def _software_project_labels(query: str) -> List[str]:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql:
        return []
    labels: List[str] = []
    for label, hints in _SOFTWARE_PROJECT_HINTS.items():
        if any(hint in ql for hint in hints):
            labels.append(label)
    return labels


def is_software_change_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql:
        return False
    if not _contains_any(ql, _SOFTWARE_CHANGE_TERMS):
        return False
    return bool(_software_project_labels(ql)) or _contains_any(ql, _SOFTWARE_TERMS)


def _is_github_repo_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    if host != "github.com":
        return False
    parts = [part for part in (parsed.path or "").split("/") if part]
    if len(parts) < 2:
        return False
    if parts[0].lower() in _GITHUB_RESERVED_PATHS:
        return False
    return True


def _dedupe_queries(rows: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for row in rows:
        clean = " ".join(str(row or "").split()).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def normalize_lookup_subject(text: str) -> str:
    subject = " ".join(str(text or "").split()).strip()
    if not subject:
        return ""
    subject = _LEADING_ACTION_RE.sub("", subject)
    subject = _TRAILING_GITHUB_RE.sub("", subject)
    subject = re.sub(r"^this\s+", "", subject, flags=re.IGNORECASE)
    subject = re.sub(r"\s+", " ", subject).strip(" ?!.")
    return subject or " ".join(str(text or "").split()).strip()


def _github_subject_from_urls(urls: List[str]) -> str:
    for url in urls or []:
        clean = str(url or "").strip()
        if not _is_github_repo_url(clean):
            continue
        parts = [part for part in clean.rstrip("/").split("/") if part]
        try:
            idx = next(i for i, part in enumerate(parts) if part.lower() == "github.com")
        except StopIteration:
            continue
        tail = parts[idx + 1 :]
        if len(tail) >= 2:
            return f"{tail[0]}/{tail[1]}"
    return ""


def comparison_subjects(text: str) -> List[str]:
    subject = " ".join(str(text or "").split()).strip()
    if not subject:
        return []
    subject = _COMPARE_PREFIX_RE.sub("", subject)
    parts = [part.strip(" ?!.") for part in _COMPARE_SPLIT_RE.split(subject) if part.strip(" ?!.")]
    if len(parts) < 2:
        return []
    return parts[:3]


def is_trip_planning_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql:
        return False
    if "itinerary" in ql:
        return True
    if any(
        marker in ql
        for marker in (
            "budget for",
            "food budget",
            "travel cost",
            "average daily cost",
            "how much should i budget",
            " cost of ",
            " expensive",
        )
    ):
        return False
    patterns = (
        r"\bplan a\b",
        r"\btrip plan\b",
        r"\bweekend itinerary\b",
        r"\bfamily trip\b",
        r"\bfood itinerary\b",
        r"\b\d+\s*day\b",
    )
    return any(re.search(pattern, ql) is not None for pattern in patterns) and any(term in ql for term in ("trip", "travel", "visit", "itinerary", "days in"))


def _travel_lookup_destination(query: str) -> str:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not ql:
        return ""
    patterns = (
        r"\bbest time to visit\s+(.+)$",
        r"\b(?:what to do|things to do|top things to do) in\s+(.+)$",
        r"\bhow many days in\s+(.+)$",
        r"\bbudget for\s+\d+\s*days?\s+in\s+(.+)$",
        r"\b(?:food\s+)?budget in\s+(.+)$",
        r"\b(?:travel\s+)?cost(?:\s+of)?\s+(.+)$",
        r"\bhow much should i budget for\s+(.+)$",
        r"\bis\s+(.+?)\s+expensive\b",
    )
    for pattern in patterns:
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip(" ?!.,")
    return ""


def is_travel_lookup_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql or is_trip_planning_query(ql):
        return False
    if "github" in ql:
        return False
    markers = (
        "best time to visit",
        "what to do in",
        "things to do in",
        "top things to do in",
        "how many days in",
        "budget for",
        "budget in",
        "food budget",
        "travel cost",
        "average daily cost",
        "how much should i budget",
        " cost of ",
        " expensive",
    )
    return any(marker in ql for marker in markers) and bool(_travel_lookup_destination(query))


def is_shopping_compare_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql:
        return False
    compare_like = any(marker in ql for marker in ("compare", "versus", " vs ", "which is better", "should i buy", "difference between", "pros and cons"))
    subjects = comparison_subjects(normalize_lookup_subject(query))
    if len(subjects) < 2:
        return False
    return compare_like and "github" not in ql


def is_government_requirements_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not ql:
        return False
    subject_terms = (
        "passport",
        "visa",
        "immigration",
        "uscis",
        "green card",
        "citizenship",
        "naturalization",
        "social security",
        "ssa",
        "irs",
        "tax",
        "medicare",
        "medicaid",
    )
    ask_terms = (
        "requirement",
        "requirements",
        "renew",
        "renewal",
        "apply",
        "application",
        "document",
        "documents",
        "eligibility",
        "processing time",
        "fees",
        "fee",
        "deadline",
    )
    return any(term in ql for term in subject_terms) and any(term in ql for term in ask_terms)


def trip_planning_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not is_trip_planning_query(q):
        return []
    day_match = re.search(r"\b(\d+)\s*day\b", ql)
    days = str(day_match.group(1)).strip() if day_match else ""
    dest_match = _TRAVEL_DEST_RE.search(q)
    destination = str(dest_match.group(1)).strip(" ?!.") if dest_match else ""
    if not destination:
        destination = q
    variants: List[str] = [
        q,
        f"{destination} itinerary",
        f"{destination} travel guide",
        f"{destination} trip planning guide",
    ]
    if days:
        variants.extend(
            [
                f"{days} day {destination} itinerary",
                f"{destination} itinerary {days} days",
                f"best {days} day itinerary {destination}",
            ]
        )
    return variants


def travel_lookup_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not is_travel_lookup_query(q):
        return []
    destination = _travel_lookup_destination(q) or q
    variants: List[str] = [
        q,
        f"{destination} travel guide",
        f"{destination} official tourism",
    ]
    if "best time to visit" in ql:
        variants.extend(
            [
                f"best time to visit {destination}",
                f"{destination} weather seasons",
                f"when to visit {destination}",
            ]
        )
    elif any(marker in ql for marker in ("what to do in", "things to do in", "top things to do in")):
        variants.extend(
            [
                f"{destination} things to do",
                f"{destination} attractions guide",
                f"{destination} first time guide",
            ]
        )
    elif "how many days in" in ql:
        variants.extend(
            [
                f"{destination} how many days",
                f"{destination} itinerary",
                f"{destination} first time itinerary",
            ]
        )
    elif "expensive" in ql or "budget" in ql or "cost" in ql:
        variants.extend(
            [
                f"{destination} travel cost",
                f"{destination} budget guide",
                f"{destination} average daily cost",
            ]
        )
    return _dedupe_queries(variants)


def shopping_compare_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    if not is_shopping_compare_query(q):
        return []
    subjects = comparison_subjects(normalize_lookup_subject(q))
    if len(subjects) < 2:
        return []
    left, right = subjects[0], subjects[1]
    return [
        q,
        f"{left} vs {right}",
        f"{left} versus {right}",
        f"{left} {right} comparison",
        f"{left} {right} review",
        f"which is better {left} or {right}",
    ]


def _is_python_docs_like_query(query: str) -> bool:
    ql = " ".join(str(query or "").split()).strip().lower()
    if "python" not in ql:
        return False
    markers = ("docs", "documentation", "release notes", "what's new", "whats new", "changelog")
    return any(marker in ql for marker in markers)


def infer_official_domains(query: str) -> List[str]:
    ql = str(query or "").lower()
    domains: List[str] = []
    medical_guidance = _contains_any(ql, _RECENCY_TERMS) or any(
        term in ql
        for term in (
            "guideline",
            "guidelines",
            "guidance",
            "recommendation",
            "recommendations",
            "treatment",
            "management",
            "therapy",
            "care standard",
            "standards of care",
        )
    )

    def add(*items: str) -> None:
        for item in items:
            if item not in domains:
                domains.append(item)

    if re.search(r"\bacc\b|\baha\b|acc/aha", ql):
        add("acc.org", "heart.org", "ahajournals.org", "jacc.org")
    if "hypertension" in ql or "blood pressure" in ql:
        add("acc.org", "heart.org", "ahajournals.org", "jacc.org", "escardio.org", "who.int", "nice.org.uk")
    if re.search(r"\bwho\b", ql):
        add("who.int")
    if re.search(r"\bcdc\b", ql) or "flu vaccine" in ql or "travel vaccines" in ql:
        add("cdc.gov")
    if re.search(r"\bfda\b", ql):
        add("fda.gov")
    if re.search(r"\btsa\b", ql):
        add("tsa.gov", "usa.gov")
    if "fafsa" in ql or "student aid" in ql:
        add("studentaid.gov")
    if "dengue" in ql:
        add("who.int", "paho.org", "cdc.gov")
    if medical_guidance and "diabetes" in ql:
        add("diabetesjournals.org")
    if medical_guidance and "asthma" in ql:
        add("ginasthma.org")
    if medical_guidance and "heart failure" in ql:
        add("acc.org", "heart.org")
    if medical_guidance and "copd" in ql:
        add("goldcopd.org")
    if medical_guidance and ("cholesterol" in ql or "lipid" in ql):
        add("acc.org", "heart.org")
    if medical_guidance and "insomnia" in ql:
        add("aasm.org", "nice.org.uk")
    if re.search(r"\bnoaa\b", ql) or "hurricane season outlook" in ql:
        add("noaa.gov", "weather.gov", "nhc.noaa.gov", "cpc.ncep.noaa.gov")
    if re.search(r"\bnws\b", ql) or "hurricane preparedness" in ql:
        add("weather.gov", "ready.gov")
    if re.search(r"\bepa\b", ql) or "air quality" in ql:
        add("epa.gov", "airnow.gov")
    if re.search(r"\bcms\b", ql) or "telehealth rules" in ql:
        add("cms.gov")
    if re.search(r"\bosha\b", ql) or "heat guidance" in ql:
        add("osha.gov")
    if _is_python_docs_like_query(ql):
        add("docs.python.org", "python.org")
    if "passport" in ql:
        add("travel.state.gov", "state.gov", "usa.gov")
    if any(term in ql for term in ("visa", "immigration", "uscis", "green card", "citizenship", "naturalization")):
        add("travel.state.gov", "state.gov", "uscis.gov", "cbp.gov", "usa.gov")
    if "social security" in ql or re.search(r"\bssa\b", ql):
        add("ssa.gov", "usa.gov")
    if "tax" in ql or re.search(r"\birs\b", ql):
        add("irs.gov", "usa.gov")
    if "medicare" in ql or "medicaid" in ql:
        add("medicare.gov", "cms.gov", "medicaid.gov", "usa.gov")
    for project_label in _software_project_labels(ql):
        add(*_SOFTWARE_PROJECT_DOMAINS.get(project_label, ()))
    return domains


def _python_doc_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not _is_python_docs_like_query(q):
        return []
    variants: List[str] = []
    version_match = re.search(r"\b(\d+\.\d+)\b", q)
    if version_match:
        version = version_match.group(1)
        variants.extend(
            [
                f"What's New In Python {version}",
                f"site:docs.python.org What's New In Python {version}",
                f"Python {version} release notes",
                f"site:python.org Python {version} release",
                f"site:docs.python.org Python {version} changelog",
                f"site:docs.python.org Python {version} release highlights",
            ]
        )
    variants.extend(
        [
            "site:docs.python.org Python documentation",
            "site:python.org Python release notes",
        ]
    )
    return variants


def _cardio_guideline_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not re.search(r"\bacc\b|\baha\b|acc/aha", ql):
        return []
    if "hypertension" not in ql and "blood pressure" not in ql:
        return []
    return [
        "2025 high blood pressure guideline",
        "site:ahajournals.org 2025 high blood pressure guideline",
        "site:jacc.org 2025 high blood pressure guideline",
        "site:heart.org top 10 things to know about the AHA/ACC high blood pressure guideline",
        "site:acc.org new ACC/AHA high blood pressure guideline",
    ]


def _hypertension_guideline_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if "hypertension" not in ql and "blood pressure" not in ql:
        return []
    if not any(term in ql for term in ("guideline", "guidelines", "guidance", "recommendation", "recommendations")):
        return []
    return [
        "2025 high blood pressure guideline",
        "2025 hypertension guideline",
        "site:ahajournals.org 2025 high blood pressure guideline",
        "site:jacc.org 2025 high blood pressure guideline",
        "site:heart.org 2025 high blood pressure guideline",
        "site:acc.org 2025 high blood pressure guideline",
        "site:escardio.org 2024 elevated blood pressure hypertension guideline",
    ]


def _who_dengue_guidance_variants(query: str) -> List[str]:
    ql = " ".join(str(query or "").split()).strip().lower()
    if "dengue" not in ql:
        return []
    if "who" not in ql and "cdc" not in ql:
        return []
    if not any(term in ql for term in ("latest", "recent", "updated", "guidance", "guideline", "guidelines", "treatment", "clinical management")):
        return []
    return [
        "site:who.int 2025 arboviral diseases dengue guideline",
        "site:who.int 2025 dengue clinical management guideline",
        "site:who.int new WHO guidelines clinical management arboviral diseases dengue",
        'site:who.int "new WHO guidelines for clinical management of arboviral diseases" dengue',
        "site:cdc.gov dengue clinical management 2024 2025",
    ]


def _government_requirement_variants(query: str) -> List[str]:
    ql = " ".join(str(query or "").split()).strip().lower()
    if not is_government_requirements_query(ql):
        return []
    variants: List[str] = [query]
    if "passport" in ql:
        variants.extend(
            [
                "site:travel.state.gov passport renewal requirements",
                "site:travel.state.gov renew an adult passport",
                "site:travel.state.gov passport renewal documents",
            ]
        )
    if any(term in ql for term in ("visa", "immigration", "uscis", "green card", "citizenship", "naturalization")):
        variants.extend(
            [
                "site:uscis.gov immigration requirements",
                "site:travel.state.gov visa requirements",
                "site:cbp.gov travel document requirements",
            ]
        )
    if "social security" in ql or re.search(r"\bssa\b", ql):
        variants.append("site:ssa.gov social security requirements")
    if "tax" in ql or re.search(r"\birs\b", ql):
        variants.append("site:irs.gov tax requirements")
    if "medicare" in ql or "medicaid" in ql:
        variants.append("site:medicare.gov medicare requirements")
    return variants


def _software_change_variants(query: str) -> List[str]:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    if not is_software_change_query(q):
        return []
    versions = re.findall(r"\b\d+(?:\.\d+){1,2}\b", q)
    labels = _software_project_labels(ql)
    variants: List[str] = [q]
    for label in labels[:2]:
        variants.extend(
            [
                f"{label} release notes",
                f"{label} changelog",
                f"{label} documentation changes",
            ]
        )
        for version in versions[:2]:
            variants.extend(
                [
                    f"{label} {version} release notes",
                    f"{label} {version} changelog",
                    f"{label} {version} documentation changes",
                ]
            )
        for domain in _SOFTWARE_PROJECT_DOMAINS.get(label, ())[:3]:
            variants.extend(
                [
                    f"site:{domain} {label} release notes",
                    f"site:{domain} {label} changelog",
                ]
            )
            for version in versions[:2]:
                variants.extend(
                    [
                        f"site:{domain} {label} {version} release notes",
                        f"site:{domain} {label} {version} changelog",
                    ]
                )
    return variants


def build_browse_plan(query: str, *, intent_hint: str = "", route_hint: str = "") -> BrowsePlan:
    q = " ".join(str(query or "").split()).strip()
    ql = q.lower()
    urls = extract_urls(q)
    repo_urls = [url for url in urls if _is_github_repo_url(url)]
    ql_without_urls = _URL_RE.sub(" ", q).lower()
    subject = normalize_lookup_subject(q)
    github_subject = _github_subject_from_urls(repo_urls)
    if github_subject:
        subject = github_subject
    needs_recency = _contains_any(ql, _RECENCY_TERMS)
    needs_citations = _contains_any(ql, _CITATION_TERMS)
    wants_deep = _contains_any(ql, _DEEP_TERMS)
    trip_planning = is_trip_planning_query(q)
    travel_lookup = is_travel_lookup_query(q)
    shopping_compare = is_shopping_compare_query(q)
    government_requirements = is_government_requirements_query(q)
    mentions_github = _contains_any(ql_without_urls, _GITHUB_EXPLICIT_TERMS) or bool(repo_urls)
    if not mentions_github and _contains_any(ql_without_urls, _GITHUB_CONTEXT_TERMS):
        mentions_github = " github " in f" {ql_without_urls} " or any(term in ql_without_urls for term in ("repo", "repository", "readme"))
    software_lookup = _contains_any(ql, _SOFTWARE_TERMS)
    software_change = is_software_change_query(q)
    inferred_official_domains = infer_official_domains(ql)
    official_preferred = (
        needs_citations
        or "official" in ql
        or "guideline" in ql
        or "guidelines" in ql
        or "guidance" in ql
        or "documentation" in ql
        or "docs" in ql
        or _is_python_docs_like_query(q)
        or software_change
        or government_requirements
        or re.search(r"\bwho\b|\bcdc\b|\bnice\b", ql) is not None
        or bool(inferred_official_domains)
    )

    if urls:
        mode: Literal["quick", "deep", "github", "direct_url"]
        mode = "github" if repo_urls else "direct_url"
        reason = "direct_url_input"
    elif mentions_github:
        mode = "github"
        reason = "github_lookup"
    elif intent_hint in {"science", "research"} or route_hint in {"research", "websearch"}:
        mode = "deep" if (needs_recency or needs_citations or wants_deep or software_lookup or software_change or trip_planning or travel_lookup or shopping_compare) else "quick"
        reason = "research_or_web_route"
    elif needs_recency or needs_citations or wants_deep or software_change or trip_planning or travel_lookup or shopping_compare:
        mode = "deep"
        reason = "freshness_or_depth_needed"
    elif software_lookup:
        mode = "deep"
        reason = "software_lookup"
    else:
        mode = "quick"
        reason = "simple_lookup"

    variants: List[str] = [q]
    official_domains = inferred_official_domains if official_preferred else []
    if mode == "deep":
        variants.extend(
            [
                subject,
                f"{subject} official source",
                f"{subject} overview",
                f"{subject} documentation" if software_lookup else f"{subject} evidence review",
                f"{subject} current status" if needs_recency else f"{subject} limitations",
            ]
        )
        variants.extend(_python_doc_variants(q))
        variants.extend(_software_change_variants(q))
        variants.extend(_hypertension_guideline_variants(q))
        variants.extend(_cardio_guideline_variants(q))
        variants.extend(_who_dengue_guidance_variants(q))
        variants.extend(_government_requirement_variants(q))
        variants.extend(trip_planning_variants(q))
        variants.extend(travel_lookup_variants(q))
        variants.extend(shopping_compare_variants(q))
        for domain in official_domains[:4]:
            variants.append(f"site:{domain} {q}")
            if subject and subject != q:
                variants.append(f"site:{domain} {subject}")
    elif mode == "github":
        compare_subjects = comparison_subjects(subject)
        variants.extend(
            [
                subject,
                f"{subject} github",
                f"site:github.com {subject}",
                f"{subject} repository",
                f"{subject} readme",
                f"{subject} documentation",
                f"{subject} release notes",
            ]
        )
        for compare_subject in compare_subjects:
            variants.extend(
                [
                    compare_subject,
                    f"{compare_subject} github",
                    f"site:github.com {compare_subject}",
                    f"{compare_subject} readme",
                ]
            )
    elif mode == "direct_url":
        variants.extend([u for u in urls[:3]])

    if needs_recency:
        variants.append(f"{subject} 2026")

    return BrowsePlan(
        mode=mode,
        query=q,
        query_variants=_dedupe_queries(variants),
        direct_urls=urls,
        needs_recency=needs_recency,
        needs_citations=needs_citations,
        official_preferred=official_preferred,
        cleanup_downloads=True,
        reason=reason,
    )
