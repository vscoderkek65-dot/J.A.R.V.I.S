from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from actions.audit import sanitize


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = BASE_DIR / "memory" / "smoke"


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _shorten(value: Any, limit: int = 900) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ...[truncated]"


def _write_ui(ui: Any, message: str) -> None:
    if not ui:
        return

    def write() -> None:
        try:
            ui.write_log(message)
        except Exception:
            pass

    root = getattr(ui, "root", None)
    if root is not None:
        try:
            root.after(0, write)
            return
        except Exception:
            pass
    write()


def _ui_exists(ui: Any) -> bool:
    root = getattr(ui, "root", None)
    if root is None:
        return False
    try:
        return bool(root.winfo_exists())
    except Exception:
        return True


def _dispatch_written_command(ui: Any, jarvis: Any, text: str = "hafiza durumu", timeout: float = 8.0) -> str:
    if jarvis is None or not hasattr(jarvis, "_on_text_command"):
        return "JarvisLive yazili komut callback'i yok."

    done = threading.Event()
    holder: dict[str, Any] = {}

    def call() -> None:
        try:
            jarvis._on_text_command(text)
            holder["result"] = f"Yazili komut gonderildi: {text}"
        except Exception as exc:
            holder["error"] = exc
        finally:
            done.set()

    root = getattr(ui, "root", None)
    if root is not None:
        try:
            root.after(0, call)
        except Exception:
            call()
    else:
        call()

    if not done.wait(timeout):
        raise TimeoutError("Yazili komut callback'i zaman asimina ugradi.")
    if "error" in holder:
        raise holder["error"]
    return str(holder.get("result") or "Yazili komut gonderildi.")


def _classify_step(name: str, output: str) -> tuple[str, str, str]:
    folded = str(output or "").casefold()
    if name == "ui_open":
        return ("pass", "UI aktif", "ui_open") if "aktif" in folded else ("fail", "UI aktif degil", "ui_missing")
    if name == "written_command":
        if "zaman asimi" in folded or "callback'i yok" in folded:
            return "fail", "Yazili komut callback'i calismadi", "written_command_unavailable"
        return "pass", "Yazili komut UI akisine gonderildi", "written_command_ok"
    if name == "web_research":
        has_answer = "kisa cevap" in folded or "kısa cevap" in folded
        has_source = "kaynak:" in folded or "kaynaklar" in folded or "http://" in folded or "https://" in folded
        if has_answer and has_source:
            return "pass", "Web arastirma kaynakli cevap dondurdu", "web_research_ok"
        if "okunabilir ve alakali kaynak bulamadim" in folded or "internet baglantisi yok" in folded:
            return "degraded", "Web arastirma calisti ama okunabilir kaynak bulamadi", "web_research_no_sources"
        if "traceback" in folded or "exception" in folded or "runtimeerror" in folded:
            return "degraded", "Web arastirma uyari/hata dondurdu", "web_research_warning"
        return "pass", "Web arastirma cevap dondurdu", "web_research_response"
    if name == "file_read":
        if "icerigi:" in folded or "içerigi:" in folded or "içeriği:" in folded:
            return "pass", "Dosya okundu", "file_read_ok"
        return "fail", "Dosya okuma beklenen icerigi dondurmedi", "file_read_unexpected_output"
    if name == "app_launch":
        if any(marker in folded for marker in ("bulunamadi", "acilamadi", "hata", "error")):
            return "fail", "Uygulama acilamadi", "app_launch_failed"
        return "pass", "Uygulama acma denemesi basarili", "app_launch_ok"
    if name == "screen_analysis":
        degraded_markers = (
            "api anahtari eksik",
            "api key missing",
            "permission denied",
            "izin verilmedi",
            "ekran goruntusu alinamadi",
            "ekran görüntüsü alınamadı",
            "aktif pencere alinamadi",
            "aktif pencere alınamadı",
            "pywin32 bulunamadi",
            "pywin32 bulunamadı",
            "vision analizi tamamlanamadi",
        )
        if any(marker in folded for marker in degraded_markers):
            return "degraded", "Ekran analizi ortam/API/izin nedeniyle sinirli", "screen_analysis_limited"
        return "pass", "Ekran analizi sonuc dondurdu", "screen_analysis_ok"
    if name == "tts_text_mode":
        if "voice_missing" in folded or "tts_degraded" in folded:
            return "degraded", "TTS motoru/sesi yok; text-mode fallback kabul edildi", "tts_voice_missing"
        return "pass", "TTS denemesi tamamlandi", "tts_ok"
    return "pass", "Adim tamamlandi", "step_ok"


def _step(name: str, action: Callable[[], str]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        output = str(action() or "")
        status, detail, reason_code = _classify_step(name, output)
        error = ""
    except Exception as exc:
        output = ""
        status = "fail"
        detail = "Adim exception ile durdu"
        reason_code = "step_exception"
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "reason_code": reason_code,
        "duration_ms": elapsed_ms,
        "output": _shorten(output),
        "error": error,
    }


def _final_status(steps: list[dict[str, Any]]) -> str:
    if any(step.get("status") == "fail" for step in steps):
        return "fail"
    if any(step.get("status") == "degraded" for step in steps):
        return "degraded"
    return "pass"


def _write_report(report: dict[str, Any], report_dir: str | Path = DEFAULT_REPORT_DIR) -> Path:
    target_dir = Path(report_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"windows-smoke-{_stamp()}.json"
    safe_report = sanitize(report, text_limit=1600)
    path.write_text(json.dumps(safe_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def run_smoke_sequence(
    *,
    ui: Any = None,
    jarvis: Any = None,
    smoke_app: str = "explorer",
    report_dir: str | Path = DEFAULT_REPORT_DIR,
    helpers: dict[str, Callable[..., Any]] | None = None,
) -> dict[str, Any]:
    helpers = helpers or {}
    started = time.perf_counter()
    started_at = _now_iso()
    _write_ui(ui, "SYS: Windows smoke basladi")

    if "web_research" in helpers:
        web_research_func = helpers["web_research"]
    else:
        from actions.web_research import research_web as web_research_func
    if "read_text_file" in helpers:
        read_text_file_func = helpers["read_text_file"]
    else:
        from actions.files import read_text_file as read_text_file_func
    if "open_app" in helpers:
        open_app_func = helpers["open_app"]
    else:
        from actions.open_app import open_app as open_app_func
    if "analyze_screen" in helpers:
        analyze_screen_func = helpers["analyze_screen"]
    else:
        from actions.screen_vision import analyze_screen as analyze_screen_func
    if "speak_text" in helpers:
        speak_text_func = helpers["speak_text"]
    else:
        from actions.tts import speak_text as speak_text_func
    if "get_available_voices" in helpers:
        voices_func = helpers["get_available_voices"]
    else:
        from actions.tts import get_available_voices as voices_func

    steps: list[dict[str, Any]] = []
    steps.append(_step("ui_open", lambda: "UI aktif" if _ui_exists(ui) else "UI aktif degil"))
    steps.append(_step("written_command", lambda: _dispatch_written_command(ui, jarvis)))
    steps.append(
        _step(
            "web_research",
            lambda: web_research_func(
                query="Python resmi belgeleri nedir",
                max_pages=2,
                open_browser=False,
            ),
        )
    )
    steps.append(_step("file_read", lambda: read_text_file_func(path="test_acceptance.ps1", max_chars=2000)))
    steps.append(_step("app_launch", lambda: open_app_func(smoke_app or "explorer")))
    steps.append(_step("screen_analysis", lambda: analyze_screen_func("JARVIS smoke test icin aktif pencereyi kisa acikla.")))

    def tts_action() -> str:
        voices = []
        try:
            voices = list(voices_func() or [])
        except Exception:
            voices = []
        speak_text_func("JARVIS Windows smoke testi tamamlandi.", blocking=True)
        return "tts_degraded: voice_missing" if not voices else f"tts_ok: {len(voices)} voices"

    steps.append(_step("tts_text_mode", tts_action))

    for step in steps:
        label = str(step.get("status", "")).upper()
        _write_ui(ui, f"SYS: SMOKE {label} - {step.get('name')}: {step.get('detail')}")

    status = _final_status(steps)
    report = {
        "kind": "windows_smoke",
        "status": status,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "smoke_app": smoke_app or "explorer",
        "steps": steps,
    }
    report_path = _write_report(report, report_dir)
    report["report_path"] = str(report_path)
    _write_ui(ui, f"SYS: Windows smoke raporu yazildi: {report_path}")
    return sanitize(report, text_limit=1600)


def build_timeout_report(timeout_seconds: int | float, report_dir: str | Path = DEFAULT_REPORT_DIR) -> dict[str, Any]:
    report = {
        "kind": "windows_smoke",
        "status": "fail",
        "reason": "timeout",
        "started_at": _now_iso(),
        "finished_at": _now_iso(),
        "timeout_seconds": timeout_seconds,
        "steps": [
            {
                "name": "timeout",
                "status": "fail",
                "detail": f"Smoke modu {timeout_seconds} saniyede tamamlanamadi.",
                "reason_code": "smoke_timeout",
                "duration_ms": 0,
                "output": "",
                "error": "timeout",
            }
        ],
    }
    report_path = _write_report(report, report_dir)
    report["report_path"] = str(report_path)
    return sanitize(report, text_limit=1600)
