from __future__ import annotations

from dataclasses import dataclass

from actions.audit import AuditLogger
from actions.plugin_system import get_plugin_registry


@dataclass(frozen=True)
class PluginPermission:
    name: str
    allowed: bool
    reason: str


PLUGIN_ALLOWLIST: set[str] = set()
SKILL_ALLOWLIST: set[str] = set()


def check_plugin_permission(name: str, kind: str = "plugin", audit_logger: AuditLogger | None = None, run_id: str = "") -> PluginPermission:
    clean = str(name or "").strip()
    if kind == "plugin":
        try:
            state = get_plugin_registry().load_state()
            plugin_state = state.get("plugins", {}).get(clean, {})
            enabled = bool(plugin_state.get("enabled"))
        except Exception:
            enabled = False
        allowed = bool(clean and (clean in PLUGIN_ALLOWLIST or enabled))
    else:
        allowed = bool(clean and clean in SKILL_ALLOWLIST)
    reason = "allowlist veya plugin state icinde" if allowed else f"{kind} allowlist disinda"
    if not allowed and audit_logger:
        audit_logger.log(
            "blocked",
            run_id=run_id,
            tool_name=f"{kind}:{clean or '-'}",
            risk_class="execute",
            args={"name": clean, "kind": kind},
            summary=f"{kind} calistirma engellendi: {clean or '-'}",
            status="blocked",
        )
    return PluginPermission(clean, allowed, reason)
