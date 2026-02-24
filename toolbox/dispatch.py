from __future__ import annotations

from datetime import datetime, timezone

from runtime.approval import ApprovalReceipt
from runtime.capabilities import CAP_TOOL_RUN, require_cap
from runtime.errors import VerifyError
from runtime.privilege import PrivilegeLevel, require_privilege
from runtime.ratelimit import SlidingRateLimit
from runtime.risk import assess
from runtime.ticketing import ticket_hash
from toolbox.loader import ToolLoader
from toolbox.registry import ToolRegistry


class ToolboxDispatch:
    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.loader = ToolLoader(self.registry)
        self.ratelimit = SlidingRateLimit(20, 60)

    def resolve(self, query: str) -> dict | None:
        q = query.lower().strip()
        if not q:
            return None
        for t in self.registry.list_tools():
            names = (
                [t.get("name", "")]
                + t.get("aliases", [])
                + t.get("tags", [])
                + t.get("examples", [])
            )
            if any(q in str(n).lower() for n in names):
                return t
        return None

    def _validate_args(self, entry: dict, args: dict) -> None:
        schema = entry.get("input_schema") or {}
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        required = set(schema.get("required") or [])
        if not isinstance(args, dict):
            raise VerifyError("Tool args must be an object")
        missing = [k for k in required if k not in args]
        if missing:
            raise VerifyError(f"Missing required args: {', '.join(missing)}")
        if additional is False:
            unknown = [k for k in args.keys() if k not in props]
            if unknown:
                raise VerifyError(
                    f"Unknown args denied by schema: {', '.join(unknown)}"
                )

    def run(self, tool_name: str, args: dict, ctx):
        self.ratelimit.hit()
        require_cap(ctx, CAP_TOOL_RUN)
        require_privilege(ctx, PrivilegeLevel.SAFE)
        entry = self.registry.find(tool_name)
        if not entry:
            raise VerifyError(f"Tool not found: {tool_name}")
        self._validate_args(entry, args)
        ticket = self.loader.propose_exec(tool_name, args)
        risk = assess(ticket)
        return {
            "state": "AWAITING_APPROVAL",
            "ticket": ticket,
            "ticket_hash": ticket_hash(ticket),
            "risk": {
                "tier": risk.tier,
                "reasons": risk.reasons,
                "potential_outcomes": risk.potential_outcomes,
            },
            "approval_prompt": {
                "confirm_method": risk.required_confirm,
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def execute(self, ticket, receipt: ApprovalReceipt):
        return self.loader.execute_with_approval(ticket, receipt)
