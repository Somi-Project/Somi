from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from workshop.toolbox.browser.store import BrowserAutomationStore


_ALLOWED_SCHEMES = {"http", "https", "file"}
_MUTATING_ACTIONS = {"click", "fill", "press"}


class BrowserRuntimeError(RuntimeError):
    pass


def _install_hint() -> str:
    return "Run '.venv\\\\Scripts\\\\playwright install chromium' to install the local browser runtime."


def browser_health() -> dict[str, Any]:
    try:
        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
            ok = executable.exists()
            return {
                "ok": ok,
                "browser": "chromium",
                "executable_path": str(executable),
                "install_hint": "" if ok else _install_hint(),
            }
    except Exception as exc:
        return {"ok": False, "browser": "chromium", "executable_path": "", "install_hint": _install_hint(), "error": str(exc)}


def _normalize_target(target: str) -> str:
    text = str(target or "").strip()
    if not text:
        raise BrowserRuntimeError("target is required")
    candidate = Path(text)
    if candidate.exists():
        return candidate.resolve().as_uri()
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BrowserRuntimeError(f"Unsupported target scheme: {parsed.scheme or '(none)'}")
    return text


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _page_snapshot(page, *, text_cap: int = 2400, max_links: int = 12) -> dict[str, Any]:
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""

    try:
        links = page.eval_on_selector_all(
            "a[href]",
            """elements => elements.slice(0, 12).map(el => ({
                text: (el.innerText || '').trim().slice(0, 160),
                href: el.href || ''
            }))""",
        )
    except Exception:
        links = []
    max_link_count = max(1, min(int(max_links or 12), 24))
    links = [dict(item) for item in list(links or [])[:max_link_count] if isinstance(item, dict)]

    def _count(selector: str) -> int:
        try:
            return int(page.locator(selector).count())
        except Exception:
            return 0

    return {
        "title": page.title(),
        "url": page.url,
        "text_excerpt": str(body_text or "")[: max(200, min(int(text_cap or 2400), 6000))],
        "links": links,
        "form_count": _count("form"),
        "input_count": _count("input, textarea, select"),
        "button_count": _count("button, input[type=button], input[type=submit]"),
    }


def capture_page_state(target: str, *, options: dict[str, Any] | None = None) -> dict[str, Any]:
    health = browser_health()
    if not bool(health.get("ok", False)):
        raise BrowserRuntimeError(str(health.get("install_hint") or health.get("error") or "Browser runtime unavailable"))

    opts = dict(options or {})
    timeout_ms = _safe_int(opts.get("timeout_ms"), default=15000, minimum=1000, maximum=45000)
    wait_until = str(opts.get("wait_until") or "domcontentloaded").strip().lower() or "domcontentloaded"
    max_links = _safe_int(opts.get("max_links"), default=12, minimum=1, maximum=24)
    text_cap = _safe_int(opts.get("text_cap"), default=2400, minimum=200, maximum=6000)
    url = _normalize_target(target)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            snapshot = _page_snapshot(page, text_cap=text_cap, max_links=max_links)
        except PlaywrightTimeoutError as exc:
            raise BrowserRuntimeError(f"Timed out while loading target: {exc}") from exc
        except PlaywrightError as exc:
            raise BrowserRuntimeError(str(exc)) from exc
        finally:
            context.close()
            browser.close()

    return {"ok": True, "target": url, "snapshot": snapshot, "health": health}


def capture_screenshot(target: str, *, options: dict[str, Any] | None = None, store: BrowserAutomationStore | None = None) -> dict[str, Any]:
    health = browser_health()
    if not bool(health.get("ok", False)):
        raise BrowserRuntimeError(str(health.get("install_hint") or health.get("error") or "Browser runtime unavailable"))

    opts = dict(options or {})
    timeout_ms = _safe_int(opts.get("timeout_ms"), default=15000, minimum=1000, maximum=45000)
    wait_until = str(opts.get("wait_until") or "domcontentloaded").strip().lower() or "domcontentloaded"
    full_page = bool(opts.get("full_page", True))
    output_store = store or BrowserAutomationStore()
    target_url = _normalize_target(target)
    path = output_store.next_capture_path(label=str(opts.get("label") or "browser_capture"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
            page.screenshot(path=str(path), full_page=full_page)
            snapshot = _page_snapshot(page)
        except PlaywrightTimeoutError as exc:
            raise BrowserRuntimeError(f"Timed out while loading target: {exc}") from exc
        except PlaywrightError as exc:
            raise BrowserRuntimeError(str(exc)) from exc
        finally:
            context.close()
            browser.close()

    return {"ok": True, "target": target_url, "screenshot_path": str(path.resolve()), "snapshot": snapshot, "health": health}


def run_browser_flow(
    target: str,
    *,
    options: dict[str, Any] | None = None,
    approved: bool = False,
    store: BrowserAutomationStore | None = None,
) -> dict[str, Any]:
    health = browser_health()
    if not bool(health.get("ok", False)):
        raise BrowserRuntimeError(str(health.get("install_hint") or health.get("error") or "Browser runtime unavailable"))

    opts = dict(options or {})
    raw_steps = [dict(step) for step in list(opts.get("steps") or []) if isinstance(step, dict)]
    if not raw_steps:
        raise BrowserRuntimeError("options.steps is required for run_flow")
    if len(raw_steps) > 12:
        raise BrowserRuntimeError("Browser flow exceeds the 12-step safety cap")

    timeout_ms = _safe_int(opts.get("timeout_ms"), default=15000, minimum=1000, maximum=45000)
    wait_until = str(opts.get("wait_until") or "domcontentloaded").strip().lower() or "domcontentloaded"
    output_store = store or BrowserAutomationStore()
    target_url = _normalize_target(target)
    step_rows: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
            for idx, step in enumerate(raw_steps, start=1):
                action = str(step.get("action") or "").strip().lower()
                if action not in {"goto", "wait_for_selector", "click", "fill", "press", "snapshot", "screenshot"}:
                    raise BrowserRuntimeError(f"Unsupported browser step action: {action or '(blank)'}")
                if action in _MUTATING_ACTIONS and not approved:
                    raise BrowserRuntimeError(f"Step {idx} requires approval: {action}")
                selector = str(step.get("selector") or "").strip()
                value = str(step.get("value") or "").strip()
                step_timeout = _safe_int(step.get("timeout_ms"), default=timeout_ms, minimum=500, maximum=45000)

                if action == "goto":
                    step_target = _normalize_target(str(step.get("target") or value or target_url))
                    page.goto(step_target, wait_until=wait_until, timeout=step_timeout)
                    step_rows.append({"step": idx, "action": action, "ok": True, "target": step_target})
                    continue
                if action == "wait_for_selector":
                    if not selector:
                        raise BrowserRuntimeError(f"Step {idx} is missing selector")
                    state = str(step.get("state") or "visible").strip().lower() or "visible"
                    page.wait_for_selector(selector, state=state, timeout=step_timeout)
                    step_rows.append({"step": idx, "action": action, "ok": True, "selector": selector, "state": state})
                    continue
                if action == "click":
                    if not selector:
                        raise BrowserRuntimeError(f"Step {idx} is missing selector")
                    page.locator(selector).click(timeout=step_timeout)
                    step_rows.append({"step": idx, "action": action, "ok": True, "selector": selector})
                    continue
                if action == "fill":
                    if not selector:
                        raise BrowserRuntimeError(f"Step {idx} is missing selector")
                    page.locator(selector).fill(value, timeout=step_timeout)
                    step_rows.append({"step": idx, "action": action, "ok": True, "selector": selector})
                    continue
                if action == "press":
                    if not selector:
                        raise BrowserRuntimeError(f"Step {idx} is missing selector")
                    page.locator(selector).press(value or "Enter", timeout=step_timeout)
                    step_rows.append({"step": idx, "action": action, "ok": True, "selector": selector, "value": value or "Enter"})
                    continue
                if action == "snapshot":
                    step_rows.append({"step": idx, "action": action, "ok": True, "snapshot": _page_snapshot(page)})
                    continue
                if action == "screenshot":
                    path = output_store.next_capture_path(label=str(step.get("label") or f"step_{idx}"))
                    page.screenshot(path=str(path), full_page=bool(step.get("full_page", True)))
                    step_rows.append({"step": idx, "action": action, "ok": True, "screenshot_path": str(path.resolve())})

            final_snapshot = _page_snapshot(page)
            final_screenshot_path = ""
            if bool(opts.get("capture_final_screenshot", False)):
                final_path = output_store.next_capture_path(label=str(opts.get("label") or "final"))
                page.screenshot(path=str(final_path), full_page=True)
                final_screenshot_path = str(final_path.resolve())
        except PlaywrightTimeoutError as exc:
            raise BrowserRuntimeError(f"Browser flow timed out: {exc}") from exc
        except PlaywrightError as exc:
            raise BrowserRuntimeError(str(exc)) from exc
        finally:
            context.close()
            browser.close()

    run_payload = {
        "ok": True,
        "target": target_url,
        "steps": step_rows,
        "final_snapshot": final_snapshot,
        "final_screenshot_path": final_screenshot_path,
        "health": health,
    }
    run_payload["run_log_path"] = output_store.write_run(run_payload, label=str(opts.get("label") or "browser_flow"))
    return run_payload
