from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (status_methods.py)."""

def push_activity(self, kind, message, ts=None, level="info"):
    stamp = ts or datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    self.state["activity_events"].append({"kind": kind, "message": message, "ts": stamp, "level": level})

    gateway_service = getattr(self, "gateway_service", None)
    gateway_session = getattr(self, "gateway_session", {}) or {}
    if gateway_service is not None and gateway_session:
        try:
            gateway_service.publish_event(
                event_type="activity",
                surface="gui",
                title=str(message or kind or "GUI activity"),
                body=f"[{kind}] {message}",
                level=level,
                user_id="default_user",
                session_id=str(gateway_session.get("session_id") or ""),
                client_id=str(gateway_session.get("client_id") or ""),
                metadata={"kind": str(kind or ""), "ts": str(stamp or "")},
            )
        except Exception:
            pass

    if getattr(self, "activity_list", None) is not None:
        self.activity_list.addItem(QListWidgetItem(line))
        self.activity_list.scrollToBottom()
    if getattr(self, "idle_label", None) is not None:
        self.idle_label.setVisible(False)

def _research_mode_badge(self, mode):
    mapping = {
        "quick": "QUICK",
        "quick_web": "QUICK",
        "deep": "DEEP",
        "deep_browse": "DEEP",
        "github": "GITHUB",
        "direct_url": "URL",
        "official": "OFFICIAL",
        "official_direct": "OFFICIAL",
        "standby": "STANDBY",
    }
    return mapping.get(str(mode or "").strip().lower(), str(mode or "standby").strip().upper() or "STANDBY")

def _research_trace_preview(self, report, *, limit=2):
    trace = []
    for entry in list(dict(report or {}).get("trace") or []):
        clean = re.sub(r"^\d+\.\s*", "", " ".join(str(entry or "").split()).strip())
        if clean:
            trace.append(clean)
    if trace:
        return trace[: max(1, int(limit or 2))]

    progress = re.sub(r"^\d+\.\s*", "", " ".join(str(dict(report or {}).get("progress_headline") or "").split()).strip())
    if progress:
        return [progress[:160]]

    summary = " ".join(str(dict(report or {}).get("execution_summary") or "").split()).strip()
    if summary:
        return [summary[:160]]
    return []

def _research_timeline_preview(self, report, *, limit=4):
    timeline = []
    payload = dict(report or {})
    for item in list(payload.get("execution_events") or []):
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or item.get("step") or "").split()).strip()
        detail = " ".join(str(item.get("detail") or item.get("summary") or "").split()).strip()
        status = str(item.get("status") or "").strip().lower()
        if not label and not detail:
            continue
        prefix = {
            "recovery": "RECOVERY",
            "error": "ALERT",
            "warn": "WATCH",
            "done": "DONE",
            "success": "DONE",
            "working": "LIVE",
            "active": "LIVE",
        }.get(status, "STEP")
        body = f"{label} -> {detail}" if label and detail else (label or detail)
        body = re.sub(r"^\d+\.\s*", "", body).strip()
        if body:
            timeline.append(f"{prefix} | {body[:150]}")
    if timeline:
        return timeline[: max(1, int(limit or 4))]

    for item in list(payload.get("execution_steps") or []):
        clean = re.sub(r"^\d+\.\s*", "", " ".join(str(item or "").split()).strip())
        if clean:
            timeline.append(f"STEP | {clean[:150]}")
    if timeline:
        return timeline[: max(1, int(limit or 4))]

    for item in list(payload.get("trace") or []):
        clean = re.sub(r"^\d+\.\s*", "", " ".join(str(item or "").split()).strip())
        if clean:
            timeline.append(f"TRACE | {clean[:150]}")
    if timeline:
        return timeline[: max(1, int(limit or 4))]

    progress = re.sub(r"^\d+\.\s*", "", " ".join(str(payload.get("progress_headline") or "").split()).strip())
    if progress:
        return [f"LIVE | {progress[:150]}"]
    return []

def _research_source_preview(self, report, *, limit=3):
    preview = []
    payload = dict(report or {})
    for item in list(payload.get("source_preview") or []):
        clean = " ".join(str(item or "").split()).strip()
        if clean:
            preview.append(clean[:92])
    if preview:
        return preview[: max(1, int(limit or 3))]

    for item in list(payload.get("sources") or []):
        if isinstance(item, dict):
            label = " ".join(str(item.get("title") or item.get("label") or item.get("url") or "").split()).strip()
        else:
            label = " ".join(str(item or "").split()).strip()
        if not label:
            continue
        label = re.sub(r"^https?://", "", label, flags=re.IGNORECASE)
        label = label.split("?", 1)[0].split("#", 1)[0].strip("/")
        preview.append(label[:92])
    return preview[: max(1, int(limit or 3))]

def update_research_pulse(self, report=None, *, announce=False):
    state = dict(self.state.get("research_pulse") or {})
    previous_query = str(state.get("query") or "").strip()
    incoming = dict(report or {}) if isinstance(report, dict) else {}

    if incoming:
        query = " ".join(str(incoming.get("query") or "").split()).strip()
        mode = str(incoming.get("mode") or state.get("mode") or "standby").strip().lower() or "standby"
        summary = " ".join(str(incoming.get("summary") or "").split()).strip()
        progress_headline = " ".join(str(incoming.get("progress_headline") or "").split()).strip()
        execution_summary = " ".join(str(incoming.get("execution_summary") or "").split()).strip()
        trust_level = str(incoming.get("trust_level") or state.get("trust_level") or "").strip().lower()
        trust_summary = " ".join(str(incoming.get("trust_summary") or state.get("trust_summary") or "").split()).strip()
        trace = self._research_trace_preview(incoming, limit=2)
        timeline = self._research_timeline_preview(incoming, limit=4)
        source_preview = self._research_source_preview(incoming, limit=3)
        try:
            sources_count = max(0, int(incoming.get("sources_count") or len(list(incoming.get("sources") or [])) or 0))
        except Exception:
            sources_count = 0
        try:
            limitations_count = max(0, int(incoming.get("limitations_count") or len(list(incoming.get("limitations") or [])) or 0))
        except Exception:
            limitations_count = 0
        updated_at = str(incoming.get("updated_at") or datetime.now().strftime("%H:%M")).strip() or datetime.now().strftime("%H:%M")
        state = {
            "query": query,
            "mode": mode,
            "summary": summary or trust_summary or progress_headline or execution_summary or "Somi finished a browse pass and condensed the evidence.",
            "progress_headline": progress_headline,
            "trace": trace,
            "timeline": timeline,
            "source_preview": source_preview,
            "sources_count": sources_count,
            "limitations_count": limitations_count,
            "trust_level": trust_level,
            "trust_summary": trust_summary,
            "updated_at": updated_at,
            "updated_epoch": datetime.now().timestamp(),
        }
        self.state["research_pulse"] = state
        if announce and query:
            if query != previous_query:
                compact_query = query if len(query) <= 72 else f"{query[:69].rstrip()}..."
                self.push_activity("research", f"Research pulse updated: {self._research_mode_badge(mode)} | {compact_query}")
            elif progress_headline:
                compact_headline = progress_headline if len(progress_headline) <= 84 else f"{progress_headline[:81].rstrip()}..."
                self.push_activity("research", f"Research trace refined: {compact_headline}")
    else:
        self.state["research_pulse"] = state

    pulse = dict(self.state.get("research_pulse") or {})
    badge = self._research_mode_badge(pulse.get("mode"))
    sources_count = int(pulse.get("sources_count") or 0)
    limitations_count = int(pulse.get("limitations_count") or 0)
    query_text = str(pulse.get("query") or "").strip() or "No research pulse yet."
    summary_text = str(pulse.get("summary") or "").strip() or "Somi will surface search traces here during deeper browsing."
    trace_rows = [str(item).strip() for item in list(pulse.get("trace") or []) if str(item).strip()]
    trace_text = "\n".join(f"{idx}. {item}" for idx, item in enumerate(trace_rows[:2], start=1))
    timeline_rows = [str(item).strip() for item in list(pulse.get("timeline") or []) if str(item).strip()]
    source_rows = [str(item).strip() for item in list(pulse.get("source_preview") or []) if str(item).strip()]
    if not trace_text:
        progress = str(pulse.get("progress_headline") or "").strip()
        trace_text = progress or "Trace will appear once Somi plans and reads sources."
    feed_rows = []
    for row in timeline_rows[:3]:
        feed_rows.append(row)
    for row in source_rows[:2]:
        feed_rows.append(f"SOURCE | {row}")
    if not feed_rows:
        feed_rows = ["STANDBY | Awaiting a browse pass to shortlist sources."]

    if getattr(self, "research_mode_label", None) is not None:
        self.research_mode_label.setText(f"{badge} | {sources_count} src")
    if getattr(self, "research_query_label", None) is not None:
        self.research_query_label.setText(query_text)
    if getattr(self, "research_summary_label", None) is not None:
        self.research_summary_label.setText(summary_text)
    if getattr(self, "research_trace_label", None) is not None:
        compact_trace = trace_text
        if compact_trace and compact_trace == summary_text:
            compact_trace = ""
        if compact_trace and len(trace_rows) == 1 and trace_rows[0] == summary_text:
            compact_trace = ""
        self.research_trace_label.setVisible(bool(compact_trace))
        self.research_trace_label.setText(compact_trace)
    if getattr(self, "research_feed_list", None) is not None:
        self.research_feed_list.clear()
        for row in feed_rows[:4]:
            self.research_feed_list.addItem(QListWidgetItem(row))
    if getattr(self, "research_meta_label", None) is not None:
        trust_level = str(pulse.get("trust_level") or "").strip().lower()
        if trust_level:
            self.research_meta_label.setText(
                f"Updated {pulse.get('updated_at') or '--'} | trust {trust_level.upper()} | cautions {limitations_count}"
            )
        else:
            self.research_meta_label.setText(f"Updated {pulse.get('updated_at') or '--'} | cautions {limitations_count}")
    if getattr(self, "research_signal_meter", None) is not None:
        self.research_signal_meter.set_report(
            mode=str(pulse.get("mode") or "standby"),
            sources_count=sources_count,
            limitations_count=limitations_count,
        )
    if hasattr(self, "refresh_research_studio"):
        try:
            self.refresh_research_studio()
        except Exception:
            pass
    if getattr(self, "metrics_label", None) is not None:
        self.update_top_strip()

def update_clock(self):
    now = datetime.now().astimezone()
    self.state["system_time_str"] = now.strftime("%a %d %b %Y | %H:%M:%S")
    tz = now.tzname() or "Local"
    self.state["timezone"] = tz if len(tz) <= 14 else tz.split(" ", 1)[0]
    self.time_label.setText(f"{self.state['system_time_str']} ({self.state['timezone']})")
    self.update_presence()
    self.update_top_strip()
    self._sync_gateway_status()

def update_heartbeat_label(self):
    label = self.heartbeat_bridge.get_label_text()
    compact = label if len(label) <= 44 else f"{label[:41]}..."
    self.heartbeat_label.setText(compact)
    self.heartbeat_label.setToolTip(self.heartbeat_bridge.get_status_tooltip())

def poll_heartbeat_events(self):
    events = self.heartbeat_bridge.poll_events()
    for event in events:
        title = event.get("title", "Heartbeat event")
        detail = event.get("detail")
        level = str(event.get("level", "INFO")).lower()
        message = f"{title}: {detail}" if detail and title != "Heartbeat steady" else title
        self.push_activity("heartbeat", message, level="warn" if level == "warn" else "info")

        if self.heartbeat_stream_list is not None:
            stamp = str(event.get("ts") or datetime.now().strftime("%H:%M:%S"))
            item_text = f"[{stamp}] {message}"
            self.heartbeat_stream_list.addItem(QListWidgetItem(item_text))
            while self.heartbeat_stream_list.count() > 120:
                self.heartbeat_stream_list.takeItem(0)
            self.heartbeat_stream_list.scrollToBottom()

def _sync_gateway_status(self, force=False):
    gateway_service = getattr(self, "gateway_service", None)
    gateway_session = getattr(self, "gateway_session", {}) or {}
    if gateway_service is None or not gateway_session:
        return

    now_ts = datetime.now().timestamp()
    last_sync = float(getattr(self, "_last_gateway_sync_ts", 0.0) or 0.0)
    if not force and (now_ts - last_sync) < 8.0:
        return

    try:
        hb_status = self.heartbeat_service.get_status()
        hb_state = dict(hb_status.get("state") or {})
    except Exception:
        hb_state = {}

    if bool(hb_state.get("paused", False)):
        health_state = "paused"
    elif int(hb_state.get("error_count", 0) or 0) > 0:
        health_state = "alert"
    elif int(hb_state.get("warn_count", 0) or 0) > 0:
        health_state = "watch"
    else:
        health_state = "steady"

    try:
        gateway_service.touch_session(
            str(gateway_session.get("session_id") or ""),
            status="online",
            metadata={"window_title": "SOMI", "timezone": str(self.state.get("timezone") or "")},
        )
        gateway_service.update_presence(
            session_id=str(gateway_session.get("session_id") or ""),
            status="online",
            activity=str((self.state.get("activity_events") or [{}])[-1].get("message") if self.state.get("activity_events") else "Standing by"),
            detail=str(self.heartbeat_bridge.get_label_text() or "Heartbeat steady"),
            metadata={
                "activity_count": int(len(self.state.get("activity_events") or [])),
                "model_name": str(self.state.get("model_name") or ""),
            },
        )
        gateway_service.record_health(
            service_id="desktop-core",
            surface="gui",
            status=health_state,
            summary=str(self.heartbeat_bridge.get_label_text() or "Heartbeat steady"),
            metadata={
                "last_action": str(hb_state.get("last_action") or "Idle"),
                "warn_count": int(hb_state.get("warn_count", 0) or 0),
                "error_count": int(hb_state.get("error_count", 0) or 0),
            },
        )
        self._last_gateway_sync_ts = now_ts
    except Exception:
        pass

def _heartbeat_goal_nudge_provider(self):
    try:
        return self.memory3.list_active_goals_sync("default_user", scope="task", limit=1)
    except Exception:
        return []

def _heartbeat_due_reminders_provider(self):
    try:
        return self.memory3.consume_due_reminders_sync("default_user", limit=3)
    except Exception:
        return []

def _heartbeat_automation_provider(self):
    try:
        return self.automation_engine.run_due()
    except Exception:
        return []

def refresh_heartbeat_diagnostics(self):
    status = self.heartbeat_service.get_status()
    state = status.get("state", {})
    events = status.get("events", [])[-10:]
    lines = [
        "Heartbeat Diagnostics",
        f"Mode: {state.get('mode', 'MONITOR')}",
        f"Running: {state.get('running', False)}",
        f"Paused: {state.get('paused', False)}",
        f"Last action: {state.get('last_action', 'Idle')}",
        "Recent events:",
    ]
    for event in events:
        lines.append(f"- {event.get('ts', '')} [{event.get('level', 'INFO')}] {event.get('title', '')}")
    if state.get("last_greeting_date"):
        lines.append(f"Morning brief ready: {state.get('last_greeting_date')}")
    if state.get("last_weather_check_ts"):
        lines.append(f"Last weather check: {state.get('last_weather_check_ts')}")
    if state.get("last_weather_warning_ts"):
        lines.append(f"Last weather warning: {state.get('last_weather_warning_ts')}")
    if state.get("last_delight_ts"):
        lines.append(f"Last delight: {state.get('last_delight_ts')}")
    if state.get("last_agentpedia_run_ts"):
        lines.append(f"Last Agentpedia run: {state.get('last_agentpedia_run_ts')}")
    if state.get("last_agentpedia_topic"):
        lines.append(f"Last Agentpedia topic: {state.get('last_agentpedia_topic')}")
    if state.get("last_agentpedia_role"):
        lines.append(f"Last Agentpedia role: {state.get('last_agentpedia_role')}")
    if state.get("last_agentpedia_style"):
        lines.append(f"Last Agentpedia style: {state.get('last_agentpedia_style')}")
    configured_role = getattr(self.heartbeat_service.settings_module, "CAREER_ROLE", None)
    lines.append(f"Configured Career Role: {configured_role or 'General'}")
    lines.append(f"Agentpedia facts: {state.get('agentpedia_facts_count', 0)}")
    if state.get("last_agentpedia_error"):
        lines.append(f"Agentpedia error: {state.get('last_agentpedia_error')}")
    if state.get("last_error"):
        lines.append(f"Last error: {state['last_error']}")
    self.diag_text.setPlainText("\n".join(lines))

def pause_heartbeat(self):
    self.heartbeat_service.pause()

def resume_heartbeat(self):
    self.heartbeat_service.resume()

def update_top_strip(self):
    model_name = str(self.read_settings().get("DEFAULT_MODEL", "--"))
    self.state["model_name"] = model_name
    self.chips_label.setText(
        f"Core online | Model {model_name} | Memory {self.state['memory_status']} | Speech {self.state['speech_status']} | Scene {self.state['background_status']}"
    )
    w = self.state["weather"]
    n = self.state["news"]
    f = self.state["finance_news"]
    r = self.state["reminders"]
    pulse = dict(self.state.get("research_pulse") or {})
    browse_badge = self._research_mode_badge(pulse.get("mode"))
    browse_sources = int(pulse.get("sources_count") or 0)
    pulse_epoch = float(pulse.get("updated_epoch") or 0.0)
    pulse_recent = pulse_epoch and (datetime.now().timestamp() - pulse_epoch) < (15 * 60)
    browse_segment = f"Browse {browse_badge}/{browse_sources}" if pulse_recent and browse_badge != "STANDBY" else "Browse standby"
    self.metrics_label.setText(
        f"Weather {w['emoji']} {w['temp']} | News {n['count']} | Markets {f['count']} | {browse_segment} | Reminders {r['due_count']}"
    )

def update_presence(self):
    hour = datetime.now().hour
    greeting = "Good evening" if hour >= 18 else "Good afternoon" if hour >= 12 else "Good morning"
    self.greeting_label.setText(f"{greeting}. Prime console is standing by.")
    if self.state["activity_events"]:
        last = self.state["activity_events"][-1]
        self.last_interaction_label.setText(f"Latest activity: {last['message']}")
    if self.state["reminders"]["due_count"]:
        self.urgent_line_label.setText(f"Attention: {self.state['reminders']['due_count']} reminder(s) due soon.")
    elif self.state["weather"]["line"] != "Weather unavailable":
        self.urgent_line_label.setText(f"Sky: {self.state['weather']['line']}")
    elif self.state["finance_news"]["headlines"]:
        self.urgent_line_label.setText(f"Market pulse: {self.state['finance_news']['headlines'][0]}")
    else:
        self.urgent_line_label.setText("No urgent items right now.")

def _build_intel_items(self):
    items: list[str] = []
    w = self.state["weather"]
    n = self.state["news"]
    f = self.state["finance_news"]
    d = self.state["developments"]
    r = self.state["reminders"]

    if w.get("line"):
        items.append(f"Weather: {w['line']}")
    if n.get("headlines"):
        items.append(f"General: {n['headlines'][0]}")
    if f.get("headlines"):
        items.append(f"Finance: {f['headlines'][0]}")
    if d.get("headlines"):
        items.append(f"Development: {d['headlines'][0]}")
    if r.get("due_count"):
        items.append(f"Reminder nudge: {r['due_count']} due | next {r['next_due']}")

    hb = self.heartbeat_label.text().replace("Heartbeat:", "").strip()
    if hb:
        items.append(f"Heartbeat {hb}")

    profile = load_assistant_profile(str(ASSISTANT_PROFILE_PATH))
    focus_domains = [str(x).strip() for x in profile.get("focus_domains", []) if str(x).strip()]
    if focus_domains:
        items.append(f"Focus: {random.choice(focus_domains)}")

    pulse = dict(self.state.get("research_pulse") or {})
    pulse_query = str(pulse.get("query") or "").strip()
    if pulse_query:
        badge = self._research_mode_badge(pulse.get("mode"))
        items.append(f"Research {badge}: {pulse_query}")
        if pulse.get("progress_headline"):
            items.append(f"Research trace: {pulse['progress_headline']}")

    items.append(f"Fact: {random.choice(FACTS)}")
    items.append(f"{random.choice(JOKES)}")
    items.append(f"{random.choice(DEV_UPDATES)}")

    # Deduplicate while preserving order.
    seen = set()
    deduped = []
    for item in items:
        key = item.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped or ["SOMI telemetry nominal."]

def rotate_intel(self):
    if self.intel_paused:
        return

    items = self._build_intel_items()
    self.intel_index = (self.intel_index + 1) % len(items)
    next_text = items[self.intel_index]

    self.intel_anim.stop()
    previous_swap = getattr(self, "_intel_swap_text_callback", None)
    if previous_swap is not None:
        try:
            self.intel_anim.finished.disconnect(previous_swap)
        except Exception:
            pass
        self._intel_swap_text_callback = None
    self.intel_anim.setStartValue(1.0)
    self.intel_anim.setEndValue(0.22)

    def swap_text():
        self.intel_text.setText(next_text)
        try:
            self.intel_anim.finished.disconnect(swap_text)
        except Exception:
            pass
        self._intel_swap_text_callback = None
        self.intel_anim.setStartValue(0.22)
        self.intel_anim.setEndValue(1.0)
        self.intel_anim.start()

    self._intel_swap_text_callback = swap_text
    self.intel_anim.finished.connect(swap_text)
    self.intel_anim.start()

def update_stream_meters(self):
    state = self.heartbeat_service.get_status().get("state", {})
    warnings = int(state.get("warn_count", 0) or 0)
    errors = int(state.get("error_count", 0) or 0)
    paused = bool(state.get("paused", False))

    if paused:
        hb_state = "PAUSED"
    elif errors > 0:
        hb_state = "ALERT"
    elif warnings > 0:
        hb_state = "WATCH"
    else:
        hb_state = "STEADY"

    model_name = str(self.state.get("model_name") or self.read_settings().get("DEFAULT_MODEL", "--"))
    model_short = model_name.split(":", 1)[0]

    signal_sources = 0
    if self.state.get("weather", {}).get("line") and self.state.get("weather", {}).get("line") != "Weather unavailable":
        signal_sources += 1
    if self.state.get("news", {}).get("headlines"):
        signal_sources += 1
    if self.state.get("finance_news", {}).get("headlines"):
        signal_sources += 1
    if self.state.get("developments", {}).get("headlines"):
        signal_sources += 1

    pulse = dict(self.state.get("research_pulse") or {})
    pulse_epoch = float(pulse.get("updated_epoch") or 0.0)
    if pulse_epoch and (datetime.now().timestamp() - pulse_epoch) < (15 * 60):
        search_mode = self._research_mode_badge(pulse.get("mode"))
    else:
        search_mode = "LIVE" if signal_sources >= 2 else "HYBRID" if signal_sources == 1 else "LOCAL"

    task_mode = "MONITOR"
    try:
        if self.chat_worker and self.chat_worker.isRunning():
            task_mode = "RESPOND" if self.chat_worker.is_busy() else "CHAT"
    except Exception:
        task_mode = "CHAT"

    if getattr(self, "tabs", None) is not None:
        cur_tab = self.tabs.tabText(self.tabs.currentIndex())
        if cur_tab in {"Toolbox", "Executive"}:
            task_mode = "CODING"

    if self.stream_orbit is not None:
        self.stream_orbit.set_values(model_short, search_mode, task_mode, hb_state)

    chips = getattr(self, "stream_status_chips", {}) or {}
    if chips:
        if chips.get("model") is not None:
            chips["model"].setText(f"Model: {model_short[:14]}")
        if chips.get("search") is not None:
            chips["search"].setText(f"Search: {search_mode}")
        if chips.get("heartbeat") is not None:
            chips["heartbeat"].setText(f"Heartbeat: {hb_state}")
        if chips.get("task") is not None:
            chips["task"].setText(f"Task: {task_mode}")

def capture_output_events(self):
    lines = [l for l in self.output_area.toPlainText().splitlines() if l.strip()]
    if len(lines) <= self.last_console_line_count:
        return
    new_lines = lines[self.last_console_line_count :]
    self.last_console_line_count = len(lines)
    for line in new_lines[-6:]:
        plain = line[-180:]
        lowered = plain.lower()
        if "stored memory" in lowered:
            self.push_activity("memory", "Stored memory")
        elif "starting telegram bot" in lowered:
            self.push_activity("module", "Started Telegram bot")
        elif "telegram bot stopped" in lowered:
            self.push_activity("module", "Stopped Telegram bot")
        elif "starting twitter autotweet" in lowered:
            self.push_activity("module", "Started Twitter auto-tweet")
        elif "twitter autotweet stopped" in lowered:
            self.push_activity("module", "Stopped Twitter auto-tweet")
        elif "starting ollama" in lowered:
            self.push_activity("core", "AI model online")
        elif "ollama stopped" in lowered:
            self.push_activity("core", "AI model offline")
        else:
            self.push_activity("console", plain)
