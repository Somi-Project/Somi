from __future__ import annotations

import importlib
import importlib.util
import platform
from pathlib import Path
from typing import Any
from urllib import error, request

from speech.runtime_settings import load_speech_runtime_settings


def _module_status(module_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    return {"module": module_name, "available": bool(spec)}


def _http_reachable(url: str, timeout_s: float = 2.0) -> dict[str, Any]:
    text = str(url or "").strip()
    if not text:
        return {"configured": False, "reachable": False, "error": "missing_url"}
    try:
        req = request.Request(text, method="HEAD")
        with request.urlopen(req, timeout=timeout_s) as resp:
            return {"configured": True, "reachable": True, "status": int(getattr(resp, "status", 200) or 200)}
    except error.HTTPError as exc:
        # A 404/405 still proves the server answered, which is useful for doctor mode.
        return {"configured": True, "reachable": True, "status": int(getattr(exc, "code", 0) or 0)}
    except Exception as exc:
        return {"configured": True, "reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def _audio_devices_status() -> dict[str, Any]:
    try:
        devices_mod = importlib.import_module("speech.io.devices")
        devices = devices_mod.list_devices()
        inputs = [row for row in devices if int(row.get("max_input_channels", 0) or 0) > 0]
        outputs = [row for row in devices if int(row.get("max_output_channels", 0) or 0) > 0]
        return {
            "available": True,
            "device_count": len(devices),
            "input_count": len(inputs),
            "output_count": len(outputs),
            "default_input": devices_mod.default_device_for_kind("input"),
            "default_output": devices_mod.default_device_for_kind("output"),
        }
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _pyttsx3_status() -> dict[str, Any]:
    if not _module_status("pyttsx3")["available"]:
        return {"available": False, "voices": 0}
    try:
        pyttsx3 = importlib.import_module("pyttsx3")
        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
        rate = engine.getProperty("rate")
        volume = engine.getProperty("volume")
        try:
            engine.stop()
        except Exception:
            pass
        return {"available": True, "voices": len(voices), "rate": rate, "volume": volume}
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def recommended_tts_provider(report: dict[str, Any]) -> str:
    providers = dict(report.get("providers") or {})
    if dict(providers.get("pyttsx3") or {}).get("available"):
        return "pyttsx3"
    if dict(providers.get("piper") or {}).get("available"):
        return "piper"
    if dict(providers.get("pocket_server") or {}).get("reachable"):
        return "pocket_server"
    return "tone"


def recommended_stt_provider(report: dict[str, Any]) -> str:
    providers = dict(report.get("providers") or {})
    if dict(providers.get("whisper_local") or {}).get("available"):
        return "whisper_local"
    return "none"


def run_speech_doctor() -> dict[str, Any]:
    settings = load_speech_runtime_settings()
    deps = {
        name: _module_status(module_name)
        for name, module_name in {
            "sounddevice": "sounddevice",
            "soundfile": "soundfile",
            "pyttsx3": "pyttsx3",
            "faster_whisper": "faster_whisper",
            "PySide6.QtTextToSpeech": "PySide6.QtTextToSpeech",
        }.items()
    }
    providers = {
        "pyttsx3": _pyttsx3_status(),
        "piper": {
            "available": bool(settings.piper_model_path and Path(settings.piper_model_path).exists()),
            "model_path": settings.piper_model_path,
            "config_path": settings.piper_config_path,
        },
        "pocket_server": _http_reachable(settings.pocket_server_url),
        "whisper_local": {
            "available": bool(deps["faster_whisper"]["available"]),
            "model": settings.stt_model,
        },
    }
    audio = _audio_devices_status() if deps["sounddevice"]["available"] else {"available": False, "error": "sounddevice_missing"}

    warnings: list[str] = []
    errors: list[str] = []
    if not deps["sounddevice"]["available"]:
        errors.append("sounddevice is not installed")
    if not deps["pyttsx3"]["available"]:
        warnings.append("pyttsx3 is not installed, so offline speech synthesis is unavailable")
    if not providers["piper"]["available"] and settings.tts_provider == "piper":
        warnings.append("Piper is configured but the local model path does not exist")
    if not providers["pocket_server"].get("reachable") and settings.tts_provider == "pocket_server":
        warnings.append("Pocket server is configured but not reachable")
    if not deps["faster_whisper"]["available"]:
        warnings.append("faster-whisper is not installed, so local STT is unavailable")
    if audio.get("available") and int(audio.get("output_count", 0) or 0) <= 0:
        errors.append("No output audio device was detected")
    if audio.get("available") and int(audio.get("input_count", 0) or 0) <= 0:
        warnings.append("No input audio device was detected")

    report = {
        "ok": not errors,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "settings": settings.to_dict(),
        "dependencies": deps,
        "audio": audio,
        "providers": providers,
        "recommended": {
            "tts_provider": recommended_tts_provider({"providers": providers}),
            "stt_provider": recommended_stt_provider({"providers": providers}),
        },
        "warnings": warnings,
        "errors": errors,
    }
    return report
