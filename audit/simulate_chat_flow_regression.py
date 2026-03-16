import asyncio
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


import agents as agents_module
from agents import Agent

REPORT_PATH = Path('audit/chat_flow_regression_report.md')

PROMPTS = [
    'Give me the latest AI chip news.',
    'open 2',
    'what were the key claims in that story?',
    'compare that with result 1',
    'summarize this URL https://example.com/analysis',
    'switch topic: what is a good python study plan?',
    'make that into 3 steps',
    'add one warning about burnout',
    'quick recap of our chat so far',
    'what should i ask next?'
]


class FakeRAGHandler:
    def __init__(self, *args, **kwargs):
        pass


class FakeMemoryManager:
    def __init__(self, *args, **kwargs):
        pass

    async def build_injected_context(self, prompt, user_id='default_user', **kwargs):
        return 'User prefers concise actionable answers.'


async def run_regression() -> bool:
    queries_seen = []

    original_decide_route = agents_module.decide_route
    original_trigger_msgs = agents_module.HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES
    original_keep_recent = agents_module.HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES
    original_rag_handler = agents_module.RAGHandler
    original_memory_manager = agents_module.Memory3Manager

    def fake_decide_route(prompt, agent_state=None):
        p = str(prompt or '').lower()
        search_words = ('latest', 'open', 'result', 'story', 'url', 'headline', 'news')
        route = 'websearch' if any(w in p for w in search_words) else 'normal'
        return SimpleNamespace(route=route, reason='simulated_regression_route', tool_veto=False, signals={})

    agents_module.decide_route = fake_decide_route
    agents_module.HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES = 8
    agents_module.HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES = 4
    agents_module.RAGHandler = FakeRAGHandler
    agents_module.Memory3Manager = FakeMemoryManager

    try:
        agent = Agent(name='Somi', user_id='regression_user', use_studies=False)

        async def fake_tool(self, tool_name, args, ctx, active_user_id):
            if str(tool_name) != 'web.intelligence':
                return {}
            q = str((args or {}).get('query') or '')
            ql = q.lower()
            queries_seen.append(q)

            if 'summarize this url:' in ql:
                url = q.split(':', 1)[1].strip() if ':' in q else 'https://unknown.local'
                return {
                    'formatted': f'Simulated summary context for {url}',
                    'results': [
                        {'title': f'Summary for {url}', 'url': url, 'description': 'simulated summary result'}
                    ],
                }

            if all(token in ql for token in ('latest', 'ai', 'chip', 'news')):
                return {
                    'formatted': '1) A100 refresh announced\n2) New low-power edge NPU\n3) Open accelerator benchmark updates',
                    'results': [
                        {'title': 'A100 refresh announced', 'url': 'https://news.example/a100', 'description': 'datacenter update'},
                        {'title': 'Low-power edge NPU', 'url': 'https://news.example/npu', 'description': 'edge compute update'},
                        {'title': 'Open accelerator benchmark', 'url': 'https://news.example/bench', 'description': 'benchmark update'},
                    ],
                }

            return {
                'formatted': f'Simulated search context for: {q}',
                'results': [
                    {'title': f'Result for {q}', 'url': 'https://news.example/generic', 'description': 'generic'}
                ],
            }

        class FakeOllama:
            async def chat(self, model, messages, options=None):
                user_msg = ''
                for msg in reversed(messages or []):
                    if str(msg.get('role')) == 'user':
                        user_msg = str(msg.get('content') or '')
                        break
                return {'message': {'content': f'Simulated response: {user_msg[:160]}'}}

        async def fake_ingest(self, active_user_id='default_user'):
            return None

        agent._run_tool_with_loop_guard = MethodType(fake_tool, agent)
        agent.ollama_client = FakeOllama()
        agent._enqueue_memory_write = lambda **kwargs: None
        agent._memory_ingest_nonblocking = MethodType(fake_ingest, agent)
        agent._build_rag_block = MethodType(lambda self, prompt, k=2: '', agent)

        rows = []
        failed = []

        t0 = time.perf_counter()
        for idx, prompt in enumerate(PROMPTS, start=1):
            try:
                started = time.perf_counter()
                out = await agent.generate_response(prompt=prompt, user_id='regression_user')
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if 'generation failed' in str(out).lower():
                    failed.append(f'Turn {idx}: generation failure message')
                rows.append((idx, prompt, out[:120].replace('\n', ' '), elapsed_ms))
            except Exception as exc:
                failed.append(f'Turn {idx}: exception {type(exc).__name__}: {exc}')

        total_ms = int((time.perf_counter() - t0) * 1000)

        hist_default = list(agent.history or [])
        hist_per_user = list(agent.history_by_user.get('regression_user', []) or [])
        history_pool = hist_per_user if hist_per_user else hist_default
        compaction_present = any(str(m.get('content') or '').startswith(agents_module.COMPACTION_PREFIX) for m in history_pool)
        selected_ctx = agent.tool_context_store.get('regression_user')
        selected_url = str(getattr(selected_ctx, 'last_selected_url', '') or '') if selected_ctx else ''

        followup_rewrite_seen = any('summarize this URL: https://news.example/npu' in q for q in queries_seen)

        checks = {
            'turn_count_10': len(rows) == 10,
            'no_failures': not failed,
            'followup_rewrite_open_2': followup_rewrite_seen,
            'selected_url_persisted': selected_url == 'https://news.example/npu',
            'history_compaction_triggered': compaction_present,
        }

        overall_ok = all(checks.values())

        lines = [
            '# Chat Flow Regression Report',
            '',
            f'- timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}',
            f'- total_turns: {len(rows)}',
            f'- total_elapsed_ms: {total_ms}',
            f'- overall_ok: {str(overall_ok).lower()}',
            f'- history_messages_checked: {len(history_pool)}',
            f'- selected_url: {selected_url or "(none)"}',
            '',
            '## Checks',
        ]
        for name, ok in checks.items():
            lines.append(f'- {name}: {"pass" if ok else "fail"}')

        if failed:
            lines.extend(['', '## Failures'])
            for row in failed:
                lines.append(f'- {row}')

        lines.extend(['', '## Turn Samples'])
        for idx, prompt, preview, elapsed in rows:
            lines.append(f'- {idx}. {prompt} -> ({elapsed} ms) {preview}')

        lines.extend(['', '## Tool Query Trace'])
        for query in queries_seen:
            lines.append(f'- {query}')

        REPORT_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return overall_ok
    finally:
        agents_module.decide_route = original_decide_route
        agents_module.HISTORY_AUTO_COMPACT_TRIGGER_MESSAGES = original_trigger_msgs
        agents_module.HISTORY_AUTO_COMPACT_KEEP_RECENT_MESSAGES = original_keep_recent
        agents_module.RAGHandler = original_rag_handler
        agents_module.Memory3Manager = original_memory_manager


def main() -> int:
    ok = asyncio.run(run_regression())
    print(f'overall_ok={str(ok).lower()}')
    print(f'report={REPORT_PATH.resolve()}')
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
