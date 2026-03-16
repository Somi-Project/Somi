from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_FILE = Path("sessions/security/runtime_secrets.json")
SECRET_SPECS: dict[str, dict[str, str]] = {
    "audit_hmac": {
        "env": "SOMI_AUDIT_SECRET",
        "setting": "AUDIT_HMAC_SECRET",
        "label": "Audit HMAC",
    },
    "approval": {
        "env": "SOMI_APPROVAL_SECRET",
        "setting": "",
        "label": "Approval",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root_dir(root_dir: str | Path | None = None) -> Path:
    if root_dir is not None:
        return Path(root_dir).resolve()
    env_root = str(os.getenv("SOMI_ROOT_DIR", "") or os.getenv("SOMI_RUNTIME_ROOT", "")).strip()
    if env_root:
        return Path(env_root).resolve()
    return Path.cwd().resolve()


def _secret_path(root_dir: str | Path | None = None) -> Path:
    return _root_dir(root_dir) / SECRET_FILE


def _load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "generated_at": "", "updated_at": "", "secrets": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "generated_at": "", "updated_at": "", "secrets": {}}
    payload = dict(raw) if isinstance(raw, dict) else {}
    payload["secrets"] = dict(payload.get("secrets") or {})
    payload.setdefault("version", 1)
    payload.setdefault("generated_at", "")
    payload.setdefault("updated_at", "")
    return payload


def _write_store(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _setting_secret(setting_name: str) -> str:
    if not str(setting_name or "").strip():
        return ""
    try:
        from config import settings as settings_module

        return str(getattr(settings_module, setting_name, "") or "").strip()
    except Exception:
        return ""


def resolve_runtime_secret(
    kind: str,
    *,
    root_dir: str | Path | None = None,
    create: bool = False,
) -> dict[str, Any]:
    spec = dict(SECRET_SPECS.get(str(kind or "").strip().lower()) or {})
    if not spec:
        raise KeyError(f"Unknown runtime secret kind: {kind}")

    env_name = str(spec.get("env") or "")
    setting_name = str(spec.get("setting") or "")
    path = _secret_path(root_dir)
    env_secret = str(os.getenv(env_name, "") or "").strip()
    if env_secret:
        return {
            "kind": str(kind),
            "label": str(spec.get("label") or kind),
            "present": True,
            "source": "env",
            "env": env_name,
            "path": str(path),
            "secret": env_secret,
        }

    setting_secret = _setting_secret(setting_name)
    if setting_secret:
        return {
            "kind": str(kind),
            "label": str(spec.get("label") or kind),
            "present": True,
            "source": "setting",
            "env": env_name,
            "setting": setting_name,
            "path": str(path),
            "secret": setting_secret,
        }

    store = _load_store(path)
    stored = dict(store.get("secrets") or {}).get(str(kind), {})
    persisted = str(dict(stored or {}).get("value") or "").strip()
    if persisted:
        return {
            "kind": str(kind),
            "label": str(spec.get("label") or kind),
            "present": True,
            "source": "persisted",
            "env": env_name,
            "setting": setting_name,
            "path": str(path),
            "created_at": str(dict(stored or {}).get("created_at") or ""),
            "secret": persisted,
        }

    if not create:
        return {
            "kind": str(kind),
            "label": str(spec.get("label") or kind),
            "present": False,
            "source": "missing",
            "env": env_name,
            "setting": setting_name,
            "path": str(path),
            "secret": "",
        }

    now = _now_iso()
    value = secrets.token_urlsafe(48)
    secrets_map = dict(store.get("secrets") or {})
    secrets_map[str(kind)] = {
        "value": value,
        "created_at": now,
        "label": str(spec.get("label") or kind),
    }
    store["secrets"] = secrets_map
    store["generated_at"] = str(store.get("generated_at") or now)
    store["updated_at"] = now
    _write_store(path, store)
    return {
        "kind": str(kind),
        "label": str(spec.get("label") or kind),
        "present": True,
        "source": "generated",
        "env": env_name,
        "setting": setting_name,
        "path": str(path),
        "created_at": now,
        "secret": value,
    }


def get_runtime_secret(
    kind: str,
    *,
    root_dir: str | Path | None = None,
    create: bool = False,
) -> str:
    return str(resolve_runtime_secret(kind, root_dir=root_dir, create=create).get("secret") or "")


def runtime_secret_status(
    *,
    root_dir: str | Path | None = None,
    create: bool = False,
) -> dict[str, Any]:
    rows = [
        {
            key: value
            for key, value in resolve_runtime_secret(kind, root_dir=root_dir, create=create).items()
            if key != "secret"
        }
        for kind in sorted(SECRET_SPECS)
    ]
    return {
        "root_dir": str(_root_dir(root_dir)),
        "path": str(_secret_path(root_dir)),
        "secrets": rows,
    }
