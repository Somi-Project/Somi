from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from gateway import DeliveryGateway, DeliveryMessage
from ontology import SomiOntology
from ontology.schema import OntologyLink, OntologyObject
from search import SessionSearchService

from .models import AutomationRun, AutomationSpec
from .nlp import compute_next_run, parse_schedule_text
from .store import AutomationStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationEngine:
    def __init__(
        self,
        *,
        store: AutomationStore | None = None,
        gateway: DeliveryGateway | None = None,
        session_search: SessionSearchService | None = None,
        ontology: SomiOntology | None = None,
        timezone_name: str = "UTC",
    ) -> None:
        self.store = store or AutomationStore()
        self.gateway = gateway or DeliveryGateway()
        self.session_search = session_search or SessionSearchService()
        self.ontology = ontology
        self.timezone_name = str(timezone_name or "UTC")

    def create_automation(
        self,
        *,
        name: str,
        user_id: str,
        schedule_text: str,
        channel: str = "desktop",
        automation_type: str = "session_digest",
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        schedule = parse_schedule_text(schedule_text, timezone_name=self.timezone_name, now=now)
        spec = AutomationSpec(
            automation_id=str(uuid.uuid4()),
            user_id=str(user_id),
            name=str(name),
            automation_type=str(automation_type),
            target_channel=str(channel),
            schedule=schedule,
            payload=dict(payload or {}),
        )
        saved = self.store.upsert_automation(spec)
        self._sync_ontology(saved)
        return saved

    def _sync_ontology(self, automation: dict[str, Any]) -> None:
        if self.ontology is None:
            return
        automation_id = str(automation.get("automation_id") or "")
        user_id = str(automation.get("user_id") or "")
        channel_name = str(automation.get("target_channel") or "desktop")
        if not automation_id or not user_id:
            return
        self.ontology.store.upsert_object(
            OntologyObject(
                object_id=f"automation:{automation_id}",
                kind="Automation",
                label=str(automation.get("name") or automation_id),
                status=str(automation.get("status") or "active"),
                owner_user_id=user_id,
                thread_id="",
                source="automations",
                attributes={
                    "automation_type": str(automation.get("automation_type") or ""),
                    "target_channel": channel_name,
                    "next_run_at": str(automation.get("next_run_at") or ""),
                },
            )
        )
        self.ontology.store.upsert_object(
            OntologyObject(
                object_id=f"channel:{channel_name}",
                kind="Channel",
                label=channel_name,
                status="enabled" if channel_name == "desktop" else "queued",
                owner_user_id=user_id,
                thread_id="",
                source="automations",
                attributes={},
            )
        )
        self.ontology.store.upsert_link(
            OntologyLink(
                from_id=f"user:{user_id}",
                relation="owns_automation",
                to_id=f"automation:{automation_id}",
                owner_user_id=user_id,
                thread_id="",
            )
        )
        self.ontology.store.upsert_link(
            OntologyLink(
                from_id=f"automation:{automation_id}",
                relation="delivers_to",
                to_id=f"channel:{channel_name}",
                owner_user_id=user_id,
                thread_id="",
            )
        )

    def _render_output(self, automation: dict[str, Any]) -> str:
        automation_type = str(automation.get("automation_type") or "session_digest")
        payload = dict(automation.get("payload") or {})
        user_id = str(automation.get("user_id") or "")
        if automation_type == "session_digest":
            query = str(payload.get("query") or "What did we decide recently?")
            days = int(payload.get("days") or 7)
            thread_id = payload.get("thread_id")
            limit = int(payload.get("limit") or 5)
            return self.session_search.answer_recall(query, user_id=user_id, thread_id=thread_id, limit=limit, days=days)
        if automation_type == "note":
            return str(payload.get("message") or "")
        raise ValueError(f"Unsupported automation type: {automation_type}")

    def run_automation(self, automation_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        automation = self.store.get_automation(str(automation_id))
        if not automation:
            raise ValueError(f"Unknown automation: {automation_id}")
        if str(automation.get("status") or "").lower() != "active":
            raise ValueError(f"Automation is not active: {automation_id}")

        now_dt = now or _utc_now()
        output_text = self._render_output(automation)
        message = DeliveryMessage(
            user_id=str(automation.get("user_id") or ""),
            channel=str(automation.get("target_channel") or "desktop"),
            title=str(automation.get("name") or "Automation"),
            body=output_text,
            metadata={
                "automation_id": str(automation.get("automation_id") or ""),
                "automation_type": str(automation.get("automation_type") or ""),
            },
        )
        receipt = self.gateway.deliver(str(automation.get("target_channel") or "desktop"), message)
        run = self.store.record_run(
            AutomationRun(
                run_id=str(uuid.uuid4()),
                automation_id=str(automation.get("automation_id") or ""),
                user_id=str(automation.get("user_id") or ""),
                status="completed",
                target_channel=str(automation.get("target_channel") or "desktop"),
                delivery_status=str(receipt.status),
                output_text=output_text,
                metadata={"receipt": receipt.to_record()},
                created_at=now_dt.astimezone(timezone.utc).isoformat(),
                completed_at=now_dt.astimezone(timezone.utc).isoformat(),
            )
        )

        schedule = dict(automation.get("schedule") or {})
        schedule_spec = parse_schedule_text(
            str(schedule.get("source_text") or ""),
            timezone_name=str(schedule.get("timezone") or self.timezone_name),
            now=now_dt,
        )
        next_run_at = compute_next_run(schedule_spec, after_dt=now_dt)
        self.store.update_schedule(
            str(automation.get("automation_id") or ""),
            next_run_at=next_run_at,
            last_run_at=now_dt.astimezone(timezone.utc).isoformat(),
        )
        updated = self.store.get_automation(str(automation.get("automation_id") or "")) or automation
        self._sync_ontology(updated)
        return {"automation": updated, "run": run, "receipt": receipt.to_record()}

    def run_due(self, *, now: datetime | None = None, limit: int = 10) -> list[dict[str, Any]]:
        now_dt = now or _utc_now()
        due = self.store.due_automations(now_iso=now_dt.astimezone(timezone.utc).isoformat(), limit=limit)
        results = []
        for automation in due:
            results.append(self.run_automation(str(automation.get("automation_id") or ""), now=now_dt))
        return results

    def render_status_page(self, *, user_id: str, limit: int = 10) -> str:
        automations = self.store.list_automations(user_id=str(user_id), limit=limit)
        runs = self.store.list_runs(user_id=str(user_id), limit=limit)
        lines = ["[Automation Status]"]
        if not automations:
            lines.append("- No automations configured.")
            return "\n".join(lines)
        for row in automations:
            lines.append(
                f"- {row.get('name')} | status={row.get('status')} | channel={row.get('target_channel')} | next={row.get('next_run_at') or 'unscheduled'}"
            )
        if runs:
            lines.append("")
            lines.append("Recent runs:")
            for row in runs[: max(1, int(limit))]:
                lines.append(f"- {row.get('created_at')} | {row.get('delivery_status')} | {row.get('output_text')[:120]}")
        return "\n".join(lines)
