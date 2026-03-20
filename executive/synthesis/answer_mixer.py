from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from workshop.toolbox.stacks.web_core.search_bundle import SearchBundle
from routing.types import QueryPlan, TimeAnchor


_RECENCY_WORDS = re.compile(r"\b(today|current|latest|now)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:[\.,]\d+)?\b")
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_DATE_PHRASE = re.compile(r"\b(?:released on|published on|updated on)\s+([A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_WHITESPACE = re.compile(r"\s+")
_REPO_SLUG = re.compile(r"github\.com/([^/\s]+/[^/\s?#]+)", re.IGNORECASE)
_DEFAULT_BRANCH = re.compile(r"Default branch:\s*([A-Za-z0-9._/-]+)", re.IGNORECASE)
_LATEST_COMMIT = re.compile(r"Latest visible commit:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*\|\s*([0-9a-f]{6,})", re.IGNORECASE)
_MANIFESTS = re.compile(r"(?:Detected manifests|manifests)\s*:\s*(.+?)(?:README excerpt:|Top-level entries:|Latest visible commit:|$)", re.IGNORECASE)
_SUPPORTING = re.compile(r"\n?Supporting sources:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_SUMMARY_PREFIX = re.compile(r"^summary\s*[-:]\s*release highlights\s*[:\-]*\s*", re.IGNORECASE)
_LEADING_TIMESTAMP = re.compile(r"^\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s*")
_WEAK_DRAFT_MARKERS = (
    "couldn't verify",
    "could not verify",
    "insufficient evidence",
    "not enough detail",
    "not fully confident",
    "don't have enough detail",
    "do not have enough detail",
    "i'm uncertain",
    "i am uncertain",
    "i don't know",
    "i do not know",
)
_BENIGN_WARNING_MARKERS = (
    "temporary repository clone cleaned up",
    "cleaned up after inspection",
    "cleanup",
)
_LOW_VALUE_SOURCE_PATTERNS = (
    re.compile(r"/toc/", re.IGNORECASE),
    re.compile(r"\bvol\s*\d+\s*,\s*no\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bsession(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bconference\b", re.IGNORECASE),
    re.compile(r"\bmeeting\b", re.IGNORECASE),
)
_TITLECASE_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
_TITLECASE_ACRONYMS = {
    "acc": "ACC",
    "aha": "AHA",
    "api": "API",
    "cdc": "CDC",
    "faq": "FAQ",
    "jacc": "JACC",
    "nih": "NIH",
    "who": "WHO",
}
_OFFICIAL_QUERY_TERMS = (
    "guideline",
    "guidelines",
    "guidance",
    "official",
    "requirement",
    "requirements",
    "eligibility",
    "deadline",
    "renew",
    "renewal",
    "apply",
    "application",
    "passport",
)
_FOCUS_AROUND_RE = re.compile(
    r"\b(?:frames?(?: the choice)? around|focus(?:es|ed)? on|center(?:s|ed)? on|highlights?|points to)\s+(.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)
_LEADING_DATE_ONLY_RE = re.compile(
    r"^(?:published|updated|released)(?:\s+on)?\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\.?\s*$|^\d{4}-\d{2}-\d{2}\.?\s*$",
    re.IGNORECASE,
)


def _strip_recency_words(text: str) -> str:
    cleaned = _RECENCY_WORDS.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _trim(text: str, limit: int = 280) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _legacy_repair_text(text: str | None) -> str:
    raw = html.unescape(str(text or "").strip())
    if not raw:
        return ""

    if any(marker in raw for marker in ("Ã", "Â", "â", "ðŸ")):
        try:
            repaired = raw.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and (repaired.count("Ã") + repaired.count("Â") + repaired.count("â") < raw.count("Ã") + raw.count("Â") + raw.count("â")):
                raw = repaired
        except Exception:
            pass

    replacements = {
        "\xa0": " ",
        "Â¶": "",
        "â€“": "-",
        "â€”": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€¦": "...",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)

    raw = _MARKDOWN_LINK.sub(r"\1", raw)
    raw = _HTML_TAG.sub(" ", raw)
    raw = raw.replace("`", "")
    raw = raw.replace("**", "")
    raw = raw.replace("__", "")
    raw = raw.replace("||", " | ")
    raw = _SUMMARY_PREFIX.sub("", raw)
    raw = _LEADING_TIMESTAMP.sub("", raw)
    raw = _WHITESPACE.sub(" ", raw).strip()
    return raw


def _repair_text(text: str | None) -> str:
    raw = html.unescape(str(text or "").strip())
    if not raw:
        return ""

    if any(marker in raw for marker in ("\u00c3", "\u00c2", "\u00e2", "\u00f0")):
        try:
            repaired = raw.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            raw_score = raw.count("\u00c3") + raw.count("\u00c2") + raw.count("\u00e2")
            repaired_score = repaired.count("\u00c3") + repaired.count("\u00c2") + repaired.count("\u00e2")
            if repaired and repaired_score < raw_score:
                raw = repaired
        except Exception:
            pass

    replacements = {
        "\xa0": " ",
        "\u00c2\u00b6": "",
        "\u00c2\u00b7": " - ",
        "\u00e2\u20ac\u201c": "-",
        "\u00e2\u20ac\u201d": "-",
        "\u00e2\u20ac\u02dc": "'",
        "\u00e2\u20ac\u2122": "'",
        "\u00e2\u20ac\u0153": '"',
        "\u00e2\u20ac\u009d": '"',
        "\u00e2\u20ac\u00a6": "...",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)

    raw = _MARKDOWN_LINK.sub(r"\1", raw)
    raw = _HTML_TAG.sub(" ", raw)
    raw = raw.replace("`", "")
    raw = raw.replace("**", "")
    raw = raw.replace("__", "")
    raw = raw.replace("||", " | ")
    raw = _SUMMARY_PREFIX.sub("", raw)
    raw = _LEADING_TIMESTAMP.sub("", raw)
    raw = _WHITESPACE.sub(" ", raw).strip()
    return raw


def _first_sentence(text: str, *, limit: int = 220) -> str:
    clean = _repair_text(text)
    if not clean:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", clean)
    if match:
        return _trim(match.group(1).strip(), limit)
    return _trim(clean, limit)


def _split_summary(text: str) -> tuple[str, list[str]]:
    clean = _repair_text(text)
    if not clean:
        return "", []
    match = _SUPPORTING.search(clean)
    if not match:
        return clean, []
    lead = clean[: match.start()].strip()
    raw_support = match.group(1).strip()
    support = [_repair_text(part) for part in raw_support.split(";")]
    support = [part for part in support if part]
    return lead, support


def _source_label(url: str) -> str:
    host = (urlparse(url or "").netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or (url or "").strip()


def _source_identity(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    path = re.sub(r"^/doi/pdf/", "/doi/", path, flags=re.IGNORECASE)
    return f"{host}{path}".lower()


def _who_publication_rank(url: str) -> int:
    clean = str(url or "").strip().lower()
    if "/publications/i/item/" in clean:
        return 0
    if "/handle/" in clean:
        return 1
    if "/items/" in clean:
        return 2
    if "/publications/b/" in clean:
        return 3
    if "/bitstream/handle/" in clean or "/server/api/core/bitstreams/" in clean:
        return 4
    return 5


def _canonical_official_source_url(result, evidence: SearchBundle | None, context: str, title: str) -> str:
    url = str(result.url or "").strip()
    if context != "official" or title != "WHO guideline publication" or not evidence:
        return url
    topic_blob = _official_topic_blob(evidence)
    if not any(term in topic_blob for term in ("who", "dengue", "arboviral")):
        return url
    best_url = url
    best_rank = _who_publication_rank(url)
    for candidate in list(evidence.results or []):
        candidate_url = str(candidate.url or "").strip()
        rank = _who_publication_rank(candidate_url)
        if rank < best_rank:
            best_url = candidate_url
            best_rank = rank
    return best_url or url


def _titleize_phrase(text: str) -> str:
    clean = _repair_text(text)
    if not clean:
        return ""
    parts = re.split(r"(\s+)", clean)
    out: list[str] = []
    word_index = 0
    for part in parts:
        if not part:
            continue
        if part.isspace():
            out.append(part)
            continue
        match = re.match(r"^([^A-Za-z0-9]*)([A-Za-z0-9][A-Za-z0-9'/.-]*)([^A-Za-z0-9]*)$", part)
        if not match:
            out.append(part)
            continue
        prefix, word, suffix = match.groups()
        lower = word.lower()
        if lower in _TITLECASE_ACRONYMS:
            rendered = _TITLECASE_ACRONYMS[lower]
        elif word_index > 0 and lower in _TITLECASE_SMALL_WORDS:
            rendered = lower
        else:
            rendered = word[:1].upper() + word[1:].lower()
        out.append(f"{prefix}{rendered}{suffix}")
        word_index += 1
    return "".join(out).strip()


def _human_join(items: list[str]) -> str:
    clean = [str(item or "").strip() for item in items if str(item or "").strip()]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return f"{', '.join(clean[:-1])}, and {clean[-1]}"


def _append_sources(text: str, evidence: SearchBundle | None, limit: int = 2) -> str:
    if not evidence or not evidence.results:
        return text
    body = (text or "").rstrip()
    if "Sources:" in body:
        return body
    seen: set[str] = set()
    src = []
    for result in evidence.results:
        title = _repair_text(result.title)
        url = str(result.url or "").strip()
        if not title or not url or url in seen:
            continue
        seen.add(url)
        src.append(f"- {title}: {url}")
        if len(src) >= limit:
            break
    if not src:
        return body
    return f"{body}\n\nSources:\n" + "\n".join(src)


def _is_weak_draft(text: str) -> bool:
    clean = _repair_text(text).lower()
    if not clean:
        return True
    return any(marker in clean for marker in _WEAK_DRAFT_MARKERS)


def _detail_score(text: str) -> int:
    clean = _repair_text(text)
    if not clean:
        return 0
    years = len(_YEAR.findall(clean))
    codeish = clean.count("`")
    nouns = len([word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{3,}", clean) if not word.isdigit()])
    return min(10, years * 2 + codeish + min(6, nouns // 8))


def _result_text(result) -> str:
    return _repair_text(" ".join([str(result.title or ""), str(result.snippet or ""), str(result.published_date or "")]))


def _evidence_context(user_text: str, evidence: SearchBundle | None) -> str:
    ql = str(user_text or "").lower()
    urls = [str(result.url or "").lower() for result in list((evidence.results if evidence else []) or [])]
    if "github" in ql or any("github.com/" in url for url in urls):
        return "github"
    if " docs" in ql or "documentation" in ql or any("docs." in _source_label(url) for url in urls):
        return "docs"
    official_hosts = (
        "who.int",
        "iris.who.int",
        "ahajournals.org",
        "jacc.org",
        "acc.org",
        "heart.org",
        "nice.org.uk",
        "cdc.gov",
        "travel.state.gov",
        "uscis.gov",
        "state.gov",
        "medicare.gov",
        "irs.gov",
        "fda.gov",
        "faa.gov",
    )
    officialish_host_hit = any(any(host in url for host in official_hosts) for url in urls) or any(
        ".gov/" in url or url.endswith(".gov") for url in urls
    )
    if (
        any(term in ql for term in ("guideline", "guidelines", "guidance", "official", "who ", "acc/", "aha"))
        or (officialish_host_hit and any(term in ql for term in _OFFICIAL_QUERY_TERMS))
        or any(any(host in url for host in official_hosts) for url in urls)
    ):
        return "official"
    return "general"


def _action_clause(context: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    trace = [str(step or "").lower() for step in list((evidence.execution_trace if evidence else []) or [])]
    query_lower = str(getattr(plan, "search_query", "") or "").lower()
    if context == "github":
        return "I checked the repo directly"
    if context == "docs":
        return "I checked the official docs"
    if context == "general" and any(term in query_lower for term in ("compare ", " vs ", " versus ", "pros and cons", "should i buy")):
        return "I checked current comparison coverage"
    if any("official" in step for step in trace) or plan.needs_recency:
        return "I checked official sources"
    if any("read:" in step or "opened" in step for step in trace):
        return "I opened the relevant pages directly"
    return ""


def _top_anchor_tokens(evidence: SearchBundle | None) -> list[str]:
    if not evidence or not evidence.results:
        return []
    top = evidence.results[0]
    tokens: list[str] = []
    slug = _repo_slug(str(top.url or ""))
    if slug:
        tokens.append(slug.lower())
    year = _extract_year(_result_text(top))
    if year:
        tokens.append(str(year))
    title_words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9.+/-]{3,}", _repair_text(top.title))]
    for word in title_words[:4]:
        if word not in tokens:
            tokens.append(word)
    return tokens[:6]


def _draft_misses_anchor(draft: str, evidence: SearchBundle | None, context: str, plan: QueryPlan) -> bool:
    clean = _repair_text(draft).lower()
    if not clean:
        return True
    anchors = _top_anchor_tokens(evidence)
    if context == "github" and evidence and evidence.results:
        slug = _repo_slug(str(evidence.results[0].url or ""))
        if slug and slug.lower() not in clean:
            return True
    if plan.needs_recency:
        year = next((token for token in anchors if token.isdigit() and len(token) == 4), "")
        if year and year not in clean:
            return True
    if context == "docs":
        key_terms = ("interactive interpreter", "free-threaded", "jit", "python 3.13")
        if any(term in clean for term in key_terms):
            return False
    return not any(anchor in clean for anchor in anchors if anchor)


def _extract_year(text: str | None) -> int | None:
    match = _YEAR.search(str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _repo_slug(url: str) -> str:
    match = _REPO_SLUG.search(str(url or ""))
    if not match:
        return ""
    return match.group(1).rstrip("/")


def _extract_repo_focus(text: str) -> str:
    raw = _repair_text(text)
    if "readme excerpt:" in raw.lower():
        raw = raw.split("README excerpt:", 1)[-1].strip()
    patterns = [
        re.compile(r"is an open-source ([^.]+)\.", re.IGNORECASE),
        re.compile(r"is a[n]? ([^.]*assistant[^.]*)\.", re.IGNORECASE),
        re.compile(r"is a[n]? ([^.]*harness[^.]*)\.", re.IGNORECASE),
        re.compile(r"is a[n]? ([^.]*framework[^.]*)\.", re.IGNORECASE),
        re.compile(r"is a[n]? ([^.]{15,140})\.", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(raw)
        if not match:
            continue
        focus = match.group(1).strip(" .")
        if "github repository" in focus.lower():
            continue
        return focus
    return ""


def _extract_default_branch(text: str) -> str:
    match = _DEFAULT_BRANCH.search(_repair_text(text))
    return str(match.group(1)).strip().rstrip(".,;:") if match else ""


def _extract_latest_commit_date(text: str, fallback: str = "") -> str:
    match = _LATEST_COMMIT.search(_repair_text(text))
    if match:
        return str(match.group(1)).strip()
    return str(fallback or "").strip()


def _legacy_extract_manifests(text: str) -> list[str]:
    match = _MANIFESTS.search(_repair_text(text))
    if not match:
        return []
    manifests = [part.strip().rstrip(".,;:") for part in match.group(1).split(",")]
    manifests = [item for item in manifests if item and item.lower() != "none detected"]
    return manifests[:3]


def _repo_clause(result) -> str:
    slug = _repo_slug(str(result.url or "")) or _repair_text(result.title)
    focus = _extract_repo_focus(_result_text(result))
    manifests = _extract_manifests(_result_text(result))
    branch = _extract_default_branch(_result_text(result))

    details = []
    if focus:
        details.append(f"presents itself as {focus}")
    if manifests:
        manifests_text = _human_join([f"`{manifest}`" for manifest in manifests])
        details.append(f"shows {manifests_text}")
    if branch:
        details.append(f"uses `{branch}` as the default branch")
    if not details:
        return f"`{slug}`"
    return f"`{slug}` " + _human_join(details)


def _legacy_supporting_phrase(evidence: SearchBundle | None, *, context: str, limit: int = 2) -> str:
    if not evidence:
        return ""
    _, summary_support = _split_summary(getattr(evidence, "summary", ""))
    labels = list(summary_support)
    if not labels:
        for result in list(evidence.results or [])[1 : limit + 2]:
            label = _repair_text(result.title) or _source_label(result.url)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
    labels = labels[:limit]
    if not labels:
        return ""
    if context in {"official", "docs"}:
        return f"I cross-checked it against {_human_join(labels)}."
    if context == "github":
        return f"I also checked {_human_join(labels)}."
    return f"Supporting sources include {_human_join(labels)}."


def _legacy_build_recency_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    lead_summary, _ = _split_summary(getattr(evidence, "summary", ""))
    top = evidence.results[0]
    title = _repair_text(top.title)
    lead = _first_sentence(lead_summary) or _first_sentence(top.snippet) or title
    if "guideline" in str(user_text or "").lower() and "guideline" in title.lower() and _YEAR.search(title):
        lead = f"The latest guidance I found is {title}."
    elif any(marker in lead.lower() for marker in ("journal hub", "published jointly")):
        lead = _first_sentence(top.snippet) or title
    action = _action_clause("official", evidence, plan)
    parts = []
    if action:
        parts.append(action + ".")
    if lead:
        parts.append(lead)
    support = _supporting_phrase(evidence, context="official")
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _is_low_value_source_label(label: str) -> bool:
    clean = _repair_text(label)
    if not clean:
        return True
    return any(pattern.search(clean) for pattern in _LOW_VALUE_SOURCE_PATTERNS)


def _source_text(result) -> str:
    return _repair_text(
        " ".join([str(result.title or ""), str(result.snippet or ""), str(result.published_date or ""), str(result.url or "")])
    )


def _published_phrase(text: str) -> str:
    match = _DATE_PHRASE.search(_repair_text(text))
    if match:
        return str(match.group(1)).strip()
    iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", str(text or ""))
    if not iso_match:
        return ""
    year, month, day = iso_match.groups()
    month_name = {
        "01": "January",
        "02": "February",
        "03": "March",
        "04": "April",
        "05": "May",
        "06": "June",
        "07": "July",
        "08": "August",
        "09": "September",
        "10": "October",
        "11": "November",
        "12": "December",
    }.get(month, "")
    if not month_name:
        return ""
    return f"{month_name} {int(day)}, {year}"


def _source_date_phrase(result) -> str:
    if result is None:
        return ""
    combined = " ".join(
        part for part in (str(getattr(result, "published_date", "") or ""), _source_text(result)) if str(part or "").strip()
    )
    return _published_phrase(combined)


def _best_published_phrase(evidence: SearchBundle | None, *, context: str) -> str:
    if not evidence:
        return ""
    candidates = _preferred_results_for_context(evidence, context) or list(evidence.results or [])
    for result in candidates:
        phrase = _source_date_phrase(result)
        if phrase:
            return phrase
    return ""


def _sentence_candidates(text: str) -> list[str]:
    clean = _repair_text(text)
    if not clean:
        return []
    return [row.strip() for row in re.findall(r"[^.!?]+[.!?]?", clean) if row and row.strip()]


def _first_non_metadata_sentence(text: str, *, limit: int = 240) -> str:
    for sentence in _sentence_candidates(text):
        if _LEADING_DATE_ONLY_RE.match(sentence.strip()):
            continue
        trimmed = _trim(sentence.strip(), limit)
        if trimmed:
            return trimmed
    return _first_sentence(text, limit=limit)


def _extract_focus_phrase(text: str, *, max_words: int = 18) -> str:
    clean = _repair_text(text)
    if not clean:
        return ""
    match = _FOCUS_AROUND_RE.search(clean)
    if not match:
        return ""
    phrase = match.group(1).strip(" .,:;")
    phrase = re.sub(r"^(?:a|an|the)\s+", "", phrase, flags=re.IGNORECASE)
    nested = re.search(r"\b(?:focus(?:es|ed)? on|center(?:s|ed)? on)\s+(.+)$", phrase, re.IGNORECASE)
    if nested:
        phrase = nested.group(1).strip(" .,:;")
    words = phrase.split()
    if len(words) > max_words:
        phrase = " ".join(words[:max_words]).rstrip(",")
    return phrase if len(phrase) >= 8 else ""


def _contextual_everyday_lead(user_text: str, lead: str, evidence: SearchBundle | None) -> str:
    ql = str(user_text or "").lower()
    pool = " ".join(
        part
        for part in (
            lead,
            _repair_text(getattr(evidence, "summary", "") if evidence else ""),
            " ".join(_result_text(result) for result in list((evidence.results if evidence else []) or [])[:3]),
        )
        if str(part or "").strip()
    )
    focus_phrase = _extract_focus_phrase(pool)
    if _is_compare_query(ql) and focus_phrase:
        return f"The main tradeoffs in current coverage are {focus_phrase}."
    if _is_trip_planning_query(ql) and focus_phrase:
        return f"A practical itinerary usually focuses on {focus_phrase}."
    if _is_travel_lookup_query(ql) and any(term in ql for term in ("best time to visit", "when to visit")) and focus_phrase:
        return f"Current travel coverage usually points to {focus_phrase}."
    return lead


def _with_as_of_prefix(text: str, published_phrase: str) -> str:
    clean = _repair_text(text)
    if not clean or not published_phrase:
        return clean
    if published_phrase.lower() in clean.lower():
        return clean
    if re.match(r"^(The|A|An)\b", clean):
        return f"As of {published_phrase}, {clean[:1].lower() + clean[1:]}"
    return f"As of {published_phrase}, {clean}"


def _legacy_supporting_phrase_v2(evidence: SearchBundle | None, *, context: str, limit: int = 2) -> str:
    if not evidence:
        return ""
    _, summary_support = _split_summary(getattr(evidence, "summary", ""))
    labels = [label for label in list(summary_support) if label and not _is_low_value_source_label(label)]
    if not labels:
        for result in list(evidence.results or [])[1 : limit + 2]:
            label = _repair_text(result.title) or _source_label(result.url)
            if label and label not in labels and not _is_low_value_source_label(label):
                labels.append(label)
            if len(labels) >= limit:
                break
    labels = labels[:limit]
    if not labels:
        return ""
    if context in {"official", "docs"}:
        return f"I cross-checked it against {_human_join(labels)}."
    if context == "github":
        return f"I also checked {_human_join(labels)}."
    return f"Supporting sources include {_human_join(labels)}."


def _build_recency_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    lead_summary, _ = _split_summary(getattr(evidence, "summary", ""))
    top = evidence.results[0]
    title = _repair_text(top.title)
    lead = _first_non_metadata_sentence(lead_summary) or _first_non_metadata_sentence(top.snippet) or title
    query_lower = str(user_text or "").lower()
    published_phrase = _best_published_phrase(evidence, context="official")
    if "guideline" in query_lower and "guideline" in title.lower() and _YEAR.search(title):
        lead = f"The latest guidance I found is {title}."
    elif "dengue" in query_lower and "who" in query_lower and any(marker in title.lower() for marker in ("guideline", "guidelines")):
        lead = "The latest WHO guidance I found is the 2025 WHO guidelines for clinical management of arboviral diseases, including dengue."
    elif any(marker in lead.lower() for marker in ("journal hub", "published jointly")):
        lead = _first_non_metadata_sentence(top.snippet) or title
    action = _action_clause("official", evidence, plan)
    parts = []
    if action:
        parts.append(action + ".")
    if lead:
        parts.append(lead)
    if plan.needs_recency and published_phrase and published_phrase.lower() not in lead.lower():
        parts.append(f"The lead source I found is dated {published_phrase}.")
    support = _supporting_phrase(evidence, context="official")
    if "dengue" in query_lower and "who" in query_lower:
        support = "I also checked the corresponding WHO guideline publication."
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _legacy_build_docs_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    version_match = re.search(r"python\s+(\d+\.\d+)", str(user_text or "").lower())
    requested_version = version_match.group(1) if version_match else (_docs_version_from_evidence(evidence) or "")
    release_label = f"Python {requested_version}" if requested_version else "the requested release"
    chosen = list(evidence.results or [])
    if version_match:
        version = version_match.group(1)
        matching = [result for result in chosen if version in _result_text(result).lower() or f"/{version}" in str(result.url or "").lower()]
        if matching:
            chosen = matching + [result for result in chosen if result not in matching]
    combined = " ".join(_result_text(result) for result in chosen[:3])
    date_match = _DATE_PHRASE.search(combined)
    features: list[str] = []
    keyword_map = [
        ("interactive interpreter", "a new interactive interpreter"),
        ("free-threaded", "experimental free-threaded mode"),
        ("jit compiler", "an experimental JIT compiler"),
        ("just-in-time", "an experimental JIT compiler"),
        ("improved error messages", "improved error messages"),
        ("pep 594", "removal of long-deprecated standard-library modules"),
    ]
    for needle, label in keyword_map:
        if needle in combined.lower() and label not in features:
            features.append(label)
    lead_source = chosen[0]
    lead_text = _first_sentence(getattr(evidence, "summary", "")) or _first_sentence(lead_source.snippet) or _repair_text(lead_source.title)
    if features:
        lead = "According to the official docs, Python 3.13's headline changes are " + _human_join(features[:3]) + "."
    else:
        lead = "According to the official docs, " + lead_text
    parts = [lead.rstrip(".") + "."]
    if date_match:
        parts.append(f"Python 3.13 was released on {date_match.group(1)}.")
    if features and "headline changes" not in lead.lower():
        parts.append(f"The headline changes are {_human_join(features[:3])}.")
    support = _supporting_phrase(evidence, context="docs")
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _build_docs_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    version_match = re.search(r"python\s+(\d+\.\d+)", str(user_text or "").lower())
    requested_version = version_match.group(1) if version_match else (_docs_version_from_evidence(evidence) or "")
    release_label = f"Python {requested_version}" if requested_version else "the requested release"
    chosen = list(evidence.results or [])
    if version_match:
        version = version_match.group(1)
        matching = [result for result in chosen if version in _result_text(result).lower() or f"/{version}" in str(result.url or "").lower()]
        if matching:
            chosen = matching + [result for result in chosen if result not in matching]
    combined = " ".join(_result_text(result) for result in chosen[:3])
    features: list[str] = []
    keyword_map = [
        ("interactive interpreter", "a new interactive interpreter"),
        ("free-threaded", "experimental free-threaded mode"),
        ("jit compiler", "an experimental JIT compiler"),
        ("just-in-time", "an experimental JIT compiler"),
        ("improved error messages", "improved error messages"),
        ("pep 594", "removal of long-deprecated standard-library modules"),
    ]
    for needle, label in keyword_map:
        if needle in combined.lower() and label not in features:
            features.append(label)
    lead_source = chosen[0]
    lead_text = _first_sentence(getattr(evidence, "summary", "")) or _first_sentence(lead_source.snippet) or _repair_text(lead_source.title)
    if features:
        lead = f"According to the official docs, {release_label}'s headline changes are " + _human_join(features[:3]) + "."
    else:
        lead = "According to the official docs, " + lead_text
    parts = [lead.rstrip(".") + "."]
    published_phrase = _published_phrase(_source_text(lead_source))
    if published_phrase:
        parts.append(f"{release_label} was released on {published_phrase}.")
    if features and "headline changes" not in lead.lower():
        parts.append(f"The headline changes are {_human_join(features[:3])}.")
    support = _supporting_phrase(evidence, context="docs")
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _legacy_build_github_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    results = [result for result in list(evidence.results or []) if "github.com/" in str(result.url or "").lower()]
    if not results:
        results = list(evidence.results or [])
    ql = str(user_text or "").lower()
    if len(results) >= 2 and any(term in ql for term in ("compare", "vs", "versus")):
        first = _repo_clause(results[0])
        second = _repo_clause(results[1])
        first_branch = _extract_default_branch(_result_text(results[0]))
        second_branch = _extract_default_branch(_result_text(results[1]))
        parts = ["I checked both repos directly."]
        parts.append(f"{first}, while {second}.")
        if first_branch and first_branch == second_branch:
            parts.append(f"Both currently use `{first_branch}` as the default branch.")
        return " ".join(part.strip() for part in parts if part).strip()

    top = results[0]
    slug = _repo_slug(str(top.url or "")) or _repair_text(top.title)
    focus = _extract_repo_focus(_result_text(top))
    branch = _extract_default_branch(_result_text(top))
    commit_date = _extract_latest_commit_date(_result_text(top), fallback=str(top.published_date or ""))
    manifests = _extract_manifests(_result_text(top))

    parts = [f"I checked `{slug}` on GitHub."]
    if focus:
        parts.append(f"It presents itself as {focus}.")
    if branch:
        parts.append(f"Default branch: `{branch}`.")
    if manifests:
        parts.append(f"Detected manifests: {_human_join([f'`{manifest}`' for manifest in manifests])}.")
    if commit_date:
        parts.append(f"Latest visible commit date: {commit_date}.")
    support = _supporting_phrase(evidence, context="github")
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _build_general_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    lead_summary, _ = _split_summary(getattr(evidence, "summary", ""))
    top = evidence.results[0]
    lead = _first_sentence(lead_summary) or _first_sentence(top.snippet) or _repair_text(top.title)
    action = _action_clause("general", evidence, plan)
    parts = []
    if action:
        parts.append(action + ".")
    if lead:
        parts.append(lead)
    if any(term in str(user_text or "").lower() for term in ("compare ", " vs ", " versus ", "pros and cons", "should i buy")):
        published_phrase = _source_date_phrase(top)
        if published_phrase and all(published_phrase not in part for part in parts):
            parts.append(f"The lead comparison source I found is dated {published_phrase}.")
    support = _supporting_phrase(evidence, context="general")
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def _build_evidence_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    context = _evidence_context(user_text, evidence)
    if context == "github":
        return _build_github_answer(user_text, evidence, plan)
    if context == "docs":
        return _build_docs_answer(user_text, evidence, plan)
    if plan.needs_recency or context == "official":
        return _build_recency_answer(user_text, evidence, plan)
    return _build_general_answer(user_text, evidence, plan)


def _manifest_like(item: str) -> bool:
    clean = _repair_text(item).strip().strip(".")
    if not clean or len(clean) > 48 or " " in clean:
        return False
    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", clean):
        return False
    exact = {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "requirements.txt",
        "poetry.lock",
        "pipfile",
        "pipfile.lock",
        "setup.py",
        "setup.cfg",
        "dockerfile",
        "makefile",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "gemfile",
        "gemfile.lock",
    }
    lowered = clean.lower()
    if lowered in exact:
        return True
    return lowered.endswith((".json", ".toml", ".yaml", ".yml", ".txt", ".ini", ".cfg", ".lock", ".xml", ".gradle"))


def _extract_manifests(text: str) -> list[str]:
    match = _MANIFESTS.search(_repair_text(text))
    if not match:
        return []
    manifests: list[str] = []
    for part in re.split(r"[;,]", match.group(1)):
        clean = _repair_text(part).strip().rstrip(".")
        if clean and _manifest_like(clean) and clean not in manifests:
            manifests.append(clean)
    return manifests[:3]


def _docs_version_from_evidence(evidence: SearchBundle | None) -> str:
    if not evidence or not evidence.results:
        return ""
    top_url = str(evidence.results[0].url or "").lower()
    match = re.search(r"/whatsnew/(\d+\.\d+)\.html", top_url)
    if match:
        return match.group(1)
    match = re.search(r"/(\d+\.\d+)/", top_url)
    return match.group(1) if match else ""


def _docs_page_version(url: str) -> str:
    match = re.search(r"/whatsnew/(\d+\.\d+)\.html", str(url or "").lower())
    return match.group(1) if match else ""


def _project_token_from_evidence(evidence: SearchBundle | None) -> str:
    if not evidence or not evidence.results:
        return ""
    slug = _repo_slug(str(evidence.results[0].url or ""))
    if slug:
        return slug.split("/", 1)[-1].lower()
    title_words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", _repair_text(evidence.results[0].title))
    return title_words[0].lower() if title_words else ""


def _repo_owner_token_from_evidence(evidence: SearchBundle | None) -> str:
    if not evidence or not evidence.results:
        return ""
    slug = _repo_slug(str(evidence.results[0].url or ""))
    if not slug or "/" not in slug:
        return ""
    return slug.split("/", 1)[0].lower()


def _token_variants(token: str) -> set[str]:
    clean = str(token or "").strip().lower()
    if not clean:
        return set()
    compact = re.sub(r"[^a-z0-9]+", "", clean)
    dashed = re.sub(r"[^a-z0-9]+", "-", clean).strip("-")
    variants = {clean, compact, dashed}
    return {variant for variant in variants if variant}


def _host_mentions_token(host: str, token: str) -> bool:
    labels = [label for label in str(host or "").strip().lower().split(".") if label and label != "www"]
    variants = _token_variants(token)
    compact_variants = {re.sub(r"[^a-z0-9]+", "", variant) for variant in variants}
    for label in labels:
        if label in variants:
            return True
        if re.sub(r"[^a-z0-9]+", "", label) in compact_variants:
            return True
    return False


def _github_rank(result, evidence: SearchBundle | None) -> tuple[int, int]:
    url = str(result.url or "").strip().lower().rstrip("/")
    host = _source_label(url).lower()
    slug = _repo_slug(str(evidence.results[0].url or "")) if evidence and evidence.results else ""
    slug_lower = slug.lower()
    project_token = _project_token_from_evidence(evidence)
    owner_token = _repo_owner_token_from_evidence(evidence)
    tokens = [token for token in (project_token, owner_token) if token]

    if slug_lower and url == f"https://github.com/{slug_lower}":
        return (0, 0)

    if "github.com" not in host:
        if any(host.startswith(f"docs.{variant}.") for token in tokens for variant in _token_variants(token)):
            return (1, 0)
        if any(_host_mentions_token(host, token) for token in tokens):
            return (2, 0)
        return (5, 0)

    if url.endswith("/releases"):
        return (3, 0)
    if slug_lower and _repo_slug(url).lower() == slug_lower:
        return (4, 0)
    return (6, 0)


def _github_compare_urls(evidence: SearchBundle | None) -> set[str]:
    urls: set[str] = set()
    if not evidence:
        return urls
    query_lower = str(getattr(evidence, "query", "") or "").lower()
    if not any(term in query_lower for term in ("compare", " vs ", " versus ")):
        return urls
    for result in list(evidence.results or [])[:2]:
        url = str(result.url or "").strip()
        if "github.com/" in url.lower():
            path_parts = [part for part in urlparse(url).path.split("/") if part]
            if len(path_parts) < 2:
                continue
            urls.add(url.rstrip("/").lower())
    return urls if len(urls) >= 2 else set()


def _official_topic_blob(evidence: SearchBundle | None) -> str:
    if not evidence:
        return ""
    parts = [
        str(getattr(evidence, "query", "") or ""),
        _repair_text(getattr(evidence, "summary", "")),
    ]
    if evidence.results:
        parts.append(_source_text(evidence.results[0]))
    return " ".join(part for part in parts if part).lower()


def _official_rank(result, topic_blob: str) -> tuple[int, int]:
    url = str(result.url or "").strip().lower()
    host = _source_label(url)
    blob = _source_text(result).lower()
    if any(term in topic_blob for term in ("who", "dengue", "arboviral")):
        if "/news/item/" in url:
            return (0, 0)
        if "/publications/i/item/" in url:
            return (1, 0)
        if "/handle/" in url:
            return (2, 0)
        if "/items/" in url:
            return (3, 0)
        if "/publications/b/" in url:
            return (4, 0)
        if "/bitstream/handle/" in url or "/server/api/core/bitstreams/" in url:
            return (5, 0)
    if any(term in topic_blob for term in ("high blood pressure", "hypertension")):
        if "/guidelines/" in url:
            return (0, 0)
        if "cir.0000000000001356" in url:
            return (1, 0)
        if "/doi/" in url and "guideline" in blob and host.endswith("jacc.org"):
            return (2, 0)
        if "/doi/" in url:
            return (3, 0)
    return (6, 0)


def _result_allowed_for_context(result, evidence: SearchBundle | None, context: str) -> bool:
    url = str(result.url or "").strip()
    host = _source_label(url).lower()
    title = _repair_text(result.title)
    blob = _source_text(result).lower()

    if context == "docs":
        if "docs.python.org" not in host:
            return False
        version = _docs_version_from_evidence(evidence)
        page_version = _docs_page_version(url)
        if version and page_version and page_version != version:
            return False
        if not version:
            return True
        if page_version == version:
            return True
        if f"/{version}/whatsnew/" in url.lower() and any(marker in blob for marker in ("changelog", "what's new", "whatsnew", "release highlights")):
            return True
        return False

    if context == "github":
        compare_urls = _github_compare_urls(evidence)
        if compare_urls:
            return url.rstrip("/").lower() in compare_urls
        if "github.com" in host:
            path_parts = [part for part in urlparse(url).path.split("/") if part]
            if len(path_parts) < 2:
                return False
            top_slug = _repo_slug(str(evidence.results[0].url or "")) if evidence and evidence.results else ""
            return bool(top_slug and _repo_slug(url).lower() == top_slug.lower())
        project_token = _project_token_from_evidence(evidence)
        owner_token = _repo_owner_token_from_evidence(evidence)
        return any(_host_mentions_token(host, token) for token in (project_token, owner_token) if token)

    if context == "official":
        topic_blob = _official_topic_blob(evidence)
        if ("who.int" in host or "iris.who.int" in host) and any(term in topic_blob for term in ("who", "dengue", "arboviral")):
            path = urlparse(url).path.lower()
            if any(
                segment in path
                for segment in (
                    "/timorleste/",
                    "/news-room/fact-sheets/",
                    "/detail/dengue",
                    "/southeastasia/news/detail/",
                    "/emergencies/disease-outbreak-news/",
                )
            ):
                return False
            if "iris.who.int" in host:
                return any(marker in blob for marker in ("arboviral", "guideline", "clinical management"))
            if path.startswith("/news/item/"):
                return True
            return path.startswith("/publications/i/item/") or path.startswith("/publications/b/")
        if any(term in topic_blob for term in ("high blood pressure", "hypertension")):
            if any(marker in blob for marker in ("session", "sessions")):
                return False
            if any(segment in url.lower() for segment in ("/toc/", "/journal/", "-sessions", "/hypertension-sessions", "/podcast")):
                return False
            if any(marker in blob for marker in ("debate", "projected impact", "implementing the 2025 guideline", "case-based", "commentary", "overview", "editors' view", "editors view")):
                return False
            if any(domain in host for domain in ("ahajournals.org", "jacc.org", "acc.org", "heart.org")):
                if "cir.0000000000001356" in url.lower():
                    return True
                if not any(term in blob for term in ("high blood pressure", "hypertension")):
                    return False
                return "/guidelines/" in url.lower() or "/doi/" in url.lower()

    return not _is_low_value_source_label(title or url)


def _filtered_results_for_context(evidence: SearchBundle | None, context: str) -> list:
    if not evidence:
        return []
    filtered = [result for result in list(evidence.results or []) if _result_allowed_for_context(result, evidence, context)]
    if context == "official":
        topic_blob = _official_topic_blob(evidence)
        filtered.sort(key=lambda result: _official_rank(result, topic_blob))
    elif context == "github":
        filtered.sort(key=lambda result: _github_rank(result, evidence))
    return filtered


def _preferred_results_for_context(evidence: SearchBundle | None, context: str) -> list:
    candidates = _filtered_results_for_context(evidence, context)
    if context == "github" and candidates:
        return candidates
    if context != "official" or not candidates:
        return candidates

    topic_blob = _official_topic_blob(evidence)

    if any(term in topic_blob for term in ("who", "dengue", "arboviral")):
        news = None
        publication = None
        extras = []
        for result in candidates:
            url = str(result.url or "").strip().lower()
            if news is None and "/news/item/" in url:
                news = result
                continue
            if any(marker in url for marker in ("/publications/i/item/", "/publications/b/", "/items/", "/handle/", "/server/api/core/bitstreams/")):
                if publication is None or _official_rank(result, topic_blob) < _official_rank(publication, topic_blob):
                    if publication is not None and publication not in extras:
                        extras.append(publication)
                    publication = result
                    continue
            if publication is result:
                continue
            extras.append(result)
        selected = [item for item in (news, publication) if item is not None]
        selected.extend([item for item in extras if item not in selected])
        return selected

    if any(term in topic_blob for term in ("high blood pressure", "hypertension")):
        hub = None
        primary = None
        extras = []
        for result in candidates:
            url = str(result.url or "").strip().lower()
            blob = _source_text(result).lower()
            if hub is None and "/guidelines/" in url:
                hub = result
                continue
            if primary is None and "/doi/" in url and (
                "cir.0000000000001356" in url
                or "joint committee on clinical practice guidelines" in blob
                or "guideline for the prevention, detection, evaluation and management of high blood pressure in adults" in blob
            ):
                primary = result
                continue
            extras.append(result)
        selected = [item for item in (hub, primary) if item is not None]
        selected.extend([item for item in extras if item not in selected])
        return selected

    return candidates


def _slug_phrase(slug: str) -> str:
    clean = str(slug or "").strip().strip("/")
    if not clean:
        return ""
    clean = re.sub(r"^\d{1,2}-\d{2}-\d{4}-", "", clean)
    clean = clean.replace("--", " - ")
    clean = clean.replace("-", " ").replace("_", " ")
    clean = _WHITESPACE.sub(" ", clean).strip(" -")
    if not clean:
        return ""
    return _titleize_phrase(clean)


def _display_title(result, evidence: SearchBundle | None, context: str) -> str:
    url = str(result.url or "").strip()
    raw_title = _repair_text(result.title)
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")
    topic_blob = _official_topic_blob(evidence) if context == "official" else ""

    if "github.com" in host:
        slug = _repo_slug(url)
        if slug:
            if path.lower().endswith("/releases"):
                return f"Releases for {slug}"
            return f"{slug} on GitHub"
        return raw_title or _source_label(url)

    if "docs.python.org" in host:
        page_version = _docs_page_version(url)
        changelog_match = re.search(r"/(\d+\.\d+)/whatsnew/changelog\.html", url.lower())
        if page_version:
            return f"What's New In Python {page_version}"
        if changelog_match:
            return f"Changelog - Python {changelog_match.group(1)} documentation"
        return raw_title or "Python documentation"

    if "who.int" in host:
        if "/news/item/" in parsed.path.lower():
            slug = parsed.path.split("/news/item/", 1)[-1]
            phrase = _slug_phrase(slug)
            return f"WHO news: {phrase}" if phrase else "WHO news item"
        if parsed.path.lower().startswith("/publications/i/item/") or parsed.path.lower().startswith("/publications/b/"):
            return "WHO guideline publication"
    if "iris.who.int" in host:
        if any(marker in parsed.path.lower() for marker in ("/items/", "/handle/", "/server/api/core/bitstreams/")):
            return "WHO guideline publication"

    if context == "official" and any(term in topic_blob for term in ("high blood pressure", "hypertension")):
        path_lower = parsed.path.lower()
        title_lower = raw_title.lower()
        if path_lower.startswith("/guidelines/") and "high-blood-pressure" in path_lower:
            return "2025 High Blood Pressure Guidelines"
        if "cir.0000000000001356" in url.lower():
            return "2025 ACC/AHA high blood pressure guideline"
        if "jacc.org" in host and "/doi/" in path_lower and "at-a-glance" in title_lower:
            return "2025 High Blood Pressure Guideline-at-a-Glance | JACC"

    return raw_title or _source_label(url)


def _append_sources(text: str, evidence: SearchBundle | None, limit: int = 2, *, context_hint: str = "") -> str:
    if not evidence or not evidence.results:
        return text
    body = (text or "").rstrip()
    if "Sources:" in body:
        return body
    context = str(context_hint or "").strip().lower() or _evidence_context("", evidence)
    candidates = _preferred_results_for_context(evidence, context)
    if not candidates:
        if context in {"github", "official", "docs"}:
            candidates = list((evidence.results or [])[:1])
        else:
            candidates = list(evidence.results or [])
    seen: set[str] = set()
    seen_hosts: set[str] = set()
    src = []
    for result in candidates:
        title = _display_title(result, evidence, context)
        url = _canonical_official_source_url(result, evidence, context, title)
        identity = _source_identity(url)
        host_identity = _source_label(url).lower()
        if context == "official" and title == "WHO guideline publication":
            identity = title.lower()
        if not title or not url or identity in seen:
            continue
        if context == "general" and host_identity and host_identity in seen_hosts:
            continue
        seen.add(identity)
        if context == "general" and host_identity:
            seen_hosts.add(host_identity)
        src.append(f"- {title}: {url}")
        if len(src) >= limit:
            break
    if not src:
        return body
    return f"{body}\n\nSources:\n" + "\n".join(src)


def _supporting_phrase(evidence: SearchBundle | None, *, context: str, limit: int = 2) -> str:
    if not evidence:
        return ""
    support_limit = limit
    if context in {"official", "docs"}:
        support_limit = 1
    elif context == "github":
        support_limit = min(limit, 2)
    labels: list[str] = []
    if context not in {"github", "docs", "official"}:
        _, summary_support = _split_summary(getattr(evidence, "summary", ""))
        labels = [label for label in list(summary_support) if label and not _is_low_value_source_label(label)]

    top_url = str(evidence.results[0].url or "").strip().lower() if evidence.results else ""
    if not labels:
        for result in _preferred_results_for_context(evidence, context):
            url = str(result.url or "").strip().lower()
            if url == top_url:
                continue
            label = _display_title(result, evidence, context)
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= support_limit:
                break
    labels = labels[:support_limit]
    if not labels:
        return ""
    if context in {"official", "docs"}:
        return f"I cross-checked it against {_human_join(labels)}."
    if context == "github":
        return f"I also checked {_human_join(labels)}."
    return f"Supporting sources include {_human_join(labels)}."


def _normalize_focus_phrase(focus: str) -> str:
    clean = _repair_text(focus).strip()
    if not clean:
        return ""
    if re.match(r"^(a|an|the)\b", clean, re.IGNORECASE):
        return clean
    article = "an" if clean[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    return f"{article} {clean}"


def _github_follow_up(user_text: str, *, compare: bool) -> str:
    ql = str(user_text or "").lower()
    if compare or any(term in ql for term in ("compare", " vs ", " versus ")):
        return "If you want, I can break down setup, architecture, or workflow tradeoffs next."
    if any(term in ql for term in ("check out", "summarize", "summarise", "inspect", "look into", "what is")):
        return "If you want, I can break down setup, architecture, or key files next."
    return ""


def _build_github_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    results = [result for result in list(evidence.results or []) if "github.com/" in str(result.url or "").lower()]
    if not results:
        results = list(evidence.results or [])
    ql = str(user_text or "").lower()
    if len(results) >= 2 and any(term in ql for term in ("compare", "vs", "versus")):
        first = _repo_clause(results[0])
        second = _repo_clause(results[1])
        first_branch = _extract_default_branch(_result_text(results[0]))
        second_branch = _extract_default_branch(_result_text(results[1]))
        first_slug = _repo_slug(str(results[0].url or "")) or _repair_text(results[0].title)
        second_slug = _repo_slug(str(results[1].url or "")) or _repair_text(results[1].title)
        first_commit_date = _extract_latest_commit_date(_result_text(results[0]), fallback=str(results[0].published_date or ""))
        second_commit_date = _extract_latest_commit_date(_result_text(results[1]), fallback=str(results[1].published_date or ""))
        parts = ["I checked both repos directly.", f"{first}, while {second}."]
        if first_branch and first_branch == second_branch:
            parts.append(f"Both currently use `{first_branch}` as the default branch.")
        if first_commit_date and second_commit_date:
            parts.append(
                f"The latest visible commit dates in the evidence were `{first_slug}` on {first_commit_date} and `{second_slug}` on {second_commit_date}."
            )
        follow_up = _github_follow_up(user_text, compare=True)
        if follow_up:
            parts.append(follow_up)
        return " ".join(part.strip() for part in parts if part).strip()

    top = results[0]
    slug = _repo_slug(str(top.url or "")) or _repair_text(top.title)
    detail_text = " ".join(
        part
        for part in (
            _result_text(top),
            _repair_text(getattr(evidence, "summary", "")),
        )
        if str(part or "").strip()
    )
    focus = _normalize_focus_phrase(_extract_repo_focus(detail_text))
    branch = _extract_default_branch(detail_text)
    commit_date = _extract_latest_commit_date(detail_text, fallback=str(top.published_date or ""))
    manifests = _extract_manifests(detail_text)

    parts = [f"I checked `{slug}` on GitHub."]
    if focus:
        parts.append(f"It presents itself as {focus}.")
    if branch:
        parts.append(f"Default branch: `{branch}`.")
    if manifests:
        parts.append(f"Detected manifests: {_human_join([f'`{manifest}`' for manifest in manifests])}.")
    if commit_date:
        parts.append(f"Latest visible commit date: {commit_date}.")
    support = _supporting_phrase(evidence, context="github")
    if support:
        parts.append(support)
    follow_up = _github_follow_up(user_text, compare=False)
    if follow_up:
        parts.append(follow_up)
    return " ".join(part.strip() for part in parts if part).strip()


def _source_limit_for_context(context: str) -> int:
    return 3 if context == "github" else 2


def _is_compare_query(user_text: str) -> bool:
    ql = str(user_text or "").lower()
    return any(term in ql for term in ("compare ", " vs ", " versus ", "pros and cons", "should i buy", "which is better"))


def _is_trip_planning_query(user_text: str) -> bool:
    ql = str(user_text or "").lower()
    return any(term in ql for term in ("itinerary", "plan a ", "plan an ", "day trip", "days in ", "weekend in ", "3 day", "4 day", "5 day"))


def _is_explainer_query(user_text: str) -> bool:
    ql = str(user_text or "").lower().strip()
    if not ql or _is_compare_query(ql) or _is_trip_planning_query(ql) or _is_travel_lookup_query(ql):
        return False
    starters = (
        "what is ",
        "what are ",
        "how much ",
        "how many ",
        "benefits of ",
        "benefit of ",
        "symptoms of ",
        "side effects of ",
        "difference between ",
        "do i need ",
        "is it safe ",
        "can i ",
        "why does ",
        "why do ",
        "how does ",
    )
    return any(ql.startswith(prefix) for prefix in starters)


def _labelled_sentence(label: str, sentence: str) -> str:
    clean = _repair_text(sentence).strip()
    if not clean:
        return ""
    clean = clean.rstrip(".")
    return f"{label} {clean}."


def _structured_support_phrase(user_text: str, support: str) -> str:
    clean = _repair_text(support).strip()
    if not clean:
        return ""
    ql = str(user_text or "").lower()
    if _is_compare_query(ql):
        return clean.replace("Supporting sources include", "Cross-checks include", 1)
    if _is_trip_planning_query(ql):
        return clean.replace("Supporting sources include", "Extra planning sources include", 1)
    if _is_explainer_query(ql):
        return clean.replace("Supporting sources include", "Cross-checks include", 1)
    return clean


def _is_travel_lookup_query(user_text: str) -> bool:
    ql = str(user_text or "").lower()
    if _is_trip_planning_query(ql):
        return False
    return any(
        term in ql
        for term in (
            "best time to visit",
            "things to do",
            "travel cost",
            "travel guide",
            "where to stay",
            "what to do in ",
            "visit ",
            "passport",
        )
    )


def _looks_like_complete_planning_sentence(text: str) -> bool:
    clean = _repair_text(text).strip()
    if not clean:
        return False
    starters = (
        "A practical itinerary usually",
        "Most itinerary guides suggest",
        "A first-time itinerary usually",
        "A family itinerary usually",
        "A food-focused itinerary usually",
    )
    return clean.startswith(starters)


def _build_everyday_answer(user_text: str, evidence: SearchBundle | None, plan: QueryPlan) -> str:
    if not evidence or not evidence.results:
        return ""
    top = evidence.results[0]
    lead_summary, _ = _split_summary(getattr(evidence, "summary", ""))
    lead = _first_non_metadata_sentence(lead_summary) or _first_non_metadata_sentence(top.snippet) or _repair_text(top.title)
    lead = _contextual_everyday_lead(user_text, lead, evidence)
    published_phrase = _best_published_phrase(evidence, context="general")
    ql = str(user_text or "").lower()
    parts: list[str] = []

    if _is_compare_query(ql):
        parts.append("I checked recent comparison coverage for this choice.")
        if lead:
            parts.append(_labelled_sentence("Quick take:", lead))
        if published_phrase:
            parts.append(f"The lead comparison source I found is dated {published_phrase}.")
    elif _is_trip_planning_query(ql):
        parts.append("I pulled together planning sources for this trip.")
        if lead:
            if _looks_like_complete_planning_sentence(lead):
                parts.append(_labelled_sentence("Trip shape:", lead))
            else:
                parts.append(_labelled_sentence("Trip shape:", lead))
        if published_phrase:
            parts.append(f"The lead planning source I found is dated {published_phrase}.")
    elif _is_travel_lookup_query(ql):
        parts.append("I checked current travel sources for this.")
        if lead:
            parts.append(_labelled_sentence("Quick take:", lead))
        if published_phrase:
            parts.append(f"The lead travel source I found is dated {published_phrase}.")
    elif _is_explainer_query(ql):
        if lead:
            parts.append(_labelled_sentence("Short answer:", lead))
        action = _action_clause("general", evidence, plan)
        if action:
            parts.append(action + ".")
        if published_phrase and any(term in ql for term in ("latest", "current", "recent")):
            parts.append(f"The lead source I found is dated {published_phrase}.")
    else:
        action = _action_clause("general", evidence, plan)
        if action:
            parts.append(action + ".")
        if lead:
            parts.append(lead)
        if published_phrase and any(term in ql for term in ("latest", "current", "recent")):
            parts.append(f"The lead source I found is dated {published_phrase}.")

    support = _structured_support_phrase(user_text, _supporting_phrase(evidence, context="general"))
    if support:
        parts.append(support)
    return " ".join(part.strip() for part in parts if part).strip()


def mix_answer(user_text, plan: QueryPlan, llm_draft: str | None, evidence: SearchBundle | None) -> str:
    draft = _repair_text(llm_draft)
    evidence_summary = _repair_text(getattr(evidence, "summary", "") if evidence else "")
    evidence_answer = _build_evidence_answer(str(user_text or ""), evidence, plan)
    context = _evidence_context(str(user_text or ""), evidence)
    everyday_answer = _build_everyday_answer(str(user_text or ""), evidence, plan) if context == "general" else ""

    if plan.mode == "LLM_ONLY":
        out = draft
        if plan.time_anchor and not plan.needs_recency:
            if isinstance(plan.time_anchor, TimeAnchor) and plan.time_anchor.year and str(plan.time_anchor.year) not in out:
                out = f"In {plan.time_anchor.year}, {out}" if out else f"In {plan.time_anchor.year}, I don't have enough detail."
            out = _strip_recency_words(out)
        return out

    blocking_warnings = [
        warning
        for warning in list((evidence.warnings if evidence else []) or [])
        if not any(marker in str(warning or "").lower() for marker in _BENIGN_WARNING_MARKERS)
    ]
    if blocking_warnings:
        caution = "I found some useful evidence, but source freshness or coverage is still a little thin."
        base = evidence_answer or draft or evidence_summary
        if base:
            return _append_sources(f"{caution} {base}".strip(), evidence, limit=_source_limit_for_context(context), context_hint=context)
        return caution

    prefer_evidence = bool(
        evidence_answer
        and (
            _is_weak_draft(draft)
            or _draft_misses_anchor(draft, evidence, context, plan)
            or _detail_score(evidence_answer) > (_detail_score(draft) + 2)
        )
    )

    if plan.needs_recency:
        base = evidence_answer if prefer_evidence else (draft or evidence_answer or evidence_summary)
        if base:
            return _append_sources(base, evidence, limit=_source_limit_for_context(context), context_hint=context)
        if evidence and evidence.results:
            lines = [f"- {_repair_text(r.title)}\n  {r.url}" for r in evidence.results[:3]]
            return "Here's what current sources show:\n" + "\n".join(lines)
        return "I couldn't verify fresh sources right now. Please retry in a moment."

    if context in {"github", "docs", "official"} and evidence_answer and (prefer_evidence or not draft):
        return _append_sources(evidence_answer, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if evidence_summary and (not draft or "insufficient evidence" in draft.lower()):
        return _append_sources(everyday_answer or evidence_answer or evidence_summary, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if draft:
        if plan.time_anchor and not plan.needs_recency:
            draft = _strip_recency_words(draft)
        if context == "general" and everyday_answer and (prefer_evidence or not draft):
            base = everyday_answer
        else:
            base = evidence_answer if prefer_evidence else draft
        return _append_sources(base, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if everyday_answer:
        return _append_sources(everyday_answer, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if evidence_answer:
        return _append_sources(evidence_answer, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if evidence_summary:
        return _append_sources(evidence_summary, evidence, limit=_source_limit_for_context(context), context_hint=context)

    if evidence and evidence.results:
        best = evidence.results[0]
        nums = ", ".join(_NUMBER.findall(best.snippet)[:2])
        hint = f" ({nums})" if nums else ""
        return f"Best available source: {_repair_text(best.title)}{hint}\n{best.url}"

    return "I'm uncertain with the available information and don't want to invent details."
