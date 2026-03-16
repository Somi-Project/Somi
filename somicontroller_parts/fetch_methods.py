from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (fetch_methods.py)."""

def kickoff_startup_refreshes(self):
    if not self.isVisible():
        return
    self.refresh_weather()
    self.refresh_news()
    self.refresh_finance_news()
    self.refresh_developments()

def refresh_weather(self):
    self.push_activity("ambient", "Refreshing weather")
    self._start_worker("weather", self.fetch_weather)

def refresh_news(self):
    self.push_activity("ambient", "Refreshing news")
    self._start_worker("news", self.fetch_news)

def refresh_finance_news(self):
    self.push_activity("ambient", "Refreshing finance news")
    self._start_worker("finance_news", self.fetch_finance_news)

def refresh_developments(self):
    self.push_activity("ambient", "Refreshing development feed")
    self._start_worker("developments", self.fetch_developments)

def refresh_reminders(self):
    self.state["reminders"] = self.load_reminders()
    self.push_activity("ambient", "Reminders refreshed")
    self.update_top_strip()

def _start_worker(self, kind, fn):
    worker = FetchWorker(kind, fn)
    worker.result.connect(self.on_fetch_result)
    worker.finished.connect(lambda: self.workers.remove(worker) if worker in self.workers else None)
    self.workers.append(worker)
    worker.start()

def on_fetch_result(self, kind, data):
    now_stamp = datetime.now().strftime("%H:%M")

    if kind == "weather":
        if data.get("ok"):
            self.state["weather"].update(data)
            self.state["weather"]["last_updated"] = now_stamp
            self.heartbeat_service.set_shared_context(
                HB_CACHED_WEATHER_LINE=self.state["weather"].get("line", ""),
                HB_CACHED_WEATHER_TS=datetime.now().astimezone().isoformat(),
                HB_CACHED_WEATHER_PAYLOAD={
                    "temp_c": data.get("temp"),
                    "description": self.state["weather"].get("line", ""),
                    "source": "gui_weather_refresh",
                },
            )
            self.push_activity("ambient", "Weather refreshed")
        else:
            self.state["weather"] = {"emoji": "WX", "temp": "--", "line": "Weather unavailable", "last_updated": now_stamp}
            self.heartbeat_service.set_shared_context(HB_CACHED_WEATHER_LINE="", HB_CACHED_WEATHER_TS="", HB_CACHED_WEATHER_PAYLOAD=None)
            self.push_activity("ambient", "Weather unavailable", level="warn")

    elif kind == "news":
        if data.get("ok"):
            self.state["news"] = {
                "headlines": data.get("headlines", []),
                "count": len(data.get("headlines", [])),
                "last_updated": now_stamp,
            }
            self.push_activity("ambient", "News refreshed")
        else:
            self.state["news"] = {"headlines": [], "count": 0, "last_updated": now_stamp}
            self.push_activity("ambient", "News unavailable", level="warn")

    elif kind == "finance_news":
        if data.get("ok"):
            self.state["finance_news"] = {
                "headlines": data.get("headlines", []),
                "count": len(data.get("headlines", [])),
                "last_updated": now_stamp,
            }
            self.push_activity("ambient", "Finance news refreshed")
        else:
            self.state["finance_news"] = {"headlines": [], "count": 0, "last_updated": now_stamp}
            self.push_activity("ambient", "Finance news unavailable", level="warn")

    elif kind == "developments":
        if data.get("ok"):
            self.state["developments"] = {
                "headlines": data.get("headlines", []),
                "count": len(data.get("headlines", [])),
                "last_updated": now_stamp,
            }
            self.push_activity("ambient", "Development feed refreshed")
        else:
            self.state["developments"] = {"headlines": [], "count": 0, "last_updated": now_stamp}
            self.push_activity("ambient", "Development feed unavailable", level="warn")

    elif kind == "runtime_diagnostics":
        self._runtime_diagnostics_running = False
        if data.get("ok"):
            report = dict(data.get("report") or {})
            score = report.get("score", 0.0)
            passed = int(report.get("passed", 0) or 0)
            total = int(report.get("total", 0) or 0)
            report_ok = bool(report.get("ok", False))
            report_path = str(data.get("report_path") or "sessions/evals/latest_eval_harness.json")
            self.output_area.append(
                f"[Diagnostics] Eval harness: {'PASS' if report_ok else 'FAIL'} "
                f"({passed}/{total}, score={score}%). Report: {report_path}"
            )
            self.output_area.ensureCursorVisible()
            if report_ok:
                self.push_activity("diagnostics", "Runtime diagnostics passed")
            else:
                failed = [
                    str(c.get("name"))
                    for c in list(report.get("checks") or [])
                    if not bool(c.get("ok"))
                ][:5]
                detail = ", ".join(failed) if failed else "check failures detected"
                self.push_activity("diagnostics", f"Runtime diagnostics found issues: {detail}", level="warn")
        else:
            err = str(data.get("error") or "diagnostics failed")
            self.output_area.append(f"[Diagnostics] Failed: {err}")
            self.output_area.ensureCursorVisible()
            self.push_activity("diagnostics", "Runtime diagnostics failed", level="warn")


    self.update_top_strip()
    self.rotate_intel()
    self.update_stream_meters()

def fetch_weather(self):
    try:
        url = "https://wttr.in/?format=j1"
        with urllib.request.urlopen(url, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        current = data.get("current_condition", [{}])[0]
        temp = current.get("temp_C", "--")
        code = int(current.get("weatherCode", 0)) if str(current.get("weatherCode", "")).isdigit() else 0
        emoji = "SUN" if code in (0, 1) else "CLOUD" if code in (2, 3) else "RAIN"
        line = f"Feels like {current.get('FeelsLikeC', '--')}C with {current.get('weatherDesc', [{'value': 'conditions unknown'}])[0].get('value')}"
        return {"ok": True, "emoji": emoji, "temp": f"{temp}C", "line": line}
    except Exception:
        return {"ok": False}

def _fetch_rss_headlines(self, url: str, limit: int = 6) -> list[str]:
    with urllib.request.urlopen(url, timeout=10) as response:
        xml_text = response.read().decode("utf-8", errors="ignore")
    root = ET.fromstring(xml_text)
    headlines = []
    for item in root.findall("./channel/item/title")[: max(1, int(limit))]:
        title = (item.text or "").strip()
        if title:
            headlines.append(title)
    return headlines

def fetch_news(self):
    try:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        return {"ok": True, "headlines": self._fetch_rss_headlines(url, limit=6)}
    except Exception:
        return {"ok": False}

def fetch_finance_news(self):
    try:
        url = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
        return {"ok": True, "headlines": self._fetch_rss_headlines(url, limit=6)}
    except Exception:
        return {"ok": False}

def fetch_developments(self):
    try:
        url = "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en"
        return {"ok": True, "headlines": self._fetch_rss_headlines(url, limit=6)}
    except Exception:
        return {"ok": False}

def load_reminders(self):
    reminders_file = Path("memory/reminders.json")
    due_count = 0
    next_due = "None"
    if reminders_file.exists():
        try:
            payload = json.loads(reminders_file.read_text(encoding="utf-8"))
            due = [r for r in payload if str(r.get("status", "")).lower() != "done"]
            due_count = len(due)
            if due:
                next_due = due[0].get("due", "Soon")
        except Exception:
            pass
    return {"due_count": due_count, "next_due": next_due, "last_updated": datetime.now().strftime("%H:%M")}

def trigger_engagement(self):
    finance_headline = self.state["finance_news"]["headlines"][0] if self.state["finance_news"]["headlines"] else "No finance pulse right now."
    picks = [
        random.choice(FACTS),
        random.choice(JOKES),
        "Try a 2-minute rapid study burst, pick one topic and summarize it.",
        "Ask SOMI for a contrarian take on your current project.",
        self.state["news"]["headlines"][0] if self.state["news"]["headlines"] else "No live headline right now, want a curiosity prompt instead?",
        finance_headline,
    ]
    msg = random.choice(picks)
    self.intel_text.setText(msg)
    self.push_activity("engage", f"I'm bored trigger: {msg}")

def copy_context_pack(self):
    headline = self.state["news"]["headlines"][0] if self.state["news"]["headlines"] else "No headline"
    finance = self.state["finance_news"]["headlines"][0] if self.state["finance_news"]["headlines"] else "No finance headline"
    dev = self.state["developments"]["headlines"][0] if self.state["developments"]["headlines"] else "No development headline"
    pack = (
        f"Time: {self.state['system_time_str']} {self.state['timezone']}\n"
        f"Weather: {self.state['weather']['line']}\n"
        f"Top headline: {headline}\n"
        f"Finance headline: {finance}\n"
        f"Development headline: {dev}\n"
        f"Reminders due: {self.state['reminders']['due_count']} (next: {self.state['reminders']['next_due']})"
    )
    QApplication.clipboard().setText(pack)
    self.push_activity("context", "Context pack copied to clipboard")
