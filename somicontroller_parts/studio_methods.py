from __future__ import annotations

"""Extracted SomiAIGUI methods from somicontroller.py (studio_methods.py)."""

import os
import subprocess
import sys

from gui.codingstudio import CodingStudioWindow


def build_control_room_panel(self):
    self.control_room_panel = ControlRoomPanel(self, snapshot_builder=self.control_room_builder)
    return self.control_room_panel


def build_research_studio_panel(self):
    self.research_studio_panel = ResearchStudioPanel(self, snapshot_builder=self.research_studio_builder)
    return self.research_studio_panel


def build_node_manager_panel(self):
    self.node_manager_panel = NodeManagerPanel(self, snapshot_builder=self.node_manager_builder)
    return self.node_manager_panel


def open_control_room(self):
    if getattr(self, "tabs", None) is None:
        return
    panel = getattr(self, "control_room_panel", None)
    if panel is None:
        return
    idx = self.tabs.indexOf(panel)
    if idx >= 0:
        self.tabs.setCurrentIndex(idx)
    try:
        panel.refresh_data()
    except Exception:
        pass


def open_research_studio(self):
    if getattr(self, "tabs", None) is None:
        return
    panel = getattr(self, "research_studio_panel", None)
    if panel is None:
        return
    idx = self.tabs.indexOf(panel)
    if idx >= 0:
        self.tabs.setCurrentIndex(idx)
    try:
        panel.refresh_data()
    except Exception:
        pass


def open_node_manager(self):
    if getattr(self, "tabs", None) is None:
        return
    panel = getattr(self, "node_manager_panel", None)
    if panel is None:
        return
    idx = self.tabs.indexOf(panel)
    if idx >= 0:
        self.tabs.setCurrentIndex(idx)
    try:
        panel.refresh_data()
    except Exception:
        pass


def refresh_control_room(self):
    panel = getattr(self, "control_room_panel", None)
    if panel is None:
        return
    try:
        panel.refresh_data()
    except Exception:
        pass


def refresh_research_studio(self):
    panel = getattr(self, "research_studio_panel", None)
    if panel is not None:
        try:
            panel.refresh_data()
        except Exception:
            pass


def refresh_node_manager(self):
    panel = getattr(self, "node_manager_panel", None)
    if panel is not None:
        try:
            panel.refresh_data()
        except Exception:
            pass


def ensure_coding_session(self, objective="", source="gui", force_open=False):
    service = getattr(self, "coding_service", None)
    if service is None:
        raise RuntimeError("Coding service is not configured")
    coding_user_id = str(getattr(self, "coding_user_id", "default_user") or "default_user").strip() or "default_user"
    snapshot = service.open_session(
        user_id=coding_user_id,
        source=str(source or "gui"),
        objective=str(objective or ""),
        metadata={"trigger": str(source or "gui"), "entrypoint": str(source or "gui"), "force_open": bool(force_open)},
        resume_active=True,
    )
    return dict(snapshot or {})


def open_coding_studio(self):
    snapshot = self.ensure_coding_session(source="gui_button", force_open=False)
    if getattr(self, "coding_studio_window", None) is None:
        self.coding_studio_window = CodingStudioWindow(self, snapshot_builder=self.coding_studio_builder, parent=self)
    self.coding_studio_window.show()
    self.coding_studio_window.raise_()
    self.coding_studio_window.activateWindow()
    try:
        self.coding_studio_window.refresh_data()
    except Exception:
        pass
    try:
        self.refresh_coding_studio()
    except Exception:
        pass
    self.push_activity("coding", f"Opened coding studio ({snapshot.get('session_id') or '--'})")


def refresh_coding_studio(self):
    window = getattr(self, "coding_studio_window", None)
    if window is not None:
        try:
            window.refresh_data()
        except Exception:
            pass
    toolbox_panel = getattr(self, "toolbox_panel", None)
    if toolbox_panel is not None and hasattr(toolbox_panel, "refresh_data"):
        try:
            toolbox_panel.refresh_data()
        except Exception:
            pass


def _coding_runtime_ctx(self, *, operation_mode="read", approved=True, max_risk_tier="MEDIUM"):
    return {
        "approved": bool(approved),
        "channel": "gui",
        "backend": "local",
        "operation_mode": str(operation_mode or "read"),
        "max_risk_tier": str(max_risk_tier or "MEDIUM"),
        "user_id": str(getattr(self, "coding_user_id", "default_user") or "default_user").strip() or "default_user",
    }


def run_coding_profile_check(self):
    snapshot = self.ensure_coding_session(source="gui_check")
    result = self.toolbox_runtime.run(
        "coding.runtime",
        {"action": "run_profile_check", "session_id": str(snapshot.get("session_id") or "")},
        self._coding_runtime_ctx(operation_mode="execute", approved=True, max_risk_tier="MEDIUM"),
    )
    self.push_activity("coding", f"Profile check: {result.get('ok')}")
    self.refresh_coding_studio()
    return result


def run_coding_verify_loop(self):
    snapshot = self.ensure_coding_session(source="gui_verify")
    result = self.toolbox_runtime.run(
        "coding.runtime",
        {"action": "run_verify_loop", "session_id": str(snapshot.get("session_id") or "")},
        self._coding_runtime_ctx(operation_mode="execute", approved=True, max_risk_tier="MEDIUM"),
    )
    scorecard = dict(result.get("scorecard") or {})
    self.push_activity("coding", f"Verify loop: {scorecard.get('status') or result.get('ok')}")
    self.refresh_coding_studio()
    return result


def bootstrap_coding_workspace(self):
    snapshot = self.ensure_coding_session(source="gui_bootstrap")
    result = self.toolbox_runtime.run(
        "coding.scaffold",
        {"action": "bootstrap_profile", "session_id": str(snapshot.get("session_id") or "")},
        self._coding_runtime_ctx(operation_mode="write", approved=True, max_risk_tier="MEDIUM"),
    )
    self.push_activity("coding", f"Workspace bootstrap: {result.get('ok')}")
    self.refresh_coding_studio()
    return result


def draft_coding_skill(self):
    snapshot = self.ensure_coding_session(source="gui_skill_draft")
    metadata = dict(snapshot.get("metadata") or {})
    hint = dict(metadata.get("skill_expansion") or {})
    capability = str(hint.get("capability") or "specialized coding capability").strip() or "specialized coding capability"
    skill_name = str(hint.get("skill_name") or capability.title()).strip() or capability.title()
    description = str(hint.get("description") or f"Draft skill for {capability}").strip()
    result = self.toolbox_runtime.run(
        "coding.scaffold",
        {
            "action": "draft_skill",
            "skill_name": skill_name,
            "description": description,
            "capability": capability,
            "objective": str(snapshot.get("objective") or ""),
        },
        self._coding_runtime_ctx(operation_mode="write", approved=True, max_risk_tier="MEDIUM"),
    )
    self.push_activity("coding", f"Skill draft created: {result.get('skill_key') or '--'}")
    self.refresh_coding_studio()
    return result


def open_coding_workspace_folder(self):
    snapshot = self.ensure_coding_session(source="gui_folder")
    workspace = dict(snapshot.get("workspace") or {})
    root_path = str(workspace.get("root_path") or "").strip()
    if not root_path:
        return {"ok": False, "error": "No coding workspace is active."}
    if os.name == "nt":
        os.startfile(root_path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", root_path], shell=False)
    else:
        subprocess.Popen(["xdg-open", root_path], shell=False)
    self.push_activity("coding", f"Opened workspace folder: {root_path}")
    return {"ok": True, "workspace_root": root_path}


def send_coding_prompt(self, prompt):
    text = str(prompt or "").strip()
    if not text:
        return "No coding prompt provided."
    snapshot = self.ensure_coding_session(objective=text, source="gui_coding_prompt", force_open=True)
    use_studies = True
    panel = getattr(self, "chat_panel", None)
    try:
        use_studies = bool(panel.use_studies_check.isChecked()) if panel is not None else True
    except Exception:
        use_studies = True
    self.ensure_chat_worker_running(use_studies=use_studies)
    worker = getattr(self, "chat_worker", None)
    if worker is None or not worker.isRunning():
        return "Chat worker is not available for coding mode."
    if worker.is_busy():
        return "Chat worker is busy. Stop the current response first."
    payload = text if text.lower().startswith("/code") else f"/code {text}"
    worker.process_prompt(payload, display_prompt=text)
    self.push_activity("coding", f"Sent coding prompt: {text[:80]}")
    self.refresh_coding_studio()
    return f"Sent to coding chat for session {snapshot.get('session_id') or '--'}."
