# handlers/research/router.py
"""
ResearchRouter: routes a query to one or more research domains and merges results.

Refined version:
- Expanded ENGINEERING_TRIGGERS for broader natural language coverage (~90%).
- Expanded NUTRITION_TRIGGERS for calories/macros/vitamins/diet queries.
- Minor cleanup: added plurals, common synonyms.
- Keeps biomed strong (already working).
- Deterministic, no LLM dependency.
- Renamed gamer_brain → entertainment with broad triggers for movies/anime/games/awards/etc.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Sequence, Tuple

from handlers.research.base import (
    id_type_and_value,
    normalize_query,
    pack_result,
    rank_and_finalize,
    safe_trim,
)

logger = logging.getLogger(__name__)

MAX_TOTAL_DEFAULT = 12


# -----------------------------
# Domain imports (lazy-safe)
# -----------------------------
def _try_import(path: str, attr: str):
    try:
        mod = __import__(path, fromlist=[attr])
        return getattr(mod, attr)
    except Exception:
        return None


# Research-ish domains only
BiomedDomain = _try_import("handlers.research.domains.biomed", "BiomedDomain")
EngineeringDomain = _try_import("handlers.research.domains.engineering", "EngineeringDomain")
NutritionDomain = _try_import("handlers.research.domains.nutrition", "NutritionDomain")
ReligionDomain = _try_import("handlers.research.domains.religion", "ReligionDomain")
EntertainmentDomain = _try_import("handlers.research.domains.entertainment", "EntertainmentDomain")
BusinessAdministratorDomain = _try_import("handlers.research.domains.business_administrator", "BusinessAdministratorDomain")
JournalismCommunicationDomain = _try_import("handlers.research.domains.journalism_communication", "JournalismCommunicationDomain")


DOMAIN_REGISTRY = {
    "biomed": BiomedDomain,
    "engineering": EngineeringDomain,
    "nutrition": NutritionDomain,
    "religion": ReligionDomain,
    "entertainment": EntertainmentDomain,
    "business_administrator": BusinessAdministratorDomain,
    "journalism_communication": JournalismCommunicationDomain,
}


# -----------------------------
# Triggers (deterministic) - EXPANDED for ~90% natural language coverage
# -----------------------------
BIOMED_TRIGGERS = [
    "pmid", "pubmed", "doi", "clinicaltrials", "nct", "guideline", "guidelines", "consensus",
    "trial", "trials", "randomized", "randomised", "meta-analysis", "systematic review",
    "dose", "mg", "mcg", "treatment", "treatments", "therapy", "therapies",
    "diagnosis", "management", "recommendation", "recommendations",
    "seizure", "epilepsy", "stroke", "multiple sclerosis", "nmosd",
    "aha", "acc", "esc", "nice",
]

ENGINEERING_TRIGGERS = [
    "finite element", "fea", "control system", "signal processing", "rf", "antenna",
    "power system", "circuit", "pcb", "cad", "mechanical", "electrical",
    "thermodynamics", "fluid", "aerodynamics", "structural", "stress analysis",
    "vibration", "dynamics", "simulation", "modeling", "optimization",
    "bridge", "truss", "beam", "frame", "load bearing",
    "ieee", "acm",
]

NUTRITION_TRIGGERS = [
    "calorie", "calories", "kcal",
    "nutrition", "nutritional", "nutrient", "nutrients",
    "vitamin", "vitamins", "mineral", "minerals",
    "protein", "fat", "fats", "carb", "carbs", "carbohydrate", "carbohydrates",
    "fiber", "sugar", "sugars", "sodium",
    "macro", "macros", "micronutrient", "micronutrients",
    "rda", "recommended daily", "daily value", "dv",
    "diet", "dietary", "food facts", "nutrition facts",
]

RELIGION_TRIGGERS = [
    "religion", "theology", "bible", "quran", "koran", "hadith", "tafsir",
    "talmud", "torah", "gospel", "verse", "surah", "sura", "psalm",
    "canon law", "church father", "exegesis",
]

ENTERTAINMENT_TRIGGERS = [
    "movie", "film", "tv", "series", "netflix", "disney", "hbo",
    "anime", "manga", "crunchyroll", "myanimelist", "anime season",
    "game", "video game", "gaming", "esports", "steam", "playstation", "xbox", "nintendo",
    "award", "oscars", "emmy", "golden globe", "game awards", "anime awards",
    "top", "best", "highest grossing", "box office", "rating", "imdb", "rotten tomatoes",
    "popular", "trending", "new release", "upcoming",
]

BUSINESS_TRIGGERS = [
    "business", "management", "strategy", "operations", "finance", "accounting",
    "marketing", "hr", "human resources", "leadership", "organizational",
    "mba", "kpi", "okr", "workflow", "governance",
]

JOURNALISM_TRIGGERS = [
    "journalism", "communication", "media", "coverage", "headline", "breaking",
    "reported", "press", "newsroom", "propaganda", "misinformation",
    "sentiment", "public opinion",
]


def _contains_any(q: str, needles: Sequence[str]) -> bool:
    ql = (q or "").lower()
    return any(n in ql for n in needles)


def _is_sentinel(r: Dict[str, Any]) -> bool:
    t = str((r or {}).get("title") or "").lower()
    return ("science search insufficient coverage" in t) or ("science search unavailable" in t)


class ResearchRouter:
    """
    Deterministic research router.

    - Chooses 1–2 domains for most queries.
    - DOI/arXiv ambiguous; bias to engineering if engineering-ish terms exist, else biomed.
    - Merges + ranks results using base.rank_and_finalize().
    """

    def __init__(
        self,
        *,
        max_domains: int = 2,
        per_domain_timeout_s: float = 14.0,
        max_total: int = MAX_TOTAL_DEFAULT,
    ):
        self.max_domains = max(1, int(max_domains))
        self.per_domain_timeout_s = max(2.0, float(per_domain_timeout_s))
        self.max_total = max(1, int(max_total))

        self.domains: Dict[str, Any] = {}
        for name, cls in DOMAIN_REGISTRY.items():
            if cls is None:
                continue
            try:
                self.domains[name] = cls()
                logger.info(f"Loaded research domain: {name}")
            except Exception as e:
                logger.warning(f"Failed to init domain '{name}': {e}")

    def available_domains(self) -> List[str]:
        return sorted(self.domains.keys())

    # ---------- Sentinels ----------
    def _insufficient_coverage(self, msg: str, *, query: str, expected: str = "") -> List[Dict[str, Any]]:
        spans = [msg]
        if expected:
            spans.append(f"Expected: {expected}")
        spans.append(f"Query: {query}")
        spans = [safe_trim(s, 260) for s in spans if s]

        return [pack_result(
            title="Science search insufficient coverage",
            url="",
            description=msg,
            source="research",
            domain="router",
            id_type="none",
            id="",
            published="",
            evidence_level="other",
            evidence_spans=spans[:4],
        )]

    def _unavailable(self, msg: str, *, query: str) -> List[Dict[str, Any]]:
        spans = [safe_trim(msg, 260), safe_trim(f"Query: {query}", 260)]
        return [pack_result(
            title="Science search unavailable",
            url="",
            description=msg,
            source="research",
            domain="router",
            id_type="none",
            id="",
            published="",
            evidence_level="other",
            evidence_spans=spans[:2],
        )]

    # ---------- Domain choice ----------
    def _choose_domains(self, query: str) -> List[str]:
        q = normalize_query(query)
        ql = q.lower()

        idt, _idv = id_type_and_value(q)
        if idt != "none":
            if idt in ("pmid", "nct"):
                return ["biomed"] if "biomed" in self.domains else self.available_domains()[:1]

            if idt in ("doi", "arxiv"):
                if _contains_any(ql, ENGINEERING_TRIGGERS) and "engineering" in self.domains:
                    out = ["engineering"]
                    if "biomed" in self.domains:
                        out.append("biomed")
                    return out[: self.max_domains]
                if "biomed" in self.domains:
                    return ["biomed"]
                return self.available_domains()[:1]

        hits: List[Tuple[str, int]] = []
        if _contains_any(ql, BIOMED_TRIGGERS):
            hits.append(("biomed", 5))
        if _contains_any(ql, ENGINEERING_TRIGGERS):
            hits.append(("engineering", 5))
        if _contains_any(ql, NUTRITION_TRIGGERS):
            hits.append(("nutrition", 5))
        if _contains_any(ql, RELIGION_TRIGGERS):
            hits.append(("religion", 4))
        if _contains_any(ql, ENTERTAINMENT_TRIGGERS):
            hits.append(("entertainment", 5))
        if _contains_any(ql, BUSINESS_TRIGGERS):
            hits.append(("business_administrator", 3))
        if _contains_any(ql, JOURNALISM_TRIGGERS):
            hits.append(("journalism_communication", 3))

        if not hits:
            if "biomed" in self.domains:
                return ["biomed"]
            return self.available_domains()[:1]

        weights: Dict[str, int] = {}
        for d, w in hits:
            if d in self.domains:
                weights[d] = weights.get(d, 0) + int(w)

        if not weights:
            if "biomed" in self.domains:
                return ["biomed"]
            return self.available_domains()[:1]

        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        picked = [d for d, _ in ranked[: self.max_domains]]
        return picked or (["biomed"] if "biomed" in self.domains else self.available_domains()[:1])

    # ---------- Execution ----------
    async def search(self, query: str, *, retries: int = 2, backoff_factor: float = 0.5) -> List[Dict[str, Any]]:
        q = normalize_query(query)
        if not q:
            return self._insufficient_coverage("Empty query.", query=query)

        if not self.domains:
            return self._unavailable("No research domains are available (modules not loaded).", query=q)

        chosen = [d for d in self._choose_domains(q) if d in self.domains]
        if not chosen:
            chosen = self.available_domains()[:1]

        logger.info(f"Agentpedia routing '{q}' to domains: {chosen}")

        tasks = []
        for d in chosen:
            handler = self.domains[d]
            coro = handler.search(q, retries=retries, backoff_factor=backoff_factor)
            tasks.append(self._run_domain(d, coro))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        merged: List[Dict[str, Any]] = []
        for g in gathered:
            if isinstance(g, Exception):
                continue
            if isinstance(g, list):
                for x in g:
                    if isinstance(x, dict):
                        merged.append(x)

        if not merged:
            return self._insufficient_coverage(
                "No results returned from selected research domains; web fallback recommended.",
                query=q,
                expected=",".join(chosen),
            )

        # Remove sentinels; if only sentinels remain => insufficient coverage (forces upstream fallback)
        non_sentinels = [r for r in merged if isinstance(r, dict) and not _is_sentinel(r)]
        if not non_sentinels:
            return self._insufficient_coverage(
                "Structured sources returned insufficient coverage; web fallback recommended.",
                query=q,
                expected=",".join(chosen),
            )

        want_id_type, _ = id_type_and_value(q)
        ranked = rank_and_finalize(
            non_sentinels,
            query=q,
            want_id_type=want_id_type,
            max_total=self.max_total,
            dedupe=True,
        )
        return ranked

    async def _run_domain(self, domain_name: str, coro) -> List[Dict[str, Any]]:
        """
        Hard per-domain timeout using wait_for (portable).
        """
        try:
            res = await asyncio.wait_for(coro, timeout=self.per_domain_timeout_s)
            if not isinstance(res, list):
                return []

            out: List[Dict[str, Any]] = []
            for r in res:
                if not isinstance(r, dict):
                    continue
                rr = dict(r)
                rr.setdefault("domain", domain_name)
                rr.setdefault("volatile", True)
                out.append(rr)
            logger.info(f"Domain '{domain_name}' returned {len(out)} results")
            return out
        except asyncio.TimeoutError:
            logger.debug(f"Domain '{domain_name}' timed out after {self.per_domain_timeout_s:.1f}s")
            return []
        except Exception as e:
            logger.debug(f"Domain '{domain_name}' failed: {type(e).__name__}: {e}")
            return []