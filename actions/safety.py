from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from actions.audit import AuditLogger


RiskClass = str
READ: RiskClass = "read"
WRITE: RiskClass = "write"
SEND: RiskClass = "send"
EXECUTE: RiskClass = "execute"
DELETE: RiskClass = "delete"
EXTERNAL: RiskClass = "external"


SummaryBuilder = Callable[[dict], str]


@dataclass(frozen=True)
class ToolRiskPolicy:
    tool_name: str
    risk_class: RiskClass
    requires_approval: bool = False
    audit_required: bool = False
    description: str = ""
    summary_builder: SummaryBuilder | None = None
    unknown: bool = False

    def summary(self, args: dict, fallback: str = "") -> str:
        if fallback:
            return fallback
        if self.summary_builder:
            try:
                value = self.summary_builder(args or {})
                if value:
                    return value
            except Exception:
                pass
        return self.description or f"{self.tool_name} calistir"


@dataclass
class PendingAction:
    action_id: str
    action_type: str
    summary: str
    runner: Callable[[], str]
    tool_name: str = ""
    risk_class: RiskClass = EXECUTE
    args: dict = field(default_factory=dict)
    created_at: str = ""
    audit_logger: AuditLogger | None = None
    run_id: str = ""


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _arg(name: str, default: str = "") -> SummaryBuilder:
    return lambda args: str(args.get(name, default) or default)


def _summary(label: str, *arg_names: str) -> SummaryBuilder:
    def build(args: dict) -> str:
        parts = [str(args.get(name, "") or "").strip() for name in arg_names]
        detail = " -> ".join(part for part in parts if part)
        return f"{label}: {detail}" if detail else label

    return build


def _whatsapp_policy(args: dict) -> ToolRiskPolicy:
    if bool(args.get("send_now", False)):
        return ToolRiskPolicy(
            "send_whatsapp_message",
            SEND,
            requires_approval=True,
            audit_required=True,
            summary_builder=lambda a: f"WhatsApp mesaji gonder: {a.get('recipient_name') or a.get('phone_number') or 'bilinmeyen kisi'} -> {str(a.get('message') or '')[:120]}",
        )
    return ToolRiskPolicy(
        "send_whatsapp_message",
        EXTERNAL,
        requires_approval=False,
        audit_required=False,
        summary_builder=lambda a: f"WhatsApp taslagi hazirla: {a.get('recipient_name') or a.get('phone_number') or 'bilinmeyen kisi'}",
    )


def _plugin_tool_policy(args: dict) -> ToolRiskPolicy:
    if not str(args.get("plugin_id", "") or "").strip() and not str(args.get("tool_name", "") or "").strip():
        return ToolRiskPolicy(
            "call_plugin_tool",
            EXECUTE,
            requires_approval=True,
            audit_required=True,
            summary_builder=lambda _a: "Plugin tool gateway; risk manifest/discovery bilgisine gore belirlenir",
        )
    try:
        from actions.plugin_system import plugin_tool_policy

        details = plugin_tool_policy(args.get("plugin_id", ""), args.get("tool_name", ""))
    except Exception as exc:
        details = {
            "blocked": True,
            "risk_class": EXECUTE,
            "requires_approval": True,
            "summary": f"Plugin policy okunamadi: {type(exc).__name__}: {exc}",
        }
    return ToolRiskPolicy(
        "call_plugin_tool",
        str(details.get("risk_class") or EXECUTE),
        requires_approval=bool(details.get("requires_approval", True)),
        audit_required=True,
        summary_builder=lambda _a: str(details.get("summary") or "Plugin tool calistir"),
        unknown=bool(details.get("blocked", False)),
    )


TOOL_RISK_REGISTRY: dict[str, ToolRiskPolicy] = {
    # read
    "sys_info": ToolRiskPolicy("sys_info", READ, summary_builder=_summary("Sistem bilgisi al", "query")),
    "get_calendar_events": ToolRiskPolicy("get_calendar_events", READ, summary_builder=_summary("Takvim oku", "query")),
    "get_reminders": ToolRiskPolicy("get_reminders", READ, summary_builder=_summary("Animsaticilari oku", "query")),
    "calendar_auth_status": ToolRiskPolicy("calendar_auth_status", READ, summary_builder=lambda _a: "Takvim OAuth durumunu al"),
    "list_calendars": ToolRiskPolicy("list_calendars", READ, summary_builder=_summary("Takvimleri listele", "provider")),
    "find_whatsapp_contact": ToolRiskPolicy("find_whatsapp_contact", READ, summary_builder=_summary("WhatsApp kisisi ara", "query")),
    "list_whatsapp_contacts": ToolRiskPolicy("list_whatsapp_contacts", READ, summary_builder=_summary("WhatsApp kisilerini listele", "source_filter")),
    "list_folder": ToolRiskPolicy("list_folder", READ, summary_builder=_summary("Klasor listele", "path")),
    "find_files": ToolRiskPolicy("find_files", READ, summary_builder=_summary("Dosya ara", "query", "path")),
    "read_text_file": ToolRiskPolicy("read_text_file", READ, summary_builder=_summary("Dosya oku", "path")),
    "summarize_text_file": ToolRiskPolicy("summarize_text_file", READ, summary_builder=_summary("Dosya ozetle", "path")),
    "get_clipboard": ToolRiskPolicy("get_clipboard", READ, summary_builder=lambda _a: "Panoyu oku"),
    "summarize_clipboard": ToolRiskPolicy("summarize_clipboard", READ, summary_builder=lambda _a: "Panoyu ozetle"),
    "get_selected_text": ToolRiskPolicy("get_selected_text", READ, summary_builder=lambda _a: "Secili metni oku"),
    "summarize_selected_text": ToolRiskPolicy("summarize_selected_text", READ, summary_builder=lambda _a: "Secili metni ozetle"),
    "active_window_info": ToolRiskPolicy("active_window_info", READ, summary_builder=lambda _a: "Aktif pencere bilgisi al"),
    "list_windows": ToolRiskPolicy("list_windows", READ, summary_builder=_summary("Pencereleri listele", "query")),
    "search_memory": ToolRiskPolicy("search_memory", READ, summary_builder=_summary("Hafizada ara", "query")),
    "list_memory": ToolRiskPolicy("list_memory", READ, summary_builder=_summary("Hafizayi listele", "kind")),
    "memory_status": ToolRiskPolicy("memory_status", READ, summary_builder=lambda _a: "Hafiza durumunu al"),
    "pending_action_status": ToolRiskPolicy("pending_action_status", READ, summary_builder=lambda _a: "Onay bekleyen islemi sor"),
    "audit_status": ToolRiskPolicy("audit_status", READ, summary_builder=lambda _a: "Audit durumunu al"),
    "tool_risk_status": ToolRiskPolicy("tool_risk_status", READ, summary_builder=_summary("Tool risk durumunu al", "tool_name")),
    "local_ai_status": ToolRiskPolicy("local_ai_status", READ, summary_builder=lambda _a: "Yerel AI durumunu al"),
    "voice_experience_status": ToolRiskPolicy("voice_experience_status", READ, summary_builder=lambda _a: "Ses deneyimi durumunu al"),
    "list_plugins": ToolRiskPolicy("list_plugins", READ, summary_builder=lambda _a: "Pluginleri listele"),
    "plugin_status": ToolRiskPolicy("plugin_status", READ, summary_builder=_summary("Plugin durumunu al", "plugin_id")),
    "startup_tracking_status": ToolRiskPolicy("startup_tracking_status", READ, summary_builder=lambda _a: "Baslangic takip durumunu al"),
    "list_tasks": ToolRiskPolicy("list_tasks", READ, summary_builder=_summary("Gorevleri listele", "status_filter")),
    # external read/open
    "get_weather": ToolRiskPolicy("get_weather", EXTERNAL, summary_builder=_summary("Hava durumu al", "location")),
    "browser_control": ToolRiskPolicy("browser_control", EXTERNAL, summary_builder=_summary("Tarayici kontrolu", "action", "url", "query")),
    "browser_read_url": ToolRiskPolicy("browser_read_url", EXTERNAL, summary_builder=_summary("BrowserAgent URL oku", "url")),
    "browser_research": ToolRiskPolicy("browser_research", EXTERNAL, summary_builder=_summary("BrowserAgent arastir", "query")),
    "play_media": ToolRiskPolicy("play_media", EXTERNAL, summary_builder=_summary("Medya ac", "query", "provider")),
    "get_youtube_channel_report": ToolRiskPolicy("get_youtube_channel_report", EXTERNAL, summary_builder=_summary("YouTube raporu al", "query", "handle")),
    "analyze_screen": ToolRiskPolicy("analyze_screen", READ, summary_builder=_summary("Ekran analiz et", "query")),
    "web_search": ToolRiskPolicy("web_search", EXTERNAL, summary_builder=_summary("Web aramasi ac", "query")),
    "open_and_summarize_url": ToolRiskPolicy("open_and_summarize_url", EXTERNAL, summary_builder=_summary("URL ac ve ozetle", "url")),
    "research_web": ToolRiskPolicy("research_web", EXTERNAL, summary_builder=_summary("Web arastir", "query")),
    "answer_research_question": ToolRiskPolicy("answer_research_question", EXTERNAL, summary_builder=_summary("Arastirma sorusu yanitla", "query")),
    "tavily_search": ToolRiskPolicy("tavily_search", EXTERNAL, summary_builder=_summary("Tavily arastir", "query")),
    "browse_url": ToolRiskPolicy("browse_url", EXTERNAL, summary_builder=_summary("URL gez", "url", "question")),
    "test_local_ai": ToolRiskPolicy("test_local_ai", EXTERNAL, summary_builder=lambda _a: "Yerel AI endpointini test et"),
    "discover_plugin_tools": ToolRiskPolicy("discover_plugin_tools", EXTERNAL, audit_required=True, summary_builder=_summary("Plugin MCP tool kesfi yap", "plugin_id")),
    "open_file": ToolRiskPolicy("open_file", EXECUTE, audit_required=True, summary_builder=_summary("Dosya/klasor ac", "path")),
    "open_app": ToolRiskPolicy("open_app", EXECUTE, audit_required=True, summary_builder=_summary("Uygulama ac", "app_name")),
    "focus_window": ToolRiskPolicy("focus_window", EXECUTE, audit_required=True, summary_builder=_summary("Pencere odakla", "query")),
    # write
    "set_clipboard": ToolRiskPolicy("set_clipboard", WRITE, requires_approval=True, audit_required=True, summary_builder=lambda a: f"Panoya yaz: {str(a.get('text') or '')[:120]}"),
    "create_folder": ToolRiskPolicy("create_folder", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Klasor olustur", "path")),
    "create_text_file": ToolRiskPolicy("create_text_file", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Metin dosyasi olustur", "path")),
    "write_text_file": ToolRiskPolicy("write_text_file", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Dosyaya yaz", "path")),
    "append_text_file": ToolRiskPolicy("append_text_file", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Dosyaya ekle", "path")),
    "move_file": ToolRiskPolicy("move_file", DELETE, requires_approval=True, audit_required=True, summary_builder=_summary("Tasi/yeniden adlandir", "source_path", "destination_path")),
    "add_calendar_event": ToolRiskPolicy("add_calendar_event", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Takvim etkinligi ekle", "title", "start_iso")),
    "add_reminder": ToolRiskPolicy("add_reminder", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Animsatici ekle", "title", "due_iso")),
    "connect_calendar_provider": ToolRiskPolicy("connect_calendar_provider", WRITE, audit_required=True, summary_builder=_summary("Takvim OAuth baglantisi baslat/tamamla", "provider", "mode")),
    "set_agent_mode": ToolRiskPolicy("set_agent_mode", WRITE, audit_required=True, summary_builder=_summary("Ajan model modunu ayarla", "mode")),
    "set_voice_mode": ToolRiskPolicy("set_voice_mode", WRITE, audit_required=True, summary_builder=_summary("Ses modunu ayarla", "mode")),
    "enable_plugin": ToolRiskPolicy("enable_plugin", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Plugin ac", "plugin_id")),
    "set_plugin_config": ToolRiskPolicy("set_plugin_config", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("Plugin config kaydet", "plugin_id")),
    "create_followup_task": ToolRiskPolicy("create_followup_task", WRITE, audit_required=True, summary_builder=_summary("Takip gorevi olustur", "title", "query")),
    "save_memory": ToolRiskPolicy("save_memory", WRITE, audit_required=True, summary_builder=_summary("Hafizaya kaydet", "category", "key")),
    "remember_file_note": ToolRiskPolicy("remember_file_note", WRITE, audit_required=True, summary_builder=_summary("Dosya notu kaydet", "path")),
    "save_whatsapp_contact": ToolRiskPolicy("save_whatsapp_contact", WRITE, audit_required=True, summary_builder=_summary("WhatsApp kisisi kaydet", "display_name", "phone_number")),
    "import_phone_book_from_vcf": ToolRiskPolicy("import_phone_book_from_vcf", WRITE, requires_approval=True, audit_required=True, summary_builder=_summary("VCF rehberi ice aktar", "vcf_path")),
    # send / execute / delete
    "browser_click": ToolRiskPolicy("browser_click", EXECUTE, requires_approval=True, audit_required=True, summary_builder=_summary("Tarayicida tikla", "selector_or_text")),
    "browser_fill": ToolRiskPolicy("browser_fill", WRITE, requires_approval=True, audit_required=True, summary_builder=lambda a: f"Tarayicida form alani doldur: {a.get('selector_or_label') or ''} -> {str(a.get('value') or '')[:120]}"),
    "browser_submit": ToolRiskPolicy("browser_submit", SEND, requires_approval=True, audit_required=True, summary_builder=_summary("Tarayicida form gonder", "selector_or_text")),
    "shell_run": ToolRiskPolicy("shell_run", EXECUTE, requires_approval=True, audit_required=True, summary_builder=_summary("Terminal komutu calistir", "command")),
    "send_hotkey_safe": ToolRiskPolicy("send_hotkey_safe", EXECUTE, requires_approval=True, audit_required=True, summary_builder=_summary("Aktif pencereye kisayol gonder", "hotkey")),
    "delete_file": ToolRiskPolicy("delete_file", DELETE, requires_approval=True, audit_required=True, summary_builder=lambda a: f"Sil: {a.get('path') or ''}" + (" (recursive)" if a.get("recursive") else "")),
    "delete_calendar_event": ToolRiskPolicy("delete_calendar_event", DELETE, requires_approval=True, audit_required=True, summary_builder=_summary("Takvim etkinligi sil", "title", "start_iso")),
    "complete_reminder": ToolRiskPolicy("complete_reminder", DELETE, requires_approval=True, audit_required=True, summary_builder=_summary("Animsatici tamamla", "reminder_id", "title")),
    "delete_reminder": ToolRiskPolicy("delete_reminder", DELETE, requires_approval=True, audit_required=True, summary_builder=_summary("Animsatici sil", "reminder_id", "title")),
    "disconnect_calendar_provider": ToolRiskPolicy("disconnect_calendar_provider", DELETE, requires_approval=True, audit_required=True, summary_builder=_summary("Takvim OAuth baglantisini kaldir", "provider")),
    "disable_plugin": ToolRiskPolicy("disable_plugin", DELETE, audit_required=True, summary_builder=_summary("Plugin kapat", "plugin_id")),
    "delete_memory": ToolRiskPolicy("delete_memory", DELETE, audit_required=True, summary_builder=_summary("Hafizadan sil", "category", "key", "match_text")),
    "cancel_task": ToolRiskPolicy("cancel_task", DELETE, audit_required=True, summary_builder=_summary("Gorev iptal et", "task_id")),
    "run_task_now": ToolRiskPolicy("run_task_now", EXECUTE, audit_required=True, summary_builder=_summary("Gorevi hemen calistir", "task_id")),
    "enable_startup_tracking": ToolRiskPolicy("enable_startup_tracking", EXECUTE, requires_approval=True, audit_required=True, summary_builder=lambda _a: "Windows baslangicinda JARVIS takip sistemini ac"),
    "disable_startup_tracking": ToolRiskPolicy("disable_startup_tracking", DELETE, requires_approval=True, audit_required=True, summary_builder=lambda _a: "Windows baslangicinda JARVIS takip sistemini kapat"),
    "approve_pending_action": ToolRiskPolicy("approve_pending_action", EXECUTE, audit_required=True, summary_builder=lambda _a: "Bekleyen islemi onayla"),
    "cancel_pending_action": ToolRiskPolicy("cancel_pending_action", DELETE, audit_required=True, summary_builder=lambda _a: "Bekleyen islemi iptal et"),
}


def classify_tool(tool_name: str, args: dict | None = None) -> ToolRiskPolicy:
    name = str(tool_name or "").strip()
    if name == "send_whatsapp_message":
        return _whatsapp_policy(args or {})
    if name == "call_plugin_tool":
        return _plugin_tool_policy(args or {})
    policy = TOOL_RISK_REGISTRY.get(name)
    if policy:
        return policy
    return ToolRiskPolicy(
        name or "unknown",
        EXECUTE,
        requires_approval=True,
        audit_required=True,
        description=f"Bilinmeyen arac calistirma engellendi: {name or '-'}",
        unknown=True,
    )


def tool_risk_status(tool_name: str = "") -> str:
    if tool_name:
        policy = classify_tool(tool_name, {})
        if policy.unknown:
            return f"{tool_name}: registry disi, varsayilan risk={policy.risk_class}, durum=blocked"
        approval = "onayli" if policy.requires_approval else "onaysiz"
        audit = "audit" if policy.audit_required else "audit yok"
        return f"{policy.tool_name}: risk={policy.risk_class}, {approval}, {audit}"
    lines = ["Tool risk registry:"]
    for name in sorted(TOOL_RISK_REGISTRY):
        policy = classify_tool(name, {})
        approval = "approval" if policy.requires_approval else "direct"
        audit = "audit" if policy.audit_required else "no-audit"
        lines.append(f"- {name}: {policy.risk_class}, {approval}, {audit}")
    return "\n".join(lines)


def guard_tool_call(
    tool_name: str,
    args: dict | None,
    runner: Callable[[], str],
    pending_actions: "PendingActionManager",
    audit_logger: AuditLogger | None = None,
    run_id: str = "",
    summary_override: str = "",
) -> str:
    policy = classify_tool(tool_name, args or {})
    summary = policy.summary(args or {}, summary_override)
    if policy.unknown:
        if audit_logger:
            audit_logger.log(
                "blocked",
                run_id=run_id,
                tool_name=policy.tool_name,
                risk_class=policy.risk_class,
                args=args or {},
                summary=summary,
                status="blocked",
            )
        return f"Guvenlik: Registry disi arac engellendi: {tool_name}. {summary}"

    if policy.requires_approval:
        return pending_actions.request(
            policy.risk_class,
            summary,
            runner,
            tool_name=tool_name,
            risk_class=policy.risk_class,
            args=args or {},
            audit_logger=audit_logger,
            run_id=run_id,
        )

    try:
        result = runner()
        if policy.audit_required and audit_logger:
            audit_logger.log(
                "executed",
                run_id=run_id,
                tool_name=tool_name,
                risk_class=policy.risk_class,
                args=args or {},
                summary=summary,
                result=str(result),
                status="executed",
            )
        return result
    except Exception as exc:
        if policy.audit_required and audit_logger:
            audit_logger.log(
                "failed",
                run_id=run_id,
                tool_name=tool_name,
                risk_class=policy.risk_class,
                args=args or {},
                summary=summary,
                result=f"{type(exc).__name__}: {exc}",
                status="failed",
            )
        raise


class PendingActionManager:
    def __init__(self):
        self._pending: PendingAction | None = None
        self._counter = 0

    def request(
        self,
        action_type: str,
        summary: str,
        runner: Callable[[], str],
        *,
        tool_name: str = "",
        risk_class: RiskClass = EXECUTE,
        args: dict | None = None,
        audit_logger: AuditLogger | None = None,
        run_id: str = "",
    ) -> str:
        self._counter += 1
        action_id = f"act-{self._counter}"
        pending = PendingAction(
            action_id=action_id,
            action_type=action_type,
            summary=summary,
            runner=runner,
            tool_name=tool_name or action_type,
            risk_class=risk_class or action_type,
            args=args or {},
            created_at=_now_iso(),
            audit_logger=audit_logger,
            run_id=run_id,
        )
        self._pending = pending
        if audit_logger:
            audit_logger.log(
                "requested",
                run_id=run_id,
                action_id=action_id,
                tool_name=pending.tool_name,
                risk_class=pending.risk_class,
                args=pending.args,
                summary=summary,
                status="waiting_approval",
            )
        return (
            f"Onay gerekiyor ({action_id}) [{pending.risk_class}/{pending.tool_name}]: {summary}\n"
            "Devam etmek icin 'onayla', iptal etmek icin 'iptal' yaz."
        )

    def has_pending(self) -> bool:
        return self._pending is not None

    def describe(self) -> str:
        if not self._pending:
            return "Onay bekleyen islem yok."
        pending = self._pending
        return (
            f"Onay bekleyen islem ({pending.action_id}) "
            f"[{pending.risk_class}/{pending.tool_name}]: {pending.summary}"
        )

    def cancel(self) -> str:
        if not self._pending:
            return "Onay bekleyen islem yok."
        pending = self._pending
        self._pending = None
        if pending.audit_logger:
            pending.audit_logger.log(
                "cancelled",
                run_id=pending.run_id,
                action_id=pending.action_id,
                tool_name=pending.tool_name,
                risk_class=pending.risk_class,
                args=pending.args,
                summary=pending.summary,
                status="cancelled",
            )
        return f"Iptal edildi ({pending.action_id}) [{pending.risk_class}/{pending.tool_name}]: {pending.summary}"

    def approve(self) -> str:
        if not self._pending:
            return "Onay bekleyen islem yok."
        pending = self._pending
        self._pending = None
        if pending.audit_logger:
            pending.audit_logger.log(
                "approved",
                run_id=pending.run_id,
                action_id=pending.action_id,
                tool_name=pending.tool_name,
                risk_class=pending.risk_class,
                args=pending.args,
                summary=pending.summary,
                status="approved",
            )
        try:
            result = pending.runner()
            if pending.audit_logger:
                pending.audit_logger.log(
                    "executed",
                    run_id=pending.run_id,
                    action_id=pending.action_id,
                    tool_name=pending.tool_name,
                    risk_class=pending.risk_class,
                    args=pending.args,
                    summary=pending.summary,
                    result=result,
                    status="executed",
                )
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if pending.audit_logger:
                pending.audit_logger.log(
                    "failed",
                    run_id=pending.run_id,
                    action_id=pending.action_id,
                    tool_name=pending.tool_name,
                    risk_class=pending.risk_class,
                    args=pending.args,
                    summary=pending.summary,
                    result=error,
                    status="failed",
                )
            return f"Onayli islem calistirilamadi: {error}"


def is_approval_text(text: str) -> bool:
    normalized = (text or "").strip().casefold()
    return normalized in {
        "onayla",
        "onay",
        "evet",
        "tamam",
        "devam",
        "calistir",
        "çalıştır",
        "Ã§alÄ±ÅŸtÄ±r",
        "gonder",
        "gönder",
        "gÃ¶nder",
    }


def is_cancel_text(text: str) -> bool:
    normalized = (text or "").strip().casefold()
    return normalized in {"iptal", "vazgec", "vazgeç", "vazgeÃ§", "hayir", "hayır", "hayÄ±r", "dur"}
