from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from gui.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QTimer,
    QVBoxLayout,
)
from gui.themes import dialog_stylesheet
from speech.doctor import run_speech_doctor


def _append_console(app, message: str) -> None:
    area = getattr(app, "output_area", None)
    if area is None:
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    area.append(f"[{stamp}] {message}")
    try:
        area.ensureCursorVisible()
    except Exception:
        pass


def speech_runtime_active(app) -> bool:
    process = getattr(app, "alex_process", None)
    return bool(process and process.poll() is None)


def _speech_python_executable() -> str:
    candidate = Path(".venv") / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _build_run_speech_command(
    *,
    agent_key: str,
    use_studies: bool,
    os_profile: str,
    input_device: str = "",
    output_device: str = "",
) -> list[str]:
    cmd = [_speech_python_executable(), "-m", "speech.tools.run_speech", "--agent-name", str(agent_key), "--os-profile", str(os_profile)]
    if use_studies:
        cmd.append("--use-studies")
    if str(input_device or "").strip():
        cmd.extend(["--input-device", str(input_device).strip()])
    if str(output_device or "").strip():
        cmd.extend(["--output-device", str(output_device).strip()])
    return cmd


def _read_process_output(process, output_queue: queue.Queue[str]) -> None:
    while True:
        line = process.stdout.readline()
        if line:
            output_queue.put(str(line).rstrip())
            continue
        break


def _drain_process_output(app, output_queue: queue.Queue[str]) -> None:
    try:
        while not output_queue.empty():
            line = output_queue.get_nowait()
            _append_console(app, f"Speech runtime: {line}")
    except queue.Empty:
        pass


def stop_speech_runtime(app, *, show_dialog: bool = False) -> bool:
    process = getattr(app, "alex_process", None)
    if not process or process.poll() is not None:
        return False

    try:
        termination_signal = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM
        os.kill(process.pid, termination_signal)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    except Exception as exc:
        _append_console(app, f"Speech runtime stop failed: {type(exc).__name__}: {exc}")
        if show_dialog:
            QMessageBox.critical(app, "Speech Error", f"Failed to stop speech runtime: {exc}")
        return False

    timer = getattr(app, "alex_timer", None)
    if timer is not None:
        timer.stop()
        app.alex_timer = None
    app.alex_process = None
    _append_console(app, "Speech runtime stopped.")
    return True


def _start_speech_runtime(
    app,
    *,
    agent_key: str,
    use_studies: bool,
    os_profile: str,
    input_device: str = "",
    output_device: str = "",
    show_dialogs: bool = False,
) -> bool:
    if speech_runtime_active(app):
        return True

    cmd = _build_run_speech_command(
        agent_key=agent_key,
        use_studies=use_studies,
        os_profile=os_profile,
        input_device=input_device,
        output_device=output_device,
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SOMI_SPEECH_OS_PROFILE"] = str(os_profile or "auto")
    if str(input_device or "").strip():
        env["SOMI_SPEECH_INPUT_DEVICE"] = str(input_device).strip()
    else:
        env.pop("SOMI_SPEECH_INPUT_DEVICE", None)
    if str(output_device or "").strip():
        env["SOMI_SPEECH_OUTPUT_DEVICE"] = str(output_device).strip()
    else:
        env.pop("SOMI_SPEECH_OUTPUT_DEVICE", None)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            universal_newlines=True,
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except Exception as exc:
        _append_console(app, f"Speech runtime failed to start: {type(exc).__name__}: {exc}")
        if show_dialogs:
            QMessageBox.critical(app, "Speech Error", f"Failed to start speech runtime: {exc}")
        return False

    app.speech_os_profile = str(os_profile or "auto")
    app.speech_input_device = str(input_device or "")
    app.speech_output_device = str(output_device or "")
    app.alex_process = process
    app.alex_stderr_queue = queue.Queue()
    threading.Thread(target=_read_process_output, args=(process, app.alex_stderr_queue), daemon=True).start()
    app.alex_timer = QTimer(app)
    app.alex_timer.timeout.connect(lambda: _drain_process_output(app, app.alex_stderr_queue))
    app.alex_timer.start(120)
    _append_console(app, f"Speech runtime started with agent {agent_key.replace('Name: ', '')}.")
    return True


def _format_speech_report(report: dict) -> str:
    settings = dict(report.get("settings") or {})
    audio = dict(report.get("audio") or {})
    recommended = dict(report.get("recommended") or {})
    providers = dict(report.get("providers") or {})
    lines = [
        "Speech Doctor",
        f"Status: {'ready' if report.get('ok') else 'issues detected'}",
        f"Recommended TTS: {recommended.get('tts_provider') or '--'}",
        f"Recommended STT: {recommended.get('stt_provider') or '--'}",
        f"Sample rate: {settings.get('sample_rate')}",
        f"Frame size: {settings.get('frame_ms')} ms",
        f"Audio devices: inputs={audio.get('input_count', 0)} outputs={audio.get('output_count', 0)}",
        "",
        "Providers:",
    ]
    for key, payload in providers.items():
        state = "ready" if payload.get("available") or payload.get("reachable") else "unavailable"
        detail = payload.get("error") or payload.get("model") or payload.get("status") or ""
        line = f"- {key}: {state}"
        if detail:
            line += f" ({detail})"
        lines.append(line)
    warnings = list(report.get("warnings") or [])
    errors = list(report.get("errors") or [])
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings)
    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {item}" for item in errors)
    return "\n".join(lines).strip()


def _run_speech_tool(app, module_name: str, *, extra_args: list[str] | None = None) -> str:
    cmd = [_speech_python_executable(), "-m", module_name, *(extra_args or [])]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, shell=False)
    output = str(proc.stdout or proc.stderr or "").strip()
    _append_console(app, f"{module_name}: {output or f'exit={proc.returncode}'}")
    return output or f"exit={proc.returncode}"


def open_speech_control(app) -> None:
    dialog = QDialog(app)
    dialog.setWindowTitle("Speech Control")
    dialog.resize(760, 620)
    dialog.setStyleSheet(dialog_stylesheet())
    layout = QVBoxLayout(dialog)

    title = QLabel("Speech Runtime")
    title.setObjectName("dialogTitle")
    subtitle = QLabel("Local-first voice control for diagnostics, playback smoke tests, and live speech runtime launch.")
    subtitle.setObjectName("dialogSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(subtitle)

    agent_row = QHBoxLayout()
    agent_row.addWidget(QLabel("Agent"))
    name_combo = QComboBox()
    name_combo.addItems(getattr(app, "agent_names", []))
    selected = str(getattr(app, "_selected_agent_name", lambda: "")() or "")
    if selected and selected in getattr(app, "agent_names", []):
        name_combo.setCurrentText(selected)
    agent_row.addWidget(name_combo, 1)
    use_studies_check = QCheckBox("Use Studies (RAG)")
    use_studies_check.setChecked(True)
    agent_row.addWidget(use_studies_check)
    layout.addLayout(agent_row)

    profile_row = QHBoxLayout()
    profile_row.addWidget(QLabel("OS Profile"))
    os_profile_combo = QComboBox()
    os_profile_combo.addItems(["auto", "windows", "mac", "linux"])
    os_profile_combo.setCurrentText(str(getattr(app, "speech_os_profile", "auto") or "auto"))
    profile_row.addWidget(os_profile_combo, 1)
    layout.addLayout(profile_row)

    input_row = QHBoxLayout()
    input_row.addWidget(QLabel("Input Device"))
    input_device_edit = QLineEdit(str(getattr(app, "speech_input_device", "") or ""))
    input_row.addWidget(input_device_edit, 1)
    layout.addLayout(input_row)

    output_row = QHBoxLayout()
    output_row.addWidget(QLabel("Output Device"))
    output_device_edit = QLineEdit(str(getattr(app, "speech_output_device", "") or ""))
    output_row.addWidget(output_device_edit, 1)
    layout.addLayout(output_row)

    report_box = QTextEdit()
    report_box.setReadOnly(True)
    report_box.setMinimumHeight(320)
    layout.addWidget(report_box, 1)

    button_row = QHBoxLayout()
    refresh_button = QPushButton("Refresh Doctor")
    test_tts_button = QPushButton("Test Voice")
    test_stt_button = QPushButton("Test STT")
    start_stop_button = QPushButton("Stop Runtime" if speech_runtime_active(app) else "Start Runtime")
    close_button = QPushButton("Close")
    for button in [refresh_button, test_tts_button, test_stt_button, start_stop_button, close_button]:
        button_row.addWidget(button)
    layout.addLayout(button_row)

    def refresh_report() -> None:
        report = run_speech_doctor()
        report_box.setPlainText(_format_speech_report(report))
        start_stop_button.setText("Stop Runtime" if speech_runtime_active(app) else "Start Runtime")

    def test_tts() -> None:
        output = _run_speech_tool(app, "speech.tools.test_tts_local", extra_args=["--play"])
        QMessageBox.information(dialog, "Speech Test", output)
        refresh_report()

    def test_stt() -> None:
        output = _run_speech_tool(app, "speech.tools.test_stt_local", extra_args=["--roundtrip"])
        QMessageBox.information(dialog, "Speech Test", output)
        refresh_report()

    def toggle_runtime() -> None:
        if speech_runtime_active(app):
            stop_speech_runtime(app, show_dialog=True)
            refresh_report()
            return

        selected_name = name_combo.currentText().strip()
        try:
            agent_key = app.agent_keys[app.agent_names.index(selected_name)]
        except Exception:
            QMessageBox.critical(dialog, "Speech Error", "Invalid or missing agent selection.")
            return

        started = _start_speech_runtime(
            app,
            agent_key=agent_key,
            use_studies=use_studies_check.isChecked(),
            os_profile=os_profile_combo.currentText().strip() or "auto",
            input_device=input_device_edit.text().strip(),
            output_device=output_device_edit.text().strip(),
            show_dialogs=True,
        )
        if started:
            QMessageBox.information(dialog, "Speech Runtime", "Speech runtime started.")
        refresh_report()

    refresh_button.clicked.connect(refresh_report)
    test_tts_button.clicked.connect(test_tts)
    test_stt_button.clicked.connect(test_stt)
    start_stop_button.clicked.connect(toggle_runtime)
    close_button.clicked.connect(dialog.close)

    refresh_report()
    dialog.exec()


def toggle_speech_runtime(app) -> bool:
    if speech_runtime_active(app):
        stop_speech_runtime(app, show_dialog=False)
    else:
        open_speech_control(app)
    return speech_runtime_active(app)


def alex_ai_toggle(app):
    return toggle_speech_runtime(app)


def audio_settings(app):
    open_speech_control(app)
