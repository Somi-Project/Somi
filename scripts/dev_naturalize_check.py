import asyncio
import re

INSTRUCT_MODEL = "stub"


class DummyOllama:
    async def chat(self, model, messages, options):
        return {
            "message": {
                "content": (
                    "As an AI assistant, here's a cleaned version.\n"
                    "In 2022, Bitcoin traded roughly between $15,476 and $47,686.\n"
                    "Sources:\n"
                    "- https://finance.yahoo.com/quote/BTC-USD/history\n"
                    "If you have any further questions, let me know."
                )
            }
        }


class NaturalizeHarness:
    def __init__(self):
        self.ollama_client = DummyOllama()

    def _looks_like_tool_dump(self, text: str) -> bool:
        if not text:
            return False
        t = str(text)
        tl = t.lower()
        strong_markers = (
            "## web/search context",
            "reply 'expand",
            "reply expand",
            "top results",
        )
        if any(m in tl for m in strong_markers):
            return True
        url_count = len(re.findall(r"https?://[^\s\]\)]+", t, flags=re.IGNORECASE))
        dump_markers = 0
        dump_markers += len(re.findall(r"(?im)^\s*(?:[-*]|\d+\.)\s+.+https?://", t))
        dump_markers += len(re.findall(r"(?im)^\s*(?:title|source|url)\s*:\s*", t))
        dump_markers += len(re.findall(r"(?im)^\s*\[[0-9]+\]\s+", t))
        return bool(url_count >= 2 and dump_markers >= 2)

    def _strip_search_meta_leakage(self, text: str) -> str:
        if not text:
            return text
        banned_line_patterns = [
            r"(?i)\bas an ai\b.*",
            r"(?i)\bbased on the provided\b.*",
            r"(?i)^\s*to provide\b.*",
            r"(?i)^\s*i would summarize\b.*",
            r"(?i)^\s*i hope this explanation helps\b.*",
            r"(?i)^\s*if you have any further questions\b.*",
            r"(?i)\braw search response\b.*",
            r"(?i)\btool output\b.*",
        ]
        kept_lines = []
        for line in str(text).splitlines():
            stripped = line.strip()
            if not stripped:
                kept_lines.append(line)
                continue
            has_url = bool(re.search(r"https?://", stripped, flags=re.IGNORECASE))
            has_number = bool(re.search(r"\d", stripped))
            is_meta = any(re.search(p, stripped) for p in banned_line_patterns)
            if is_meta and not has_url and not has_number:
                continue
            kept_lines.append(line)
        return "\n".join(kept_lines).strip()

    async def _naturalize_search_output(self, raw_content: str, original_prompt: str) -> str:
        if not self._looks_like_tool_dump(raw_content):
            return raw_content

        system_prompt = "output only"
        user_prompt = f"{original_prompt}\n{raw_content}"
        _ = (system_prompt, user_prompt)
        resp = await self.ollama_client.chat(
            model=INSTRUCT_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            options={"temperature": 0.1, "max_tokens": 600, "keep_alive": 300},
        )
        cleaned = resp.get("message", {}).get("content", "") or raw_content
        scrubbed = self._strip_search_meta_leakage(cleaned)
        return scrubbed if scrubbed else raw_content


async def main() -> None:
    harness = NaturalizeHarness()

    raw_content = """## Web/Search Context
Top results
BTC-USD year low (2022): $15,476
BTC-USD year high (2022): $47,686
Reply 'expand' for more
https://finance.yahoo.com/quote/BTC-USD/history
"""

    cleaned = await harness._naturalize_search_output(raw_content, "what was the price in 2022")

    forbidden_phrases = [
        "as an ai",
        "based on the provided",
        "to provide",
        "i would summarize",
        "i hope this explanation helps",
        "if you have any further questions",
    ]
    lowered = cleaned.lower()
    assert all(p not in lowered for p in forbidden_phrases), cleaned
    assert "$15,476" in cleaned and "$47,686" in cleaned, cleaned
    assert "https://finance.yahoo.com/quote/BTC-USD/history" in cleaned, cleaned

    print("PASS: naturalize output is non-meta and preserves numbers + URL")


if __name__ == "__main__":
    asyncio.run(main())
