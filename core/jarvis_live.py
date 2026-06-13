"""JarvisLive — main application controller for JARVIS desktop assistant.

Extracted from main.py to reduce file size and improve modularity.
Contains: token declarations, runtime class, tool dispatch, audio pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    import pyaudio
except Exception:
    pyaudio = None

from google import genai
from google.genai import types

from app_config import get_app_config_value, load_app_config, normalize_agent_mode, normalize_voice_mode
from core.agent_runtime import AgentRuntime
from core.logger import get_logger, LogContext
from core.trace import TraceManager
from ui import JarvisUI

from memory.memory_manager import (
    delete_memory,
    format_memory_for_prompt,
    list_memory,
    load_memory,
    memory_status,
    remember_file_note,
    search_memory,
    update_memory,
)
from memory.memory_store import (
    format_relevant_memories_for_prompt,
    infer_memory_from_text,
    save_conversation_summary,
)

from actions.open_app import open_app
from actions.sys_info import sys_info
from actions.calendar import get_calendar_events, add_calendar_event, delete_calendar_event
from actions.reminders import get_reminders, add_reminder, complete_reminder, delete_reminder
from actions.browser import browser_control
from actions.browser_agent import (
    browser_click,
    browser_fill,
    browser_read_url,
    browser_research,
    browser_submit,
)
from actions.shell import shell_run
from actions.whatsapp import (
    find_whatsapp_contact,
    import_phone_book_from_vcf,
    list_whatsapp_contacts,
    send_whatsapp_message,
    save_whatsapp_contact,
)
from actions.media import play_media
from actions.weather import get_weather_summary
from actions.screen_vision import analyze_screen
from actions.youtube_stats import get_youtube_channel_report
from actions.local_web import handle_local_web_command
from actions.local_tasks import handle_local_task_command
from actions.local_memory import handle_local_memory_command
from actions.logging_utils import safe_log_preview
from actions.smoke import build_timeout_report, run_smoke_sequence
from actions.documents import create_pdf, create_docx, create_xlsx, create_pptx, document_status
from actions.database import query_database, list_tables, database_status
from actions.network import ping_host, dns_lookup, http_check, network_status
from actions.tts import get_speech_controller
from actions.voice_control import (
    SpeechMemory,
    VoiceGate,
    parse_voice_control,
    set_voice_mode as set_voice_mode_config,
    voice_experience_status as build_voice_experience_status,
)
from actions.wake_word import WakeWordDetector, load_wake_word_config
from actions.files import (
    find_files,
    list_folder,
    read_text_file,
    summarize_text_file,
    open_file,
    create_folder,
    create_text_file,
    write_text_file,
    append_text_file,
    move_file,
    delete_file,
)
from actions.clipboard import (
    get_clipboard,
    set_clipboard,
    summarize_clipboard,
    get_selected_text,
    summarize_selected_text,
)
from actions.desktop import active_window_info, list_windows, focus_window, send_hotkey_safe
from actions.web_research import (
    web_search,
    open_and_summarize_url,
    research_web,
    browse_url,
    tavily_search,
    answer_research_question,
)
from actions.calendar_integrations import (
    calendar_auth_status,
    connect_calendar_provider,
    disconnect_calendar_provider,
    list_calendars,
)
from actions.audit import audit_status, set_audit_logger, get_audit_logger
from actions.safety import (
    classify_tool,
    guard_tool_call,
    is_approval_text,
    is_cancel_text,
    local_ai_status,
    test_local_ai,
    tool_risk_status,
    internet_available,
    LOCAL_AI_ONLY_TOOLS,
    OFFLINE_BLOCKED_TOOLS,
)
from actions.safety import PendingActionManager
from actions.tasks import (
    TaskScheduler,
    create_followup_task,
    list_tasks,
    cancel_task,
    run_task_now,
    startup_tracking_status,
    enable_startup_tracking,
    disable_startup_tracking,
)
from actions.plugins import (
    list_plugins,
    plugin_status,
    enable_plugin,
    disable_plugin,
    set_plugin_config,
    discover_plugin_tools,
    call_plugin_tool,
)
from actions.agent_config import cloud_agent_config, local_agent_config, local_agent_config_ready, set_agent_mode
from actions.windows_notify import notify_windows
from actions.audio_constants import FORMAT, CHANNELS, SEND_SAMPLE_RATE, RECV_SAMPLE_RATE, CHUNK_SIZE

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "jarvis_prompt.txt"
LIVE_MODEL = "models/gemini-2.0-flash-live-001"
CONTROL_TOKEN_RE = re.compile(r"\[[A-Z_]+\]")
RESEARCH_UI_STATES = {
    "research_web", "answer_research_question", "tavily_search",
    "browser_research", "browser_read_url", "browse_url", "open_and_summarize_url",
}


def get_api_key() -> str:
    return str(get_app_config_value("gemini_api_key", "") or "")


def load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Sen JARVIS'sin — Windows/macOS uzerinde calisan kisisel AI asistani. "
            "Türkçe konuş. Kısa ve net yanıtlar ver. "
            "Araçları kullanarak görevleri tamamla, asla taklit etme."
        )


# Tool declarations moved to core/tool_declarations.py
from core.tool_declarations import TOOL_DECLARATIONS


class JarvisLive:
    """Main application controller. Owns UI, audio pipeline, agent runtime, trace, and task scheduler."""

    def __init__(self, ui: JarvisUI | None = None, start_task_scheduler: bool = True):
        self.ui = ui or JarvisUI()
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self._loop = None
        self._is_speaking = False
        self._speaking_lock = threading.Lock()
        self._audio_input_available = True
        self._audio_output_available = True
        self._audio_notice_sent: set[str] = set()
        self._text_mode = False
        self._pyaudio = None
        self._pyaudio_lock = threading.Lock()
        self.speech = get_speech_controller()
        self.speech_memory = SpeechMemory()
        cfg = load_app_config()
        self.voice_gate = VoiceGate(mode=normalize_voice_mode(cfg.get("voice_input_mode", "ptt_wake")))
        self._wake_detector = WakeWordDetector(load_wake_word_config(cfg))
        self.audit_logger = get_audit_logger()
        self.pending_actions = PendingActionManager()
        self.trace = TraceManager(
            BASE_DIR / "memory" / "traces",
            debug_sink=lambda msg, level="INFO": self.ui.write_debug(msg, level=level),
        )
        self.agent_runtime = AgentRuntime(TOOL_DECLARATIONS, trace_manager=self.trace)
        self.task_scheduler = TaskScheduler(notify_callback=self._notify_task_result)
        if start_task_scheduler:
            self.task_scheduler.start()
        self._voice_run_id = ""
        self._paused = False
        self._audio_notice_cache: dict[str, float] = {}

        # Register UI callbacks
        self.ui.on_text_command = self._on_text_command
        self.ui.on_pause_toggle = self._on_pause_toggle
        self.ui.on_effects_state_change = self._on_effects_state_change
        self.ui.on_ptt_start = self._on_ptt_start
        self.ui.on_ptt_stop = self._on_ptt_stop
        self.ui.on_stop_command = self._on_stop_command
        self.ui.on_wake_toggle = self._on_wake_toggle

        self._sync_voice_ui()
        log.info("JarvisLive initialized")

    # ------------------------------------------------------------------ #
    # UI Callbacks
    # ------------------------------------------------------------------ #

    def _on_pause_toggle(self, paused: bool) -> None:
        self._paused = paused

    @staticmethod
    def _on_effects_state_change(_enabled: bool) -> None:
        pass

    def _sync_voice_ui(self) -> None:
        status = self._wake_detector.status() if self._wake_detector else ""
        if hasattr(self.ui, "set_text_mode"):
            self.ui.set_text_mode(self._text_mode)
        if hasattr(self.ui, "set_ptt_active"):
            self.ui.set_ptt_active(bool(self.voice_gate.ptt_active))
        if hasattr(self.ui, "set_wake_status"):
            self.ui.set_wake_status(
                bool(self._wake_detector and self._wake_detector.ready),
                status,
            )

    def _refresh_wake_detector(self) -> str:
        try:
            if self._wake_detector:
                self._wake_detector.close()
        except Exception:
            log.warning("Wake detector close failed", exc_info=True)
        cfg = load_app_config()
        self.voice_gate.set_mode(cfg.get("voice_input_mode", "ptt_wake"))
        self._wake_detector = WakeWordDetector(load_wake_word_config(cfg))
        self._sync_voice_ui()
        return self._wake_detector.status()

    def _on_ptt_start(self) -> None:
        self.voice_gate.start_ptt()
        self._sync_voice_ui()
        self.ui.mark_user_activity(True)
        if self._is_speaking or self.speech.is_speaking:
            self._interrupt_audio_from_thread()

    def _on_ptt_stop(self) -> None:
        self.voice_gate.stop_ptt()
        self._sync_voice_ui()
        if self._loop and self.session:
            asyncio.run_coroutine_threadsafe(self._send_audio_stream_end(), self._loop)

    def _on_wake_toggle(self, enabled: bool) -> None:
        from app_config import save_app_config
        save_app_config({"wake_word_enabled": bool(enabled)})
        status = self._refresh_wake_detector()
        self.ui.write_log(f"SYS: Wake word {'acildi' if enabled else 'kapatildi'}: {status}")

    def _on_stop_command(self) -> None:
        self._interrupt_audio_from_thread()

    # ------------------------------------------------------------------ #
    # Audio helpers
    # ------------------------------------------------------------------ #

    def _interrupt_audio_from_thread(self) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._interrupt_audio(), self._loop)
        else:
            self.speech.stop()
            self.speech_memory.mark_stopped()
            self.set_speaking(False)

    async def _send_audio_stream_end(self) -> None:
        try:
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
        except Exception:
            log.debug("send_audio_stream_end failed", exc_info=True)

    def _arm_wake_capture(self) -> None:
        cfg = load_app_config()
        seconds = int(cfg.get("wake_capture_seconds", 8) or 8)
        self.voice_gate.arm_wake(seconds)
        self._sync_voice_ui()
        self.ui.mark_user_activity(True)
        if self._is_speaking or self.speech.is_speaking:
            self._interrupt_audio_from_thread()

    # ------------------------------------------------------------------ #
    # Voice control
    # ------------------------------------------------------------------ #

    def _handle_voice_control_command(self, text: str, *, source: str = "text") -> bool:
        parsed = parse_voice_control(text)
        if not parsed.matched:
            return False
        action = parsed.action
        if action == "stop":
            self._interrupt_audio_from_thread()
            self.ui.write_log("SYS: Ses kesildi.")
            self.ui.set_state("LISTENING")
            return True
        if action == "resume":
            if self._paused:
                self._paused = False
                self.ui.paused = False
                if hasattr(self.ui, "_draw_pause_button"):
                    self.ui.root.after(0, self.ui._draw_pause_button)
                self.ui.write_log("SYS: JARVIS devam ediyor...")
            text_to_speak = self.speech_memory.resume()
            if text_to_speak and not self.ui.muted:
                self._speak_response(text_to_speak)
            else:
                self.ui.set_state("LISTENING")
            return True
        if action == "repeat":
            text_to_speak = self.speech_memory.repeat()
            if text_to_speak and not self.ui.muted:
                self._speak_response(text_to_speak)
            else:
                self.ui.write_log("SYS: Tekrar okunacak son yanit yok.")
                self.ui.set_state("LISTENING")
            return True
        if action == "shorten":
            short = self.speech_memory.shorten()
            if not short:
                self.ui.write_log("SYS: Kisaltacak son yanit yok.")
                self.ui.set_state("LISTENING")
                return True
            self.ui.write_log(f"JARVIS: {short}")
            if not self.ui.muted:
                self._speak_response(short)
            else:
                self.ui.set_state("LISTENING")
            return True
        return False

    def _speak_response(self, text: str, on_done: Callable | None = None) -> bool:
        spoken = str(text or "").strip()
        if not spoken:
            if on_done:
                on_done()
            return False
        self.speech_memory.set(spoken)
        self.set_speaking(True)

        def done():
            self.speech_memory.advance_by_text(spoken)
            self.set_speaking(False)
            if on_done:
                on_done()

        self.speech.speak(spoken, on_done=done, blocking=False)
        return True

    def set_speaking(self, value: bool) -> None:
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        else:
            if self.pending_actions.has_pending():
                self.ui.set_state("WAITING_APPROVAL")
            else:
                self.ui.set_state("LISTENING")

    def speak_error(self, tool_name: str, error: str) -> None:
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.ui.write_debug(f"{tool_name}: {short}", level="ERROR")
        self.ui.set_state("ERROR")

    # ------------------------------------------------------------------ #
    # Guard & tracing helpers
    # ------------------------------------------------------------------ #

    def _guarded_tool_action(self, tool_name: str, args: dict, runner: Callable, summary: str = "") -> str:
        run_id = self.agent_runtime.current_run_id or self.trace.current_run_id
        return guard_tool_call(
            tool_name,
            args or {},
            runner,
            self.pending_actions,
            self.audit_logger,
            run_id=run_id,
            summary_override=summary,
        )

    def _notify_task_result(self, title: str, body: str) -> None:
        summary = self._speech_excerpt(body, limit=700) or str(body or "").strip()
        message = f"Takip bildirimi: {title}\n{summary}"
        self.ui.write_log(f"SYS: {message}")
        toast_result = notify_windows(title, summary)
        if "gonderilemedi" in toast_result.casefold():
            self.ui.write_debug(toast_result, level="WARN")
        else:
            self.ui.write_debug(toast_result, level="INFO")
        if not self.ui.muted and summary:
            self._speak_response(summary)

    def _start_user_run(self, text: str, source: str = "text") -> str:
        run_id = self.trace.start_run(text, source=source)
        self.agent_runtime.set_current_run(run_id)
        return run_id

    def _auto_learn_from_user_text(self, text: str, run_id: str) -> None:
        try:
            learned = infer_memory_from_text(text, source_id=run_id)
            if learned.get("saved"):
                item = learned.get("item") or {}
                self.trace.log_event(run_id, "auto_memory_saved", {
                    "id": item.get("id"), "kind": item.get("kind"), "title": item.get("title"),
                })
                self.ui.write_debug(f"Hafiza ogrenildi: #{item.get('id')} {item.get('title')}", level="INFO")
        except Exception as exc:
            self.trace.log_event(run_id, "auto_memory_failed", {"error": str(exc)})

    def _speech_excerpt(self, text: str, limit: int = 700) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        for old, new in (
            ("\r\n", "\n"), ("\r", "\n"), ("*", ""), ("#", ""),
        ):
            clean = clean.replace(old, new)
        lines = [l.strip() for l in clean.split("\n") if l.strip()]
        cleaned = " ".join(lines)
        return cleaned[:limit] + ("..." if len(cleaned) > limit else "")

    def _clean_transcript_text(self, raw: str) -> tuple[str, bool]:
        noise_starters = {"[music]", "[laughter]", "[applause]", "[noise]", "[background noise]"}
        if not raw:
            return "", False
        had_noise = False
        parts = re.split(r"\[.*?\]", raw)
        cleaned = " ".join(p for p in parts if p.strip()).strip()
        if cleaned != raw.strip():
            had_noise = True
        return cleaned, had_noise

    def _focus_ui_section_for_tool(self, _tool_name: str, _args: dict) -> None:
        try:
            if hasattr(self.ui, "focus_tool_section"):
                self.ui.focus_tool_section(_tool_name)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Text command handler
    # ------------------------------------------------------------------ #

    def _on_text_command(self, text: str) -> None:
        self.ui.mark_user_activity(True)
        run_id = self._start_user_run(text, source="text")
        if self._handle_voice_control_command(text, source="text"):
            return
        self._auto_learn_from_user_text(text, run_id)
        if not self.agent_runtime.apply_text_command(
            text,
            run_id=run_id,
            on_result=self._on_text_result,
        ):
            self.ui.write_log("SYS: Komut islenemedi - 9Router/REST API kullanilamiyor.")

    def _on_text_result(self, text: str) -> None:
        self.ui.write_log(f"JARVIS: {text}")
        if self._audio_output_available and not self.ui.muted and text:
            self._speak_response(text)
        else:
            self.ui.set_state("LISTENING")

    # ------------------------------------------------------------------ #
    # Interrupt helpers
    # ------------------------------------------------------------------ #

    async def _interrupt_audio(self) -> None:
        self.speech.stop()
        self.speech_memory.mark_stopped()
        self.set_speaking(False)
        try:
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
                while not self.audio_in_queue.empty():
                    try:
                        self.audio_in_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
        except Exception:
            pass

    @staticmethod
    def _result_looks_like_error(result: Any) -> bool:
        text = str(result or "").strip()
        if not text or text == "Tamam.":
            return False
        return text.lower().startswith(("hata:", "error:", "failed:", "exception:"))

    def _should_play_success_sfx(self, name: str, _args: dict, result: Any) -> bool:
        low = name.lower()
        if low not in ("shell_run", "send_whatsapp_message"):
            return False
        text = str(result or "").strip().lower()
        if any(w in text for w in ("hata", "error", "fail", "reddedildi", "iptal")):
            return False
        return True

    # ------------------------------------------------------------------ #
    # Tool execution
    # ------------------------------------------------------------------ #

    async def _execute_tool(self, fc: types.FunctionCall) -> types.FunctionResponse:
        name = fc.name
        args = dict((fc.args or {}).items())
        tool_decl = next((d for d in TOOL_DECLARATIONS if d["name"] == name), None)
        policy = classify_tool(name, args, tool_decl)

        if name in OFFLINE_BLOCKED_TOOLS and not internet_available():
            result = (
                "Internet baglantisi yok/offline mod aktif. Bu arac dis kaynak gerektiriyor; "
                "yerel dosya, hafiza, pano ve sistem araclari calismaya devam eder."
            )
            self.trace.log_event(
                self.agent_runtime.current_run_id or self.trace.current_run_id,
                "offline_external_blocked",
                {"tool_name": name, "args": args},
            )
            return types.FunctionResponse(id=fc.id, name=name, response={"result": result})

        loop = asyncio.get_event_loop()
        result = "Tamam."
        had_exception = False

        try:
            if name == "save_memory":
                cat = args.get("category", "notes")
                key = args.get("key", "")
                val = args.get("value", "")
                if key and val:
                    update_memory({cat: {key: {"value": val}}})
                    log.info("Memory saved %s/%s", cat, key)
                result = "ok"

            elif name == "delete_memory":
                result = delete_memory(
                    args.get("category", ""),
                    args.get("key", ""),
                    args.get("match_text", ""),
                )

            elif name == "search_memory":
                r = await loop.run_in_executor(
                    None,
                    lambda: search_memory(
                        args.get("query", ""),
                        args.get("kind", ""),
                        int(args.get("limit", 8) or 8),
                    ),
                )
                result = r or "Hafiza aramasi tamamlandi."

            elif name == "list_memory":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_memory(
                        args.get("kind", ""),
                        int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Hafiza listelendi."

            elif name == "memory_status":
                r = await loop.run_in_executor(None, memory_status)
                result = r or "Hafiza durumu alindi."

            elif name == "remember_file_note":
                r = await loop.run_in_executor(
                    None,
                    lambda: remember_file_note(
                        args.get("path", ""),
                        args.get("summary", ""),
                        args.get("tags", ""),
                    ),
                )
                result = r or "Dosya notu hafizaya kaydedildi."

            elif name == "pending_action_status":
                result = self.pending_actions.describe()

            elif name == "approve_pending_action":
                result = self.pending_actions.approve()

            elif name == "cancel_pending_action":
                result = self.pending_actions.cancel()

            elif name == "audit_status":
                result = audit_status(int(args.get("limit", 10) or 10), self.audit_logger)

            elif name == "tool_risk_status":
                result = tool_risk_status(args.get("tool_name", ""))

            elif name == "local_ai_status":
                r = await loop.run_in_executor(None, local_ai_status)
                result = r or "Yerel AI durumu alindi."

            elif name == "test_local_ai":
                r = await loop.run_in_executor(
                    None,
                    lambda: test_local_ai(args.get("prompt", "")),
                )
                result = r or "Yerel AI testi tamamlandi."

            elif name == "set_agent_mode":
                result = self._guarded_tool_action(
                    name, args, lambda: set_agent_mode(args.get("mode", "hybrid")),
                )

            elif name == "voice_experience_status":
                result = build_voice_experience_status(
                    config=load_app_config(),
                    audio_input_available=self._audio_input_available,
                    audio_output_available=self._audio_output_available,
                    text_mode=self._text_mode,
                    ptt_active=self.voice_gate.ptt_active,
                    wake_ready=bool(self._wake_detector and self._wake_detector.ready),
                    wake_error=self._wake_detector.status() if self._wake_detector else "",
                )

            elif name == "set_voice_mode":
                def _set_voice():
                    value = set_voice_mode_config(args.get("mode", "ptt_wake"))
                    status = self._refresh_wake_detector()
                    return f"{value}\n{status}"

                result = self._guarded_tool_action(name, args, _set_voice)

            elif name == "list_plugins":
                r = await loop.run_in_executor(None, list_plugins)
                result = r or "Pluginler listelendi."

            elif name == "plugin_status":
                r = await loop.run_in_executor(
                    None, lambda: plugin_status(args.get("plugin_id", "")),
                )
                result = r or "Plugin durumu alindi."

            elif name == "enable_plugin":
                result = self._guarded_tool_action(
                    name, args, lambda: enable_plugin(args.get("plugin_id", "")),
                )

            elif name == "disable_plugin":
                result = self._guarded_tool_action(
                    name, args, lambda: disable_plugin(args.get("plugin_id", "")),
                )

            elif name == "set_plugin_config":
                config_value = args.get("config") or args.get("config_json", "")
                result = self._guarded_tool_action(
                    name, args,
                    lambda: set_plugin_config(
                        args.get("plugin_id", ""),
                        config_value,
                        bool(args.get("merge", True)),
                    ),
                )

            elif name == "discover_plugin_tools":
                r = await loop.run_in_executor(
                    None, lambda: discover_plugin_tools(args.get("plugin_id", "")),
                )
                result = r or "Plugin tool kesfi tamamlandi."

            elif name == "call_plugin_tool":
                arguments_value = args.get("arguments") or args.get("arguments_json", "{}")
                result = self._guarded_tool_action(
                    name, args,
                    lambda: call_plugin_tool(
                        args.get("plugin_id", ""),
                        args.get("tool_name", ""),
                        arguments_value,
                    ),
                )

            elif name == "create_followup_task":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_followup_task(
                        args.get("title", ""),
                        args.get("task_type", "web_watch"),
                        args.get("query", ""),
                        args.get("url", ""),
                        args.get("schedule_kind", "interval"),
                        int(args.get("interval_minutes", 180) or 180),
                        args.get("run_at", ""),
                        bool(args.get("baseline_now", True)),
                    ),
                )
                result = r or "Takip gorevi olusturuldu."

            elif name == "list_tasks":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_tasks(
                        args.get("status_filter", "active"),
                        int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Gorevler listelendi."

            elif name == "cancel_task":
                r = await loop.run_in_executor(
                    None, lambda: cancel_task(args.get("task_id", 0)),
                )
                result = r or "Gorev iptal edildi."

            elif name == "run_task_now":
                r = await loop.run_in_executor(
                    None, lambda: run_task_now(args.get("task_id", 0)),
                )
                result = r or "Gorev calistirildi."

            elif name == "startup_tracking_status":
                r = await loop.run_in_executor(None, startup_tracking_status)
                result = r or "Baslangic takip durumu alindi."

            elif name == "enable_startup_tracking":
                result = self._guarded_tool_action(name, args, enable_startup_tracking)

            elif name == "disable_startup_tracking":
                result = self._guarded_tool_action(name, args, disable_startup_tracking)

            elif name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(args.get("app_name", "")),
                )
                result = r or f"{args.get('app_name')} açıldı."

            elif name == "sys_info":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: sys_info(args.get("query", "all")),
                )
                result = r or "Bilgi alındı."

            elif name == "get_weather":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: get_weather_summary(args.get("location") or None),
                )
                result = r or "Hava durumu bilgisi alindi."

            elif name == "calendar_auth_status":
                r = await loop.run_in_executor(None, calendar_auth_status)
                result = r or "Takvim baglanti durumu alindi."

            elif name == "connect_calendar_provider":
                r = await loop.run_in_executor(
                    None,
                    lambda: connect_calendar_provider(
                        args.get("provider", ""), args.get("mode", "start"),
                    ),
                )
                result = r or "Takvim saglayici baglantisi guncellendi."

            elif name == "disconnect_calendar_provider":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: disconnect_calendar_provider(args.get("provider", "")),
                )

            elif name == "list_calendars":
                r = await loop.run_in_executor(
                    None, lambda: list_calendars(args.get("provider", "")),
                )
                result = r or "Takvimler listelendi."

            elif name == "get_calendar_events":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_calendar_events(
                        args.get("query", "today"), int(args.get("limit", 6) or 6),
                    ),
                )
                result = r or "Takvim bilgisi alindi."

            elif name == "add_calendar_event":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: add_calendar_event(
                        args.get("title", ""), args.get("start_iso", ""),
                        args.get("end_iso", ""), args.get("notes", ""),
                        args.get("location", ""), args.get("calendar_name", ""),
                        bool(args.get("all_day", False)),
                    ),
                )

            elif name == "delete_calendar_event":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: delete_calendar_event(
                        args.get("title", ""), args.get("start_iso", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("delete_all_matches", False)),
                    ),
                )

            elif name == "get_reminders":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_reminders(
                        args.get("query", "upcoming"),
                        int(args.get("limit", 8) or 8),
                        args.get("list_name", ""),
                    ),
                )
                result = r or "Animsatici bilgisi alindi."

            elif name == "add_reminder":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: add_reminder(
                        args.get("title", ""), args.get("due_iso", ""),
                        args.get("notes", ""), args.get("list_name", ""),
                        args.get("priority", ""), bool(args.get("all_day", False)),
                    ),
                )

            elif name == "complete_reminder":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: complete_reminder(
                        args.get("reminder_id", ""), args.get("title", ""),
                        args.get("list_name", ""),
                    ),
                )

            elif name == "delete_reminder":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: delete_reminder(
                        args.get("reminder_id", ""), args.get("title", ""),
                        args.get("list_name", ""),
                    ),
                )

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(
                        args.get("action"), args.get("url"), args.get("query"),
                    ),
                )
                result = r or "Tamam."

            elif name == "browser_read_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: browser_read_url(
                        args.get("url", ""), args.get("question", ""),
                        int(args.get("max_pages", 3) or 3),
                        bool(args.get("visible", False)),
                    ),
                )
                result = r or "Sayfa BrowserAgent ile okundu."

            elif name == "browser_research":
                r = await loop.run_in_executor(
                    None,
                    lambda: browser_research(
                        args.get("query", ""),
                        int(args.get("max_pages", 5) or 5),
                        bool(args.get("visible", False)),
                    ),
                )
                result = r or "BrowserAgent arastirmasi tamamlandi."

            elif name == "browser_click":
                target = args.get("selector_or_text", "")
                result = self._guarded_tool_action(
                    name, args,
                    lambda: browser_click(target, bool(args.get("visible", True))),
                )

            elif name == "browser_fill":
                target = args.get("selector_or_label", "")
                value = args.get("value", "")
                result = self._guarded_tool_action(
                    name, args,
                    lambda: browser_fill(target, value, bool(args.get("visible", True))),
                )

            elif name == "browser_submit":
                target = args.get("selector_or_text", "")
                result = self._guarded_tool_action(
                    name, args,
                    lambda: browser_submit(target, bool(args.get("visible", True))),
                )

            elif name == "shell_run":
                command = args.get("command", "")
                result = self._guarded_tool_action(
                    name, args, lambda: shell_run(command),
                )

            elif name == "play_media":
                r = await loop.run_in_executor(
                    None,
                    lambda: play_media(
                        args.get("query", ""), args.get("provider", "auto"),
                        bool(args.get("autoplay", True)),
                    ),
                )
                result = r or "Medya oynatma başlatıldı."

            elif name == "get_youtube_channel_report":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_youtube_channel_report(
                        args.get("query", "overview"), args.get("handle", ""),
                        int(args.get("video_limit", 6) or 6),
                    ),
                )
                result = r or "YouTube kanal raporu alindi."

            elif name == "analyze_screen":
                r = await loop.run_in_executor(
                    None,
                    lambda: analyze_screen(
                        args.get("query", "Ekranda ne var?"),
                        args.get("target", "active_window"),
                    ),
                )
                result = r or "Ekran analizi tamamlandi."

            elif name == "list_folder":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_folder(
                        args.get("path", ""),
                        int(args.get("limit", 60) or 60),
                    ),
                )
                result = r or "Klasor listelendi."

            elif name == "find_files":
                r = await loop.run_in_executor(
                    None,
                    lambda: find_files(
                        args.get("query", ""), args.get("path", ""),
                        int(args.get("limit", 40) or 40),
                    ),
                )
                result = r or "Dosya aramasi tamamlandi."

            elif name == "read_text_file":
                r = await loop.run_in_executor(
                    None,
                    lambda: read_text_file(
                        args.get("path", ""),
                        int(args.get("max_chars", 12000) or 12000),
                    ),
                )
                result = r or "Dosya okundu."

            elif name == "summarize_text_file":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_text_file(
                        args.get("path", ""),
                        int(args.get("max_chars", 16000) or 16000),
                    ),
                )
                result = r or "Dosya ozetlendi."

            elif name == "open_file":
                r = await loop.run_in_executor(
                    None, lambda: open_file(args.get("path", "")),
                )
                result = r or "Dosya acildi."

            elif name == "get_clipboard":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_clipboard(int(args.get("max_chars", 12000) or 12000)),
                )
                result = r or "Pano okundu."

            elif name == "set_clipboard":
                result = self._guarded_tool_action(
                    name, args, lambda: set_clipboard(args.get("text", "")),
                )

            elif name == "summarize_clipboard":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_clipboard(int(args.get("max_chars", 4000) or 4000)),
                )
                result = r or "Pano ozetlendi."

            elif name == "get_selected_text":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_selected_text(
                        int(args.get("max_chars", 12000) or 12000),
                        bool(args.get("restore_clipboard", True)),
                    ),
                )
                result = r or "Secili metin okundu."

            elif name == "summarize_selected_text":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_selected_text(int(args.get("max_chars", 4000) or 4000)),
                )
                result = r or "Secili metin ozetlendi."

            elif name == "active_window_info":
                r = await loop.run_in_executor(None, active_window_info)
                result = r or "Aktif pencere bilgisi alindi."

            elif name == "list_windows":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_windows(
                        args.get("query", ""), int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Pencereler listelendi."

            elif name == "focus_window":
                r = await loop.run_in_executor(
                    None,
                    lambda: focus_window(
                        args.get("query", ""), bool(args.get("exact", False)),
                    ),
                )
                result = r or "Pencere odaklandi."

            elif name == "send_hotkey_safe":
                hotkey = args.get("hotkey", "")
                delay = float(args.get("delay_seconds", 0.2) or 0.2)
                result = self._guarded_tool_action(
                    name, args, lambda: send_hotkey_safe(hotkey, delay),
                )

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: web_search(
                        args.get("query", ""),
                        bool(args.get("open_results", True)),
                    ),
                )
                result = r or "Web aramasi acildi."

            elif name == "open_and_summarize_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: open_and_summarize_url(
                        args.get("url", ""),
                        int(args.get("max_chars", 2500) or 2500),
                    ),
                )
                result = r or "Sayfa acildi."

            elif name == "research_web":
                r = await loop.run_in_executor(
                    None,
                    lambda: research_web(
                        args.get("query", ""),
                        int(args.get("max_pages", 5) or 5),
                        bool(args.get("open_browser", False)),
                    ),
                )
                result = r or "Arastirma tamamlandi."

            elif name == "answer_research_question":
                r = await loop.run_in_executor(
                    None,
                    lambda: answer_research_question(
                        args.get("query", ""),
                        args.get("depth", "balanced"),
                        bool(args.get("speak", False)),
                    ),
                )
                result = r or "Arastirma tamamlandi."

            elif name == "tavily_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: tavily_search(
                        args.get("query", ""),
                        int(args.get("max_results", 5) or 5),
                        args.get("search_depth", "advanced"),
                    ),
                )
                result = r or "Tavily arastirmasi tamamlandi."

            elif name == "browse_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: browse_url(
                        args.get("url", ""), args.get("question", ""),
                        int(args.get("max_pages", 2) or 2),
                        bool(args.get("open_browser", False)),
                    ),
                )
                result = r or "Sayfa gezildi."

            elif name == "create_folder":
                result = self._guarded_tool_action(
                    name, args, lambda: create_folder(args.get("path", "")),
                )

            elif name == "create_text_file":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: create_text_file(
                        args.get("path", ""), args.get("content", ""),
                        bool(args.get("overwrite", False)),
                    ),
                )

            elif name == "write_text_file":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: write_text_file(
                        args.get("path", ""), args.get("content", ""),
                        bool(args.get("overwrite", True)),
                    ),
                )

            elif name == "append_text_file":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: append_text_file(args.get("path", ""), args.get("content", "")),
                )

            elif name == "move_file":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: move_file(
                        args.get("source_path", ""), args.get("destination_path", ""),
                        bool(args.get("overwrite", False)),
                    ),
                )

            elif name == "delete_file":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: delete_file(
                        args.get("path", ""), bool(args.get("recursive", False)),
                    ),
                )

            elif name == "find_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: find_whatsapp_contact(
                        args.get("query", ""), int(args.get("limit", 5) or 5),
                    ),
                )
                result = r or "WhatsApp kisi aramasi tamamlandi."

            elif name == "list_whatsapp_contacts":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_whatsapp_contacts(
                        int(args.get("limit", 30) or 30),
                        args.get("source_filter", ""),
                    ),
                )
                result = r or "WhatsApp kisileri listelendi."

            elif name == "import_phone_book_from_vcf":
                result = self._guarded_tool_action(
                    name, args,
                    lambda: import_phone_book_from_vcf(args.get("vcf_path", "")),
                )

            elif name == "send_whatsapp_message":
                message = args.get("message", "")
                phone_number = args.get("phone_number", "")
                recipient_name = args.get("recipient_name", "")
                send_now = bool(args.get("send_now", False))
                app_target = args.get("app_target", "auto")
                if send_now:
                    result = self._guarded_tool_action(
                        name, args,
                        lambda: send_whatsapp_message(
                            message, phone_number, recipient_name, True, app_target,
                        ),
                    )
                else:
                    r = await loop.run_in_executor(
                        None,
                        lambda: send_whatsapp_message(
                            message, phone_number, recipient_name, False, app_target,
                        ),
                    )
                    result = r or "WhatsApp taslagi hazirlandi."

            elif name == "save_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: save_whatsapp_contact(
                        args.get("display_name", ""), args.get("phone_number", ""),
                        args.get("aliases", ""),
                    ),
                )
                result = r or "WhatsApp kişisi kaydedildi."

            # --- Document Generation ---
            elif name == "create_pdf":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_pdf(
                        json.loads(args.get("descriptor_json", "{}")),
                        args.get("output_path", ""),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "create_docx":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_docx(
                        json.loads(args.get("descriptor_json", "{}")),
                        args.get("output_path", ""),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "create_xlsx":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_xlsx(
                        json.loads(args.get("descriptor_json", "{}")),
                        args.get("output_path", ""),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "create_pptx":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_pptx(
                        json.loads(args.get("descriptor_json", "{}")),
                        args.get("output_path", ""),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "document_status":
                r = await loop.run_in_executor(None, document_status)
                result = json.dumps(r, ensure_ascii=False)

            # --- Database ---
            elif name == "query_database":
                r = await loop.run_in_executor(
                    None,
                    lambda: query_database(
                        args.get("db_path", ""),
                        args.get("sql", ""),
                        None,
                        int(args.get("limit", 100) or 100),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "list_tables":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_tables(args.get("db_path", "")),
                )
                result = json.dumps(r, ensure_ascii=False)

            # --- Network ---
            elif name == "ping_host":
                r = await loop.run_in_executor(
                    None,
                    lambda: ping_host(
                        args.get("host", ""),
                        int(args.get("count", 4) or 4),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "dns_lookup":
                r = await loop.run_in_executor(
                    None,
                    lambda: dns_lookup(args.get("host", "")),
                )
                result = json.dumps(r, ensure_ascii=False)

            elif name == "http_check":
                r = await loop.run_in_executor(
                    None,
                    lambda: http_check(
                        args.get("url", ""),
                        int(args.get("timeout", 10) or 10),
                    ),
                )
                result = json.dumps(r, ensure_ascii=False)

            else:
                result = f"Bilinmeyen araç: {name}"

        except Exception as e:
            result = f"Hata: {e}"
            had_exception = True
            self.trace.log_error(
                self.agent_runtime.current_run_id or self.trace.current_run_id,
                f"tool:{name}",
                f"{type(e).__name__}: {e}",
                {"tool_name": name, "args_preview": safe_log_preview(args, limit=700, redact_content_keys=True)},
            )
            self.speak_error(name, e)

        tool_failed = self._result_looks_like_error(result)
        waiting_approval = str(result or "").startswith("Onay gerekiyor")
        if policy.audit_required and not (policy.requires_approval and str(result).startswith("Onay gerekiyor")):
            self.audit_logger.log(
                "failed" if (had_exception or tool_failed) else "executed",
                run_id=self.agent_runtime.current_run_id or self.trace.current_run_id,
                tool_name=name,
                risk_class=policy.risk_class,
                args=args,
                summary=policy.summary(args),
                result=str(result),
                status="failed" if (had_exception or tool_failed) else "executed",
            )
        if tool_failed:
            if not had_exception:
                self.ui.set_state("ERROR")
        elif waiting_approval:
            self.ui.set_state("WAITING_APPROVAL")
        elif self._should_play_success_sfx(name, args, result):
            self.ui.play_success_sfx()

        if not tool_failed and not waiting_approval and not self.ui.muted:
            self.ui.set_state("LISTENING")

        log.info("tool %s -> %s", name, safe_log_preview(result, limit=300))
        return types.FunctionResponse(
            id=fc.id, name=name, response={"result": result},
        )

    # ------------------------------------------------------------------ #
    # Audio pipeline
    # ------------------------------------------------------------------ #

    async def _send_realtime(self) -> None:
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    def _get_pyaudio(self):
        if pyaudio is None:
            raise RuntimeError("PyAudio yuklu degil veya baslatilamadi.")
        with self._pyaudio_lock:
            if self._pyaudio is None:
                self._pyaudio = pyaudio.PyAudio()
            return self._pyaudio

    def _open_input_stream(self):
        last_error = None
        candidates = [None]
        pya = self._get_pyaudio()
        try:
            for index in range(pya.get_device_count()):
                info = pya.get_device_info_by_index(index)
                if int(info.get("maxInputChannels", 0) or 0) > 0:
                    candidates.append(index)
        except Exception:
            pass
        for index in candidates:
            try:
                kwargs = {}
                if index is not None:
                    kwargs["input_device_index"] = index
                return pya.open(
                    format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
                    input=True, frames_per_buffer=CHUNK_SIZE, **kwargs,
                )
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("Mikrofon cihazi bulunamadi.")

    def _open_output_stream(self):
        last_error = None
        candidates = [None]
        pya = self._get_pyaudio()
        try:
            for index in range(pya.get_device_count()):
                info = pya.get_device_info_by_index(index)
                if int(info.get("maxOutputChannels", 0) or 0) > 0:
                    candidates.append(index)
        except Exception:
            pass
        for index in candidates:
            try:
                kwargs = {}
                if index is not None:
                    kwargs["output_device_index"] = index
                return pya.open(
                    format=FORMAT, channels=CHANNELS, rate=RECV_SAMPLE_RATE,
                    output=True, **kwargs,
                )
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("Ses cikis cihazi bulunamadi.")

    async def _listen_audio(self) -> None:
        log.info("[JARVIS] 🎤 Mikrofon başladı")
        try:
            stream = await asyncio.to_thread(self._open_input_stream)
            self._audio_input_available = True
            self._text_mode = False
            self._sync_voice_ui()
        except Exception as exc:
            self._audio_input_available = False
            self._text_mode = True
            self._sync_voice_ui()
            detail = f"{type(exc).__name__}: {exc}"
            self._audio_notice(
                "input_unavailable",
                "Mikrofon acilamadi; yazili komut ve web arama modu aktif. Windows Ses Ayarlari > Giris cihazini kontrol et.",
            )
            return

        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False
                )
                if (
                    self._wake_detector
                    and self._wake_detector.config.enabled
                    and not self.voice_gate.ptt_active
                    and self._wake_detector.process_pcm(data)
                ):
                    self._arm_wake_capture()
                with self._speaking_lock:
                    jarvis_speaking = self._is_speaking
                self.voice_gate.muted = bool(self.ui.muted)
                self.voice_gate.paused = bool(self._paused)
                if jarvis_speaking and self.voice_gate.is_open():
                    await self._interrupt_audio()
                    jarvis_speaking = False
                if not jarvis_speaking and self.voice_gate.is_open():
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
        except Exception as e:
            print(f"[JARVIS] ❌ Mikrofon: {e}")
            self._audio_input_available = False
            self._audio_notice(
                "input_failed",
                f"Mikrofon akisi durdu; yazili komut modu aktif. Detay: {type(e).__name__}: {e}",
            )
            self._text_mode = True
            self._sync_voice_ui()
            return
        finally:
            stream.close()

    # ------------------------------------------------------------------ #
    # Receive audio from Gemini
    # ------------------------------------------------------------------ #

    async def _receive_audio(self) -> None:
        print("[JARVIS] 👂 Alım başladı")
        out_buf, in_buf = [], []
        output_noise = False
        output_noise_samples = []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data and self._audio_output_available:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content
                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            raw_txt = sc.output_transcription.text.strip()
                            if raw_txt:
                                txt, had_noise = self._clean_transcript_text(raw_txt)
                                if had_noise:
                                    output_noise = True
                                    if len(output_noise_samples) < 4:
                                        output_noise_samples.append(raw_txt)
                                if txt:
                                    out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                if not self._voice_run_id:
                                    self._voice_run_id = self._start_user_run("voice input", source="voice")
                                in_buf.append(txt)
                                self.ui.mark_user_activity(True)

                        if sc.turn_complete:
                            self.set_speaking(False)
                            full_in = " ".join(in_buf).strip()
                            voice_control_handled = False
                            if full_in:
                                if not self._voice_run_id:
                                    self._voice_run_id = self._start_user_run(full_in, source="voice")
                                self.trace.log_event(self._voice_run_id, "voice_transcript", {"text": full_in})
                                self.ui.write_log(f"Siz: {full_in}")
                                voice_control_handled = self._handle_voice_control_command(full_in, source="voice")
                                if voice_control_handled:
                                    self.trace.log_event(self._voice_run_id, "voice_control_command", {"text": full_in})
                                else:
                                    self._auto_learn_from_user_text(full_in, self._voice_run_id)
                                in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out and not voice_control_handled:
                                if self._voice_run_id:
                                    self.trace.log_event(self._voice_run_id, "voice_agent_result", {"text": full_out})
                                saved_summary = save_conversation_summary(full_in, full_out, self._voice_run_id)
                                if saved_summary and not saved_summary.get("blocked") and saved_summary.get("id"):
                                    self.trace.log_event(
                                        self._voice_run_id,
                                        "conversation_summary_saved",
                                        {"id": saved_summary.get("id")},
                                    )
                                self.speech_memory.set(self._speech_excerpt(full_out) or full_out)
                                self.ui.write_log(f"JARVIS: {full_out}")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Kısmen filtrelenen ses transcripti: "
                                        + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                                elif output_noise:
                                    self.ui.write_log("ERR: JARVIS sesli yanıtını çözümlerken bir hata oluştu.")
                                    if output_noise_samples:
                                        self.ui.write_debug(
                                            "Filtrelenen ham transcript: "
                                            + " | ".join(output_noise_samples),
                                            level="WARN",
                                        )
                                    self.ui.set_state("ERROR")
                                out_buf = []
                                output_noise = False
                                output_noise_samples = []
                                self._voice_run_id = ""

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(function_responses=fn_responses)

        except Exception as e:
            print(f"[JARVIS] ❌ Alım: {e}")
            self.trace.log_error(
                self._voice_run_id or self.trace.current_run_id,
                "receive_audio",
                f"{type(e).__name__}: {e}",
            )
            raise

    # ------------------------------------------------------------------ #
    # Play audio output
    # ------------------------------------------------------------------ #

    async def _play_audio(self) -> None:
        print("[JARVIS] 🔊 Ses çalma başladı")
        try:
            stream = await asyncio.to_thread(self._open_output_stream)
            self._audio_output_available = True
        except Exception as exc:
            self._audio_output_available = False
            detail = f"{type(exc).__name__}: {exc}"
            print(f"[JARVIS] Ses cikisi devre disi: {detail}")
            self._audio_notice(
                "output_unavailable",
                "Ses cikisi acilamadi; yanitlar metin olarak loglanacak. Windows Ses Ayarlari > Cikis cihazini kontrol et.",
            )
            return

        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Ses: {e}")
            self._audio_output_available = False
            self._audio_notice(
                "output_failed",
                f"Ses cikisi durdu; yanitlar metin olarak loglanacak. Detay: {type(e).__name__}: {e}",
            )
            return
        finally:
            self.set_speaking(False)
            stream.close()

    # ------------------------------------------------------------------ #
    # Main run loop
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        self._loop = asyncio.get_event_loop()
        gemini_missing_notice_sent = False

        while True:
            if self._paused:
                await asyncio.sleep(1)
                continue

            api_key = get_api_key()
            if not api_key:
                if not gemini_missing_notice_sent:
                    self.ui.write_log(
                        "SYS: Gemini API anahtari yok; sesli Live devre disi, "
                        "yazili Ninerouter ajan modu kullanilabilir."
                    )
                    self.ui.set_state("LISTENING")
                    gemini_missing_notice_sent = True
                await asyncio.sleep(3)
                continue

            client = genai.Client(
                api_key=api_key,
                http_options={"api_version": "v1alpha"},
            )

            try:
                print("[JARVIS] 🔌 Bağlanıyor...")
                self.ui.set_state("THINKING")
                config = self._build_config()
                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self._loop = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Bağlandı.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS hazir. Dinliyorum...")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                detail = self._format_exception_summary(e)
                log.error("[JARVIS] connection error: %s", detail)
                self.trace.log_error(
                    self.trace.current_run_id,
                    "gemini_live",
                    detail,
                )
                self.set_speaking(False)
                self.session = None
                self.ui.write_log(
                    f"ERR: JARVIS baglantisi kesildi veya internete ulasilamiyor - {detail}"
                )
                self.ui.set_state("ERROR")
                print("[JARVIS] 🔄 3 saniyede yeniden bağlanıyor...")
                await asyncio.sleep(3)

    def _build_config(self) -> types.LiveConnectConfig:
        system_instruction = load_system_prompt()
        memory_prompt = format_memory_for_prompt(limit=12, max_chars=4000)
        relevant = format_relevant_memories_for_prompt("", limit=6, max_chars=3000)
        extra = "\n".join(filter(None, [memory_prompt, relevant]))
        if extra:
            system_instruction = f"{system_instruction}\n\n--- Hafiza ---\n{extra}"

        tools = TOOL_DECLARATIONS or []
        cfg = load_app_config()
        voice_mode = normalize_voice_mode(cfg.get("voice_input_mode", "ptt_wake"))

        return types.LiveConnectConfig(
            response_modalities=["TEXT", "AUDIO"],
            system_instruction=system_instruction,
            tools=[types.Tool(function_declarations=tools)],
            session_resumption=True,
            context_window_compression=types.ContextWindowCompression(
                should_compress=True,
                trigger_tokens=8000,
            ),
        )

    # ------------------------------------------------------------------ #
    # Audio notice (debounced log + UI)
    # ------------------------------------------------------------------ #

    def _audio_notice(self, key: str, message: str, cooldown: float = 90.0) -> None:
        now = time.monotonic()
        last = self._audio_notice_cache.get(key, 0.0)
        if now - last < cooldown:
            return
        self._audio_notice_cache[key] = now
        self.ui.write_log(f"SYS: {message}")

    @staticmethod
    def _format_exception_summary(exc: BaseException) -> str:
        message = str(exc)
        snippet = message.replace("\n", " ")[:220]
        return f"{type(exc).__name__}: {snippet}"


# ------------------------------------------------------------------ #
# Entry point helpers
# ------------------------------------------------------------------ #

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JARVIS desktop assistant")
    parser.add_argument("--smoke", action="store_true", help="Windows UI smoke modunu calistir ve cik.")
    parser.add_argument("--smoke-timeout", type=int, default=90, help="Smoke modu zaman asimi saniyesi.")
    parser.add_argument("--smoke-app", default="explorer", help="Smoke modunda acilacak uygulama.")
    return parser


def _run_smoke_app(timeout_seconds: int = 90, smoke_app: str = "explorer") -> int:
    ui = JarvisUI()
    try:
        ui._api_key_ready = True
        if hasattr(ui, "_close_setup_ui"):
            ui._close_setup_ui()
        ui.set_text_mode(True)
        ui.set_state("LISTENING")
    except Exception:
        pass

    jarvis = JarvisLive(ui, start_task_scheduler=False)
    jarvis._text_mode = True
    jarvis._sync_voice_ui()

    holder = {"finished": False, "exit_code": 1}
    lock = threading.Lock()

    def close_ui(delay_ms: int = 1200) -> None:
        def close() -> None:
            try:
                jarvis.task_scheduler.stop()
            except Exception:
                pass
            try:
                ui.sound.stop_all()
            except Exception:
                pass
            try:
                ui.root.destroy()
            except Exception:
                pass
        try:
            ui.root.after(delay_ms, close)
        except Exception:
            close()

    def finish(report: dict) -> None:
        with lock:
            if holder["finished"]:
                return
            holder["finished"] = True
            holder["exit_code"] = 0 if report.get("status") in {"pass", "degraded"} else 1
        try:
            ui.write_log(f"SYS: Windows smoke tamamlandi: {report.get('status')} | {report.get('report_path', '')}")
        except Exception:
            pass
        close_ui()

    def timeout() -> None:
        with lock:
            if holder["finished"]:
                return
            holder["finished"] = True
            holder["exit_code"] = 1
        report = build_timeout_report(timeout_seconds)
        try:
            ui.write_log(f"SYS: SMOKE FAIL - timeout | {report.get('report_path', '')}")
        except Exception:
            pass
        close_ui(300)

    def worker() -> None:
        try:
            report = run_smoke_sequence(ui=ui, jarvis=jarvis, smoke_app=smoke_app)
        except Exception as exc:
            report = {
                "status": "fail",
                "report_path": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            ui.root.after(0, finish, report)
        except Exception:
            finish(report)

    threading.Thread(target=worker, name="JarvisSmoke", daemon=True).start()
    ui.root.after(max(1, int(timeout_seconds or 90)) * 1000, timeout)
    ui.root.mainloop()
    return int(holder["exit_code"])


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if os.environ.get("TERM_PROGRAM") == "vscode":
        print("[JARVIS] VS Code icinden baslatildi.")

    if args.smoke:
        return _run_smoke_app(args.smoke_timeout, args.smoke_app)

    ui = JarvisUI()

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Kapatılıyor...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
