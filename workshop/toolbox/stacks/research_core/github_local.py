from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Dict, Iterable, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse


_REPO_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
_LEADING_COMPARE_RE = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?(?:check out|look into|look up|summarize|summarise|research|analyze|analyse|compare)\s+",
    re.IGNORECASE,
)
_TRAILING_GITHUB_RE = re.compile(r"\s+(?:on|from|at)\s+github\s*$", re.IGNORECASE)
_COMPARE_SPLIT_RE = re.compile(r"\s+(?:and|vs\.?|versus)\s+", re.IGNORECASE)
_MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)
_RESERVED_GITHUB_OWNERS = {
    "about",
    "collections",
    "events",
    "features",
    "marketplace",
    "orgs",
    "organizations",
    "search",
    "settings",
    "site",
    "sponsors",
    "topics",
    "users",
}
_CANONICAL_REPOS = (
    ("bootstrap", "https://github.com/twbs/bootstrap", ("bootstrap",)),
    ("deer-flow", "https://github.com/bytedance/deer-flow", ("deer-flow", "deer flow", "deerflow")),
    ("django", "https://github.com/django/django", ("django",)),
    ("fastapi", "https://github.com/fastapi/fastapi", ("fastapi",)),
    ("langchain", "https://github.com/langchain-ai/langchain", ("langchain", "lang chain")),
    ("llama.cpp", "https://github.com/ggerganov/llama.cpp", ("llama.cpp", "llama cpp", "llamacpp")),
    ("next.js", "https://github.com/vercel/next.js", ("next.js", "nextjs")),
    ("openclaw", "https://github.com/openclaw/openclaw", ("openclaw",)),
    ("ollama", "https://github.com/ollama/ollama", ("ollama",)),
    ("openai-python", "https://github.com/openai/openai-python", ("openai-python", "openai python")),
    ("pandas", "https://github.com/pandas-dev/pandas", ("pandas",)),
    ("playwright", "https://github.com/microsoft/playwright", ("playwright",)),
    ("httpx", "https://github.com/encode/httpx", ("httpx",)),
    ("pytorch", "https://github.com/pytorch/pytorch", ("pytorch",)),
    ("react", "https://github.com/facebook/react", ("react",)),
    ("requests", "https://github.com/psf/requests", ("requests",)),
    ("selenium", "https://github.com/SeleniumHQ/selenium", ("selenium",)),
    ("tailwindcss", "https://github.com/tailwindlabs/tailwindcss", ("tailwind css", "tailwindcss", "tailwind")),
    ("tensorflow", "https://github.com/tensorflow/tensorflow", ("tensorflow",)),
    ("typescript", "https://github.com/microsoft/TypeScript", ("typescript",)),
)
_SKIP_TAG_FETCH_SLUGS = {
    "facebook/react",
    "microsoft/typescript",
    "pytorch/pytorch",
    "tensorflow/tensorflow",
    "vercel/next.js",
}
_KNOWN_DEFAULT_BRANCHES = {
    "facebook/react": "main",
    "microsoft/typescript": "main",
    "pytorch/pytorch": "main",
    "tensorflow/tensorflow": "master",
    "vercel/next.js": "canary",
}


@dataclass
class GitHubInspection:
    repo_url: str
    repo_slug: str
    default_branch: str = ""
    latest_commit: str = ""
    readme_excerpt: str = ""
    top_level_entries: List[str] = field(default_factory=list)
    manifests: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    summary: str = ""
    inspection_method: str = "remote"


def _run_git(args: List[str], *, cwd: str | None = None, timeout_s: float = 20.0) -> str:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git command failed")
    return proc.stdout.strip()


def extract_repo_urls(text: str) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for owner, repo in _REPO_URL_RE.findall(str(text or "")):
        if owner.lower() in _RESERVED_GITHUB_OWNERS:
            continue
        url = f"https://github.com/{owner}/{repo}".rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _slug_tokens(text: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(tok) > 1}


def _comparison_subjects(query: str) -> List[str]:
    subject = " ".join(str(query or "").split()).strip()
    if not subject:
        return []
    subject = _LEADING_COMPARE_RE.sub("", subject)
    subject = re.sub(r"^(?:github\s+)?comparison\s+between\s+", "", subject, flags=re.IGNORECASE)
    subject = _TRAILING_GITHUB_RE.sub("", subject)
    parts = [part.strip(" ?!.") for part in _COMPARE_SPLIT_RE.split(subject) if part.strip(" ?!.")]
    return parts[:4]


def _canonical_repo_for_subject(subject: str) -> Optional[str]:
    normalized = " ".join(str(subject or "").split()).strip().lower()
    if not normalized:
        return None
    tokens = _slug_tokens(normalized)
    for _label, repo_url, hints in _CANONICAL_REPOS:
        for hint in hints:
            hint_norm = " ".join(str(hint or "").split()).strip().lower()
            if not hint_norm:
                continue
            if hint_norm in normalized:
                return repo_url
            hint_tokens = _slug_tokens(hint_norm)
            if hint_tokens and hint_tokens <= tokens:
                return repo_url
    return None


def _canonical_repo_candidates(query: str, *, limit: int) -> List[str]:
    subjects = _comparison_subjects(query) if limit > 1 else []
    ordered: List[str] = []
    seen: set[str] = set()
    if subjects:
        for subject in subjects:
            repo_url = _canonical_repo_for_subject(subject)
            if repo_url and repo_url not in seen:
                ordered.append(repo_url)
                seen.add(repo_url)
    repo_url = _canonical_repo_for_subject(query)
    if repo_url and repo_url not in seen:
        ordered.append(repo_url)
        seen.add(repo_url)
    return ordered[: max(1, limit)]


def _should_fetch_tags(repo_slug: str) -> bool:
    return str(repo_slug or "").strip().lower() not in _SKIP_TAG_FETCH_SLUGS


def guess_repo_urls(query: str) -> List[str]:
    q_tokens = [tok for tok in _slug_tokens(query) if tok not in {"github", "repo", "repository", "readme", "docs", "documentation"}]
    guesses: List[str] = []
    for token in q_tokens[:3]:
        if len(token) < 4:
            continue
        guesses.append(f"https://github.com/{token}/{token}")
    return guesses


def choose_best_repo(query: str, discovery_rows: Iterable[dict]) -> Optional[str]:
    repos = choose_repositories(query, discovery_rows, limit=1)
    return repos[0] if repos else None


def choose_repositories(query: str, discovery_rows: Iterable[dict], *, limit: int = 2) -> List[str]:
    direct = extract_repo_urls(query)
    if direct:
        return direct[: max(1, limit)]

    q_tokens = _slug_tokens(query)
    scored_candidates: Dict[str, float] = {}
    for rank, repo_url in enumerate(_canonical_repo_candidates(query, limit=max(1, limit)), start=1):
        scored_candidates[repo_url] = 100.0 - float(rank)
    for row in discovery_rows or []:
        url = str((row or {}).get("url") or "").strip()
        title = str((row or {}).get("title") or "").strip()
        candidates = extract_repo_urls(f"{url}\n{title}")
        for repo_url in candidates:
            parsed = urlparse(repo_url)
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) < 2:
                continue
            owner, repo = path_parts[:2]
            score = 0.0
            slug = f"{owner} {repo}".lower()
            title_tokens = _slug_tokens(title)
            score += len(q_tokens & _slug_tokens(slug)) * 3
            score += len(q_tokens & title_tokens) * 2
            if repo.lower() in str(query or "").lower():
                score += 4
            if owner.lower() in str(query or "").lower():
                score += 2
            if "/blob/" not in url and "/issues/" not in url and "/pull/" not in url:
                score += 1
            previous = scored_candidates.get(repo_url)
            if previous is None or score > previous:
                scored_candidates[repo_url] = score

    if scored_candidates:
        ranked = sorted(scored_candidates.items(), key=lambda item: item[1], reverse=True)
        compare_subjects = _comparison_subjects(query) if limit > 1 else []
        if len(compare_subjects) >= 2:
            chosen: List[str] = []
            used: set[str] = set()
            for subject in compare_subjects:
                normalized_subject = " ".join(str(subject or "").split()).strip().lower()
                subject_tokens = _slug_tokens(subject)
                if not normalized_subject and not subject_tokens:
                    continue
                for repo_url, _score in ranked:
                    if repo_url in used:
                        continue
                    parsed = urlparse(repo_url)
                    path_parts = [p for p in parsed.path.split("/") if p]
                    slug_text = " ".join(path_parts[:2]).lower()
                    slug_tokens = _slug_tokens(slug_text)
                    token_match = bool(subject_tokens & slug_tokens)
                    text_match = bool(normalized_subject) and (
                        normalized_subject in slug_text
                        or slug_text.replace(".", " ").replace("-", " ").replace("_", " ").find(normalized_subject) >= 0
                        or any(len(token) >= 4 and token in slug_text for token in subject_tokens)
                    )
                    if token_match or text_match:
                        chosen.append(repo_url)
                        used.add(repo_url)
                        break
            if chosen:
                for repo_url, _score in ranked:
                    if repo_url in used:
                        continue
                    chosen.append(repo_url)
                    used.add(repo_url)
                    if len(chosen) >= max(1, limit):
                        break
                return chosen[: max(1, limit)]
        return [url for url, _ in ranked[: max(1, limit)]]

    guesses = guess_repo_urls(query)
    return guesses[: max(1, limit)]


def _read_text(path: Path, max_chars: int = 5000, *, preserve_lines: bool = False) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if preserve_lines:
        lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in str(data or "").splitlines()]
        return "\n".join(lines)[:max_chars]
    return " ".join(data.split())[:max_chars]


def _looks_nav_line(line: str) -> bool:
    parts = [part.strip() for part in str(line or "").split("|") if part.strip()]
    if len(parts) < 2:
        return False
    if len(str(line or "").strip()) > 120:
        return False
    if any(part.endswith(".") for part in parts):
        return False
    return all(len(part) <= 24 for part in parts)


def _looks_marketing_shout(line: str) -> bool:
    letters = [ch for ch in str(line or "") if ch.isalpha()]
    if len(letters) < 8:
        return False
    uppercase = sum(1 for ch in letters if ch.isupper())
    words = re.findall(r"[A-Za-z0-9']+", str(line or ""))
    if not words or len(words) > 8:
        return False
    repeated = len(set(word.lower() for word in words)) <= max(1, len(words) // 2)
    return (uppercase / max(1, len(letters))) >= 0.85 and repeated


def _strip_markdown_inline(text: str) -> str:
    clean = str(text or "")
    clean = clean.replace("**", "").replace("__", "").replace("`", "")
    clean = re.sub(r"(?<!\*)\*(?!\*)", "", clean)
    clean = re.sub(r"(?<!_)_(?!_)", "", clean)
    return clean


def _looks_link_cloud(line: str) -> bool:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+./-]*", str(line or ""))
    if len(words) < 4:
        return False
    if len(str(line or "").strip()) > 140:
        return False
    if any(ch in str(line or "") for ch in ".:;!?"):
        return False
    lower_words = [word.lower() for word in words]
    nav_markers = {
        "website",
        "docs",
        "vision",
        "deepwiki",
        "getting",
        "started",
        "updating",
        "showcase",
        "faq",
        "onboard",
        "onboarding",
        "docker",
        "discord",
        "learn",
        "more",
        "quick",
        "start",
        "configuration",
        "documentation",
        "guide",
    }
    marker_hits = sum(1 for word in lower_words if word in nav_markers)
    if marker_hits >= 2:
        return True
    titled = sum(1 for word in words if word[:1].isupper())
    return len(words) >= 5 and all(len(word) <= 18 for word in words) and titled >= max(3, len(words) - 1)


def _looks_title_banner(line: str) -> bool:
    clean = str(line or "").strip()
    if not clean or any(ch in clean for ch in ".!?"):
        return False
    if "-" not in clean and "|" not in clean:
        return False
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+./'-]*", clean)
    if len(words) < 2 or len(words) > 10:
        return False
    lower = clean.lower()
    return not any(marker in lower for marker in (" is ", " are ", " helps ", " lets ", " makes ", " powers ", " use ", " build "))


def _readme_excerpt_clause(text: str) -> str:
    clean = str(text or "").strip().rstrip(".!?")
    return f"README excerpt: {clean}." if clean else ""


def _clean_readme_excerpt(text: str, *, max_chars: int = 700) -> str:
    clean = html.unescape(str(text or ""))
    if not clean:
        return ""
    replacements = {
        "—": "-",
        "–": "-",
        "’": "'",
        "“": '"',
        "”": '"',
        "Â": "",
        "â€”": "-",
        "â€“": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€�": '"',
        "ðŸ¦ž": "",
    }
    for source, target in replacements.items():
        clean = clean.replace(source, target)
    clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"https?://\S+", " ", clean)
    lines = [line.strip() for line in str(clean or "").splitlines()]
    kept: List[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line:
            continue
        lower = line.lower()
        if any(marker in lower for marker in ("img.shields.io", "srcset=", "raw.githubusercontent.com", "prefers-color-scheme")):
            continue
        line = re.sub(r"^#+\s*", "", line).strip()
        line = re.sub(r"^[-*]\s+", "", line).strip()
        line = _strip_markdown_inline(line)
        line = re.sub(r'([A-Za-z0-9])\s*["\']\s*([A-Z])', r"\1 - \2", line)
        if line.startswith(">"):
            continue
        if line.lower() in {"table of contents", "contents", "official website", "website"}:
            continue
        if re.fullmatch(r"\|?[\s\-:|]+\|?", line):
            continue
        if _looks_nav_line(line):
            continue
        if _looks_marketing_shout(line):
            continue
        if _looks_link_cloud(line):
            continue
        if _looks_title_banner(line):
            continue
        if len(line) < 3:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", line.lower())
        if normalized and normalized in seen:
            continue
        if normalized:
            seen.add(normalized)
        kept.append(line)
        if len(kept) >= 3 and len(" ".join(kept)) >= min(max_chars, 220):
            break
        if len(" ".join(kept)) >= max_chars:
            break
    collapsed = " ".join(kept)
    collapsed = _strip_markdown_inline(collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip(" .")
    collapsed = re.sub(r'([A-Za-z0-9])\s*"\s*([A-Z])', r"\1 - \2", collapsed)
    collapsed = re.sub(r"([A-Za-z0-9])\s*'\s*([A-Z])", r"\1 - \2", collapsed)
    collapsed = re.sub(r"\b([A-Z][A-Za-z0-9 .+-]{2,60})!\s+\1!\s*", "", collapsed)
    collapsed = re.sub(
        r"\b(It answers you on the channels you already use)\s*\((?:[^()]*,\s*){4,}[^()]*\)",
        r"\1.",
        collapsed,
        flags=re.IGNORECASE,
    )
    collapsed = re.sub(r"\((?:[^()]*,\s*){5,}[^()]*\)", "", collapsed)
    collapsed = collapsed.encode("ascii", "ignore").decode("ascii", errors="ignore")
    collapsed = re.sub(r'([A-Za-z0-9])\s*"\s*([A-Z])', r"\1 - \2", collapsed)
    collapsed = re.sub(r"([A-Za-z0-9])\s*'\s*([A-Z])", r"\1 - \2", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip(" .")
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", collapsed) if part.strip()]
    compact_sentences: List[str] = []
    seen_sentences: set[str] = set()
    for index, sentence in enumerate(sentences):
        sentence = re.sub(r"\s+", " ", sentence).strip()
        if not sentence:
            continue
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+./'-]*", sentence)
        lower = sentence.lower()
        if (
            index == 0
            and len(words) <= 6
            and not any(marker in lower for marker in (" is ", " are ", " lets ", " helps ", " gives ", " makes ", " runs ", " powers "))
            and len(sentences) > 1
        ):
            continue
        if sentence.count(",") >= 6 and "channels you already use" not in lower:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", lower)
        if normalized and normalized in seen_sentences:
            continue
        if normalized:
            seen_sentences.add(normalized)
        compact_sentences.append(sentence.rstrip(".") + ".")
        if len(" ".join(compact_sentences)) >= min(max_chars, 220):
            break
        if len(compact_sentences) >= 2:
            break
    final_excerpt = " ".join(compact_sentences) if compact_sentences else collapsed
    final_excerpt = re.sub(r"\s+", " ", final_excerpt).strip()
    return final_excerpt[:max_chars].rstrip()


def _parse_package_json(path: Path) -> str:
    return _parse_package_json_text(path.read_text(encoding="utf-8", errors="ignore"))


def _parse_package_json_text(text: str) -> str:
    try:
        payload = json.loads(str(text or ""))
    except Exception:
        return ""
    bits = []
    for key in ("name", "description", "version"):
        value = payload.get(key)
        if value:
            bits.append(f"{key}={value}")
    return "; ".join(bits)


def _parse_manifest(path: Path) -> str:
    if path.name == "package.json":
        return _parse_package_json(path)
    return _read_text(path, max_chars=1200)


def _parse_manifest_text(name: str, text: str) -> str:
    if name == "package.json":
        return _parse_package_json_text(text)
    return " ".join(str(text or "").split())[:1200]


def _fetch_text(url: str, *, timeout_s: float = 8.0, max_bytes: int = 250_000) -> str:
    request = urllib_request.Request(
        str(url or ""),
        headers={
            "User-Agent": "Somi-GitHub-Inspector/1.0",
            "Accept": "text/plain, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_s) as response:
            payload = response.read(max_bytes + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, ValueError):
        return ""
    except Exception:
        return ""
    return payload[:max_bytes].decode(charset, errors="ignore")


def _candidate_branches(branch: str) -> List[str]:
    branches: List[str] = []
    for candidate in (branch, "main", "master"):
        clean = str(candidate or "").strip()
        if clean and clean not in branches:
            branches.append(clean)
    return branches


def _raw_url(repo_slug: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_slug}/{branch}/{relative_path.lstrip('/')}"


def _first_remote_text(repo_slug: str, branches: Iterable[str], relative_paths: Iterable[str], *, max_chars: int) -> tuple[str, str, str]:
    for branch in list(branches):
        for relative_path in list(relative_paths):
            text = _fetch_text(_raw_url(repo_slug, branch, relative_path))
            if text:
                return branch, relative_path, str(text or "")[:max_chars]
    return "", "", ""


def _latest_commit_date(repo_url: str, branch: str) -> str:
    if not branch:
        return ""
    feed = _fetch_text(f"{repo_url}/commits/{branch}.atom", timeout_s=8.0, max_bytes=160_000)
    match = re.search(r"<updated>(\d{4}-\d{2}-\d{2})T", feed)
    return str(match.group(1)).strip() if match else ""


def _inspect_repository_via_remote(repo_url: str, repo_slug: str, branch: str, tags: List[str]) -> GitHubInspection:
    branches = _candidate_branches(branch)
    resolved_branch, readme_path, readme_text = _first_remote_text(
        repo_slug,
        branches,
        ("README.md", "README.rst", "README.txt"),
        max_chars=4000,
    )
    clean_readme_excerpt = _clean_readme_excerpt(readme_text, max_chars=420)
    active_branch = resolved_branch or (branches[0] if branches else "")
    manifests: Dict[str, str] = {}
    sources = [repo_url]
    if readme_path and active_branch:
        sources.append(_raw_url(repo_slug, active_branch, readme_path))
    for manifest_name in _MANIFEST_NAMES:
        manifest_branch, manifest_path, manifest_text = _first_remote_text(
            repo_slug,
            [active_branch] if active_branch else branches,
            (manifest_name,),
            max_chars=1200,
        )
        if not manifest_text:
            continue
        active_branch = active_branch or manifest_branch
        manifests[manifest_name] = _parse_manifest_text(manifest_name, manifest_text)[:500]
        sources.append(_raw_url(repo_slug, manifest_branch or active_branch, manifest_path))

    latest_commit = _latest_commit_date(repo_url, active_branch or branch)
    summary_parts = [f"{repo_slug} is a GitHub repository."]
    if active_branch:
        summary_parts.append(f"Default branch: {active_branch}.")
    if latest_commit:
        summary_parts.append(f"Latest visible commit: {latest_commit}.")
    if manifests:
        summary_parts.append(f"Detected manifests: {', '.join(manifests.keys())}.")
    if clean_readme_excerpt:
        summary_parts.append(_readme_excerpt_clause(clean_readme_excerpt))
    if tags:
        summary_parts.append(f"Recent tags: {', '.join(tags[:4])}.")

    return GitHubInspection(
        repo_url=repo_url,
        repo_slug=repo_slug,
        default_branch=active_branch or branch,
        latest_commit=latest_commit,
        readme_excerpt=_clean_readme_excerpt(readme_text, max_chars=1200),
        manifests=manifests,
        tags=tags,
        sources=sources,
        summary=" ".join(summary_parts).strip(),
        inspection_method="remote",
    )


def inspect_github_repository(
    repo_url: str,
    *,
    cleanup: bool = True,
    temp_root: str | None = None,
    remote_only: bool = False,
) -> GitHubInspection:
    repo_url = str(repo_url or "").strip().rstrip("/")
    matches = extract_repo_urls(repo_url)
    if not matches:
        raise ValueError("repo_url must be a GitHub repository URL")
    repo_url = matches[0]
    slug = repo_url.replace("https://github.com/", "", 1)
    git_url = repo_url + ".git"
    slug_key = slug.lower()

    branch = _KNOWN_DEFAULT_BRANCHES.get(slug_key, "") if remote_only else ""
    latest_commit = ""
    tags: List[str] = []
    if not remote_only:
        try:
            ls_remote = _run_git(["ls-remote", "--symref", git_url, "HEAD"], timeout_s=20.0)
            for line in ls_remote.splitlines():
                if line.startswith("ref: ") and "\tHEAD" in line:
                    branch = line.split("ref: ", 1)[1].split("\tHEAD", 1)[0].strip().rsplit("/", 1)[-1]
                    break
        except Exception:
            branch = ""
    if not branch:
        branch = _KNOWN_DEFAULT_BRANCHES.get(slug_key, "")

    try:
        if not remote_only and _should_fetch_tags(slug):
            tag_rows = _run_git(["ls-remote", "--tags", "--refs", git_url], timeout_s=8.0)
            tags = [line.rsplit("/", 1)[-1] for line in tag_rows.splitlines()[:5] if line.strip()]
    except Exception:
        tags = []

    remote_inspection = _inspect_repository_via_remote(repo_url, slug, branch, tags)
    if remote_only or remote_inspection.readme_excerpt or remote_inspection.manifests:
        return remote_inspection

    scratch_dir = tempfile.mkdtemp(prefix="somi_repo_", dir=temp_root)
    try:
        _run_git(["clone", "--depth", "1", "--filter=blob:none", "--no-checkout", git_url, scratch_dir], timeout_s=60.0)
        _run_git(["sparse-checkout", "init", "--cone"], cwd=scratch_dir, timeout_s=20.0)
        sparse_paths = [
            "README.md",
            "README.rst",
            "README.txt",
            "docs",
            "src",
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "Cargo.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
        ]
        _run_git(["sparse-checkout", "set", *sparse_paths], cwd=scratch_dir, timeout_s=20.0)
        _run_git(["checkout"], cwd=scratch_dir, timeout_s=30.0)

        try:
            latest_commit = _run_git(["log", "-1", "--date=short", "--format=%cd | %h | %s"], cwd=scratch_dir, timeout_s=20.0)
        except Exception:
            latest_commit = ""

        root = Path(scratch_dir)
        top_level_entries = sorted(p.name for p in root.iterdir())[:12]

        readme_text = ""
        for name in ("README.md", "README.rst", "README.txt"):
            candidate = root / name
            if candidate.exists():
                readme_text = _read_text(candidate, max_chars=4000, preserve_lines=True)
                if readme_text:
                    break
        clean_readme_excerpt = _clean_readme_excerpt(readme_text, max_chars=420)

        manifests: Dict[str, str] = {}
        for manifest_name in _MANIFEST_NAMES:
            candidate = root / manifest_name
            if candidate.exists():
                parsed = _parse_manifest(candidate)
                manifests[manifest_name] = parsed[:500]

        summary_parts = [f"{slug} is a GitHub repository."]
        if branch:
            summary_parts.append(f"Default branch: {branch}.")
        if latest_commit:
            summary_parts.append(f"Latest visible commit: {latest_commit}.")
        if top_level_entries:
            summary_parts.append(f"Top-level entries: {', '.join(top_level_entries[:8])}.")
        if manifests:
            summary_parts.append(f"Detected manifests: {', '.join(manifests.keys())}.")
        if clean_readme_excerpt:
            summary_parts.append(_readme_excerpt_clause(clean_readme_excerpt))
        if tags:
            summary_parts.append(f"Recent tags: {', '.join(tags[:4])}.")

        sources = [repo_url]
        if branch:
            sources.append(f"{repo_url}/tree/{branch}")
        return GitHubInspection(
            repo_url=repo_url,
            repo_slug=slug,
            default_branch=branch,
            latest_commit=latest_commit,
            readme_excerpt=_clean_readme_excerpt(readme_text, max_chars=1200),
            top_level_entries=top_level_entries,
            manifests=manifests,
            tags=tags,
            sources=sources,
            summary=" ".join(summary_parts).strip(),
            inspection_method="clone",
        )
    finally:
        if cleanup:
            shutil.rmtree(scratch_dir, ignore_errors=True)
