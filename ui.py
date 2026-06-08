"""
JARVIS desktop — UI v3
Concentric teal rings · Segmented arcs
"""

import os, time, math, random, signal, threading
import platform
import tkinter as tk
from collections import deque
from pathlib import Path
import psutil
from PIL import Image

from app_config import has_gemini_api_key, has_text_agent_config, load_app_config, save_app_config
from actions.local_ai import test_local_ai
from actions.calendar_integrations import (
    calendar_auth_status,
    connect_calendar_provider,
    disconnect_calendar_provider,
)
from actions.plugin_system import (
    disable_plugin,
    discover_plugin_tools,
    enable_plugin,
    list_plugins,
    plugin_status,
    set_plugin_config,
)
from actions.weather import get_weather_summary

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = f"VOICE CORE · {platform.system() or 'Desktop'}"

# ── Renk paleti ──────────────────────────────────────────────────────────────
C_BG      = "#020c0c"
C_PRI     = "#00d4c0"
C_ORG     = "#ff6600"
C_ORG2    = "#ff9900"
C_MID     = "#006a62"
C_DIM     = "#0a2a28"
C_DIMMER  = "#061414"
C_TEXT    = "#7dfff6"
C_PANEL   = "#030f0f"
C_GREEN   = "#00ff88"
C_RED     = "#ff3344"
C_MUTED   = "#cc2255"
C_BLUE    = "#4488ff"
C_GOLD    = "#ffcc00"

# Orb durum renkleri
ORB_COLORS = {
    "LISTENING":    (0, 255, 136),
    "SPEAKING":     (68, 136, 255),
    "THINKING":     (255, 204, 0),
    "RESEARCHING":  (255, 153, 0),
    "WAITING_APPROVAL": (255, 204, 0),
    "MUTED":        (200, 30, 80),
    "PAUSED":       (30, 60, 55),
    "ERROR":        (255, 51, 68),
    "INITIALISING": (255, 51, 68),
}

# ── Boyutlar ─────────────────────────────────────────────────────────────────
W_TARGET = 2200
H_TARGET = 1320
LEFT_W_T = 360
RIGHT_W_T = 410
HDR_H    = 72
FOOTER_H = 26
INPUT_H  = 34
CONTROL_H = 146

VOICES = ["Charon", "Puck", "Aoede", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"]

# ── Font sistemi ─────────────────────────────────────────────────────────────
# Grift fontu kullanıcının sisteminde yüklü. Basliklarda daha sert bir vurgu
# icin ayri extra bold aile adini kullaniyoruz.
FONT_BODY_FAMILY = "Grift"
FONT_DISPLAY_FAMILY = "Grift Extra Bold"


def font_body(size: int):
    return (FONT_BODY_FAMILY, size)


def font_body_bold(size: int):
    return (FONT_BODY_FAMILY, size, "bold")


def font_display(size: int):
    return (FONT_DISPLAY_FAMILY, size)


STATE_HEX_COLORS = {
    "LISTENING": C_GREEN,
    "SPEAKING": C_BLUE,
    "THINKING": C_GOLD,
    "RESEARCHING": C_ORG2,
    "WAITING_APPROVAL": C_GOLD,
    "INITIALISING": C_RED,
    "ERROR": C_RED,
}

STATE_LABELS_TR = {
    "LISTENING": "DİNLİYOR",
    "THINKING": "DÜŞÜNÜYOR",
    "RESEARCHING": "ARAŞTIRIYOR",
    "SPEAKING": "KONUŞUYOR",
    "WAITING_APPROVAL": "ONAY BEKLİYOR",
    "ERROR": "HATA",
    "INITIALISING": "BAĞLANIYOR",
    "PAUSED": "DURAKLATILDI",
}


# ── SoundManager ─────────────────────────────────────────────────────────────
import subprocess as _sp

def _resolve_sfx_dir() -> Path:
    return BASE_DIR / "SFX"


_SFX_DIR = _resolve_sfx_dir()
_HUD_FILE = _SFX_DIR / "HUD.mp3"
_START_FILE = _SFX_DIR / "Start.mp3"
_THINK_FILE = _SFX_DIR / "Think.mp3"
_DONE_FILE = _SFX_DIR / "Done.mp3"
_ERROR_FILE = _SFX_DIR / "Error.mp3"
_IS_WINDOWS = platform.system() == "Windows"


class _PygameSoundHandle:
    _pygame = None
    _mixer_ready = False

    @classmethod
    def _ensure_mixer(cls):
        if cls._mixer_ready:
            return cls._pygame
        import pygame  # type: ignore

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        cls._pygame = pygame
        cls._mixer_ready = True
        return pygame

    def __init__(self, path: Path, volume: float):
        pygame = self._ensure_mixer()
        self._sound = pygame.mixer.Sound(str(path))
        self._sound.set_volume(max(0.0, min(1.0, float(volume))))
        self._channel = self._sound.play()
        if self._channel is None:
            raise RuntimeError("SFX kanali baslatilamadi.")

    def poll(self):
        return None if self._channel and self._channel.get_busy() else 0

    def terminate(self):
        if self._channel:
            self._channel.stop()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        started = time.time()
        while self.poll() is None:
            if timeout is not None and time.time() - started > timeout:
                raise TimeoutError("SFX bekleme zaman asimi.")
            time.sleep(0.03)
        return 0


class SoundManager:
    def __init__(self):
        self._enabled = True
        self._ambient_proc = None
        self._volume = 0.20
        self._ambient_stop = None
        self._ambient_thread = None
        self._foreground_proc = None
        self._foreground_stop = None
        self._foreground_thread = None
        self._foreground_tag = ""
        self._all_sound_procs = set()
        self._lock = threading.RLock()

    @staticmethod
    def _terminate_process(proc):
        if not proc:
            return
        if proc.poll() is not None:
            return
        killed_group = False
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            killed_group = True
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=0.6)
        except Exception:
            try:
                if killed_group:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=0.3)
            except Exception:
                pass

    def _start_afplay(self, path: Path, volume: float):
        if _IS_WINDOWS:
            proc = _PygameSoundHandle(path, volume)
        else:
            proc = _sp.Popen(
                ["afplay", "-v", f"{volume:.2f}", str(path)],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
                start_new_session=True,
            )
        with self._lock:
            self._all_sound_procs.add(proc)
        return proc

    def _forget_process(self, proc):
        if not proc:
            return
        with self._lock:
            self._all_sound_procs.discard(proc)

    def start_ambient(self):
        if not _HUD_FILE.exists():
            return
        with self._lock:
            if not self._enabled:
                return
            if self._foreground_proc and self._foreground_proc.poll() is None:
                return
            if self._ambient_thread and self._ambient_thread.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._loop_ambient,
                args=(stop_event,),
                daemon=True,
            )
            self._ambient_stop = stop_event
            self._ambient_thread = worker
        worker.start()

    def _loop_ambient(self, stop_event: threading.Event):
        while not stop_event.is_set():
            with self._lock:
                if not self._enabled or self._ambient_stop is not stop_event:
                    break
                volume = self._volume
            try:
                proc = self._start_afplay(_HUD_FILE, volume)
            except Exception:
                break

            with self._lock:
                if self._ambient_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._ambient_proc = proc

            while proc.poll() is None and not stop_event.wait(0.2):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._ambient_proc is proc:
                    self._ambient_proc = None
            if proc.poll() is not None:
                self._forget_process(proc)

            if stop_event.is_set():
                break
            time.sleep(0.2)

        with self._lock:
            if self._ambient_stop is stop_event:
                self._ambient_stop = None
            if self._ambient_thread and self._ambient_thread.ident == threading.get_ident():
                self._ambient_thread = None

    def _stop_ambient(self):
        with self._lock:
            stop_event = self._ambient_stop
            proc = self._ambient_proc
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def _stop_foreground(self):
        with self._lock:
            stop_event = self._foreground_stop
            proc = self._foreground_proc
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def _play_foreground(
        self,
        path: Path,
        tag: str,
        loop: bool = False,
        volume_factor: float = 1.0,
        pause_ambient: bool = True,
    ):
        if not path.exists():
            return
        with self._lock:
            if not self._enabled:
                return
            if loop and self._foreground_tag == tag and self._foreground_thread and self._foreground_thread.is_alive():
                return
            base_volume = self._volume
        if pause_ambient:
            self._stop_ambient()
        self._stop_foreground()

        stop_event = threading.Event()
        worker = threading.Thread(
            target=self._foreground_worker,
            args=(
                path,
                tag,
                stop_event,
                loop,
                max(0.0, min(1.0, base_volume * volume_factor)),
                pause_ambient,
            ),
            daemon=True,
        )
        with self._lock:
            self._foreground_stop = stop_event
            self._foreground_thread = worker
            self._foreground_tag = tag
        worker.start()

    def _foreground_worker(
        self,
        path: Path,
        tag: str,
        stop_event: threading.Event,
        loop: bool,
        volume: float,
        resume_ambient: bool,
    ):
        while not stop_event.is_set():
            try:
                proc = self._start_afplay(path, volume)
            except Exception:
                break

            with self._lock:
                if self._foreground_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._foreground_proc = proc

            while proc.poll() is None and not stop_event.wait(0.12):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._foreground_proc is proc:
                    self._foreground_proc = None
            if proc.poll() is not None:
                self._forget_process(proc)

            if not loop or stop_event.is_set():
                break
            time.sleep(0.08)

        with self._lock:
            if self._foreground_stop is stop_event:
                self._foreground_stop = None
                self._foreground_thread = None
                self._foreground_tag = ""
            should_restart = resume_ambient and self._enabled and self._foreground_stop is None
        if should_restart:
            self.start_ambient()

    def play_startup(self):
        self._play_foreground(_START_FILE, tag="start", loop=False, volume_factor=0.95)

    def play_success(self):
        self._play_foreground(
            _DONE_FILE,
            tag="done",
            loop=False,
            volume_factor=0.68,
            pause_ambient=False,
        )

    def play_error(self):
        self._play_foreground(_ERROR_FILE, tag="error", loop=False, volume_factor=0.95)

    def start_thinking(self):
        self._play_foreground(
            _THINK_FILE,
            tag="think",
            loop=True,
            volume_factor=0.82,
            pause_ambient=False,
        )

    def stop_thinking(self):
        with self._lock:
            is_thinking = self._foreground_tag == "think"
        if is_thinking:
            self._stop_foreground()

    def toggle(self) -> bool:
        self.set_enabled(not self._enabled)
        return self._enabled

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        with self._lock:
            self._enabled = enabled
        if enabled:
            self.start_ambient()
        else:
            self._stop_ambient()
            self._stop_foreground()

    def set_volume(self, volume: float):
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))
            fg_tag = self._foreground_tag
            can_restart_ambient = self._enabled and not fg_tag
        if fg_tag == "think":
            self._stop_foreground()
            self.start_thinking()
        elif can_restart_ambient:
            self._stop_ambient()
            self.start_ambient()

    def stop_all(self):
        with self._lock:
            self._enabled = False
            ambient_stop = self._ambient_stop
            foreground_stop = self._foreground_stop
            procs = {
                proc
                for proc in (
                    self._ambient_proc,
                    self._foreground_proc,
                    *self._all_sound_procs,
                )
                if proc
            }
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
            self._all_sound_procs.clear()
        if ambient_stop:
            ambient_stop.set()
        if foreground_stop:
            foreground_stop.set()
        for proc in procs:
            self._terminate_process(proc)

    def get_volume(self) -> float:
        return self._volume


# ─────────────────────────────────────────────────────────────────────────────

class JarvisUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.update_idletasks()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        margin_x = max(24, int(sw * 0.025))
        margin_y = max(54, int(sh * 0.055))
        self.W = min(max(640, sw - margin_x), sw, W_TARGET)
        self.H = min(max(520, sh - margin_y), sh, H_TARGET)
        _geo = f"{self.W}x{self.H}+{(sw-self.W)//2}+{max(0, (sh-self.H)//2 - 8)}"
        self.root.geometry(_geo)
        self.root.minsize(min(self.W, sw), min(self.H, sh))
        self.root.resizable(True, True)
        self.root.configure(bg=C_BG)
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()
        # Window manager bazen geometry'yi override eder, tekrar zorla.
        for delay in (80, 220, 600, 1200):
            self.root.after(delay, self._force_startup_size)
        # Birkaç saniye sonra topmost'u kapat (normal davranış)
        self.root.after(3000, lambda: self.root.attributes('-topmost', False))

        self._window_geometry = _geo
        self._normal_size = (self.W, self.H)
        self._fullscreen = True

        self._set_layout_metrics(self.W, self.H)

        # ── State ────────────────────────────────────────────────────────────
        self.speaking        = False
        self.user_speaking   = False
        self.muted           = False
        self.paused          = False
        self.text_mode       = False
        self.ptt_active      = False
        self.wake_ready      = False
        self.wake_status     = "Wake word kapali; PTT hazir."
        self._ptt_key_down   = False
        self._wake_toggle_var = None
        self.scale           = 1.0
        self.target_scale    = 1.0
        self.halo_a          = 55.0
        self.target_halo     = 55.0
        self.last_t          = time.time()
        self.tick            = 0
        self.rings_spin      = [0.0, 45.0, 90.0, 200.0]  # 4 ayrı halka
        self.pulse_r         = []
        self.status_blink    = True
        self._jarvis_state   = "INITIALISING"
        self._user_speaking_until = 0.0

        # ── Health overlay ───────────────────────────────────────────────────
        self._health_visible  = False
        self._health_query    = "all"
        self._health_display  = ""
        self._health_hide_job = None
        self._weather_card = {
            "city": "Istanbul",
            "primary": "--",
            "details": ["Hava durumu yükleniyor..."],
        }
        self._health_card_lines = ["Sağlık özeti yükleniyor..."]
        self._panel_focus = ""
        self._panel_focus_until = 0.0
        self._brief_refresh_busy = False
        self._started_at = time.time()
        self._error_hold_until = 0.0
        self._settings_open = False
        self._settings_tab = "settings"
        self._debug_entries = deque(maxlen=160)
        self._startup_sfx_played = False
        self._settings_geometry = {
            "btn_x": 14,
            "btn_y": 12,
            "btn_w": 250,
            "btn_h": 46,
            "panel_x": 14,
            "panel_y": HDR_H + 10,
            "panel_w": 320,
            "panel_h": 292,
        }
        self.setup_frame = None
        self.integrations_frame = None
        self.plugins_frame = None
        self.api_entry = None
        self.youtube_api_entry = None
        self.youtube_handle_entry = None
        self.tavily_api_entry = None
        self.agent_provider_var = None
        self.ninerouter_url_entry = None
        self.ninerouter_model_entry = None
        self.ninerouter_key_entry = None
        self.local_provider_var = None
        self.local_url_entry = None
        self.local_model_entry = None
        self.local_key_entry = None
        self.local_foundry_alias_entry = None
        self.plugin_id_entry = None
        self.plugin_config_text = None
        self.plugin_output_text = None
        self.local_auto_start_var = None
        self.calendar_provider_var = None
        self.outlook_client_entry = None
        self.outlook_tenant_entry = None
        self.google_client_entry = None
        self.google_secret_entry = None

        # ── Callbacks ────────────────────────────────────────────────────────
        self.on_text_command = None
        self.on_pause_toggle = None
        self.on_stop_command = None
        self.on_voice_change = None
        self.on_effects_state_change = None
        self.on_ptt_start = None
        self.on_ptt_stop = None
        self.on_wake_toggle = None

        # ── Voice ────────────────────────────────────────────────────────────
        self._current_voice = self._load_voice()

        # ── Sound ────────────────────────────────────────────────────────────
        self.sound = SoundManager()

        # ── Stats ────────────────────────────────────────────────────────────
        self._stats      = {'cpu': 0.0, 'ram': 0.0, 'disk': 0.0,
                            'battery': 100.0, 'net_up': 0.0, 'net_down': 0.0}
        self._cpu_hist   = [0.0] * 24
        self._last_net   = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._wave_jarvis = [random.randint(4, 26) for _ in range(18)]
        self._wave_user   = [random.randint(2, 10) for _ in range(18)]

        # ── Typing ───────────────────────────────────────────────────────────
        self.typing_queue = deque()
        self.is_typing    = False

        # ── Partiküller (arka plan, az sayıda) ───────────────────────────────
        self.particles = [
            {
                'x':  random.uniform(0, self.W),
                'y':  random.uniform(0, self.H),
                'vx': random.uniform(-0.15, 0.15),
                'vy': random.uniform(-0.15, 0.15),
                'r':  random.uniform(0.5, 1.8),
                'a':  random.randint(15, 70),
            }
            for _ in range(24)
        ]

        self.orb_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'orbit': random.uniform(0.06, 0.98),
                'speed': random.uniform(-0.030, 0.030),
                'size': random.uniform(0.8, 2.8),
                'phase': random.uniform(0, math.tau),
                'wobble': random.uniform(0.010, 0.040),
                'depth': random.uniform(0.30, 1.00),
            }
            for _ in range(160)
        ]
        self.orb_shell_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'speed': random.uniform(-0.020, 0.020),
                'size': random.uniform(1.4, 3.8),
                'phase': random.uniform(0, math.tau),
                'glow': random.uniform(0.4, 1.0),
            }
            for _ in range(84)
        ]

        # ── Canvas ───────────────────────────────────────────────────────────
        self.bg = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        # ── Log ──────────────────────────────────────────────────────────────
        self.log_frame = tk.Frame(self.root, bg="#030e0e",
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y,
                             width=self.CHAT_W, height=self.CHAT_H)
        self.log_text = tk.Text(
            self.log_frame, fg=C_TEXT, bg="#030e0e",
            insertbackground=C_TEXT, borderwidth=0,
            wrap="word", font=font_body(12), padx=12, pady=8)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#d0f0ee")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_GOLD)
        self.log_text.tag_config("err", foreground=C_RED)

        self._build_input_bar(self.CHAT_W)
        self._build_mute_button()
        self._build_pause_button()
        self._build_ptt_button()
        self._build_shutdown_button()
        self._build_settings_panel()
        self._build_voice_selector(self._settings_body)
        self._build_sfx_button(self._settings_body)
        self._build_wake_toggle(self._settings_body)
        self._build_api_button(self._settings_body)
        self._build_integrations_button(self._settings_body)
        self._build_plugins_button(self._settings_body)
        self._build_fx_slider(self._settings_body)
        self._layout_settings_controls()
        self._place_layout_widgets()

        # Orb tıklama = pause/resume
        self.bg.bind("<Button-1>", self._on_canvas_click)

        self.root.bind("<F4>",        lambda e: self._toggle_mute())
        self.root.bind("<Command-m>", lambda e: self._toggle_mute())
        self.root.bind("<Control-m>", lambda e: self._toggle_mute())
        self.root.bind("<Escape>",    lambda e: self._shutdown())
        self.root.bind("<F5>",        lambda e: self._toggle_pause())
        self.root.bind_all("<KeyPress-space>", self._on_ptt_key_press)
        self.root.bind_all("<KeyRelease-space>", self._on_ptt_key_release)
        self.root.bind("<F11>",       lambda e: self._toggle_fullscreen())
        self.root.bind("<Command-f>", lambda e: self._toggle_fullscreen())
        self.root.bind("<Control-f>", lambda e: self._toggle_fullscreen())

        self._api_key_ready = has_gemini_api_key() or has_text_agent_config()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._effects_active = None
        self._sync_sound_state()
        self.root.after(180, self._play_startup_sfx_once)
        self._kick_brief_refresh()
        self.root.after(120, self._enter_fullscreen)
        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)

    def _force_startup_size(self):
        if self._fullscreen:
            self._enter_fullscreen()
            return
        self.root.geometry(self._window_geometry)
        self._resize_surface(*self._normal_size)
        self.root.update_idletasks()

    def _enter_fullscreen(self):
        sw = max(self.root.winfo_screenwidth(), self.root.winfo_width(), self.W)
        sh = max(self.root.winfo_screenheight(), self.root.winfo_height(), self.H)
        self.root.attributes("-fullscreen", True)
        self.root.geometry(f"{sw}x{sh}+0+0")
        self._resize_surface(sw, sh)

    def _set_layout_metrics(self, width: int, height: int):
        self.W = int(width)
        self.H = int(height)
        self.LEFT_W = min(LEFT_W_T, int(self.W * 0.23))
        self.RIGHT_W = min(RIGHT_W_T, int(self.W * 0.25))
        center_w = self.W - self.LEFT_W - self.RIGHT_W
        orb_area_h = self.H - HDR_H - CONTROL_H - FOOTER_H - 24
        self.FCX = self.LEFT_W + center_w // 2
        self.FCY = HDR_H + orb_area_h // 2 + 6
        self.FACE = min(int(orb_area_h * 0.90), int(center_w * 0.86), 860)

        self.CENTER_X0 = self.LEFT_W
        self.CENTER_X1 = self.W - self.RIGHT_W
        self.CTRL_X = self.LEFT_W + 18
        self.CTRL_Y = HDR_H + orb_area_h + 2
        self.CTRL_W = center_w - 36
        self.CHAT_PANEL_X = self.W - self.RIGHT_W + 8
        self.CHAT_PANEL_Y = HDR_H + 8
        self.CHAT_PANEL_W = self.RIGHT_W - 14
        self.CHAT_PANEL_H = self.H - HDR_H - FOOTER_H - 16
        self.CHAT_X = self.CHAT_PANEL_X + 10
        self.CHAT_Y = self.CHAT_PANEL_Y + 34
        self.CHAT_W = self.CHAT_PANEL_W - 20
        self.CHAT_H = self.CHAT_PANEL_H - 90
        self.CHAT_INPUT_Y = self.CHAT_PANEL_Y + self.CHAT_PANEL_H - INPUT_H - 10

    # ── Voice ─────────────────────────────────────────────────────────────────
    def _load_voice(self) -> str:
        try:
            return str(load_app_config().get("voice", "Charon") or "Charon")
        except Exception:
            return "Charon"

    # ── Shutdown button (sağ alt, büyük) ────────────────────────────────────
    def _build_shutdown_button(self):
        BW, BH = 140, 36
        self._shutdown_canvas = tk.Canvas(
            self.root, width=BW, height=BH,
            bg=C_BG, highlightthickness=0, cursor="hand2")
        self._shutdown_canvas.bind("<Button-1>", lambda e: self._shutdown())
        self._draw_shutdown_button()

    def _draw_shutdown_button(self):
        c = self._shutdown_canvas
        BW, BH = 140, 36
        c.delete("all")
        # Köşe braket stili
        bl = 8
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=C_RED, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=C_RED, width=2)
        c.create_text(BW//2, BH//2, text="⏻  SHUTDOWN",
                      fill=C_RED, font=font_display(11))

    def _build_settings_panel(self):
        geo = self._settings_geometry
        self._settings_btn_canvas = tk.Canvas(
            self.root,
            width=geo["btn_w"],
            height=geo["btn_h"],
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_btn_canvas.place(x=geo["btn_x"], y=geo["btn_y"])
        self._settings_btn_canvas.bind("<Button-1>", lambda e: self._toggle_settings_panel())
        self._draw_settings_button()

        self._settings_panel = tk.Frame(
            self.root,
            bg="#041111",
            highlightbackground=C_MID,
            highlightthickness=1,
        )
        self._settings_panel.place_forget()

        self._settings_title = tk.Label(
            self._settings_panel,
            text="SETTINGS",
            fg=C_PRI,
            bg="#041111",
            font=font_display(11),
        )
        self._settings_tab_settings = tk.Canvas(
            self._settings_panel,
            width=108,
            height=28,
            bg="#041111",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_settings.bind("<Button-1>", lambda e: self._set_settings_tab("settings"))
        self._settings_tab_debug = tk.Canvas(
            self._settings_panel,
            width=96,
            height=28,
            bg="#041111",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_debug.bind("<Button-1>", lambda e: self._set_settings_tab("debug"))
        self._settings_body = tk.Frame(self._settings_panel, bg="#041111")
        self._debug_body = tk.Frame(self._settings_panel, bg="#041111")
        self._settings_sfx_label = tk.Label(
            self._settings_body,
            text="SFX",
            fg=C_MID,
            bg="#041111",
            font=font_body_bold(8),
        )
        self._settings_status_primary = tk.Label(
            self._settings_body,
            text="",
            fg=C_TEXT,
            bg="#041111",
            font=font_body_bold(9),
            anchor="w",
            justify="left",
        )
        self._settings_status_secondary = tk.Label(
            self._settings_body,
            text="",
            fg=C_MID,
            bg="#041111",
            font=font_body(9),
            anchor="w",
            justify="left",
        )
        self._debug_text = tk.Text(
            self._debug_body,
            fg=C_TEXT,
            bg="#020a0a",
            insertbackground=C_TEXT,
            borderwidth=0,
            wrap="word",
            font=font_body(10),
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground=C_DIM,
        )
        self._debug_text.tag_config("info", foreground=C_TEXT)
        self._debug_text.tag_config("warn", foreground=C_GOLD)
        self._debug_text.tag_config("err", foreground=C_RED)
        self._debug_text.configure(state="disabled")
        self._draw_settings_tabs()
        self._render_debug_logs()
        self._refresh_settings_status()

    def _draw_settings_button(self):
        c = self._settings_btn_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        accent = C_BLUE if self._settings_open else C_MID
        inner = "#062020" if self._settings_open else "#021010"
        c.create_rectangle(0, 0, bw, bh, fill=inner, outline="")
        bl = 9
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=accent, width=2)
            c.create_line(bx, by, bx, by + sy * bl, fill=accent, width=2)
        c.create_text(14, 15, text="SYSTEM SETTINGS", fill=C_PRI, font=font_display(10), anchor="w")
        c.create_text(14, 33, text=MODEL_BADGE, fill="#4f7b78", font=font_body(9), anchor="w")
        c.create_text(bw - 14, bh // 2, text="▾" if self._settings_open else "▸",
                      fill=accent, font=font_display(14), anchor="e")

    def _toggle_settings_panel(self):
        self._settings_open = not self._settings_open
        self._draw_settings_button()
        self._place_layout_widgets()

    def _draw_settings_tabs(self):
        for key, canvas, label in (
            ("settings", self._settings_tab_settings, "SETTINGS"),
            ("debug", self._settings_tab_debug, "DEBUG"),
        ):
            active = self._settings_tab == key
            bw = int(canvas["width"])
            bh = int(canvas["height"])
            canvas.delete("all")
            outline = C_PRI if active else C_DIM
            fill = "#082020" if active else "#041111"
            text_col = C_PRI if active else "#5ea7a0"
            canvas.create_rectangle(0, 0, bw, bh, fill=fill, outline="")
            bl = 7
            for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
                canvas.create_line(bx, by, bx + sx * bl, by, fill=outline, width=1)
                canvas.create_line(bx, by, bx, by + sy * bl, fill=outline, width=1)
            canvas.create_text(bw // 2, bh // 2, text=label, fill=text_col, font=font_body_bold(9))

    def _set_settings_tab(self, tab: str):
        self._settings_tab = "debug" if tab == "debug" else "settings"
        self._draw_settings_tabs()
        self._place_layout_widgets()

    def _layout_settings_controls(self):
        inner_w = self._settings_geometry["panel_w"] - 24
        self._api_canvas.place(x=0, y=2)
        self._integrations_canvas.place(x=0, y=34)
        self._plugins_canvas.place(x=0, y=66)
        self._sfx_canvas.place(x=inner_w - int(self._sfx_canvas["width"]) - 4, y=0)
        self._settings_status_primary.place(x=0, y=104, width=inner_w)
        self._settings_status_secondary.place(x=0, y=124, width=inner_w)
        self._settings_sfx_label.place(x=0, y=154)
        self._volume_label.place(x=0, y=174)
        self._volume_scale.place(x=0, y=192, width=inner_w, height=24)
        self._wake_check.place(x=0, y=224)
        self._wake_status_label.place(x=116, y=228, width=inner_w - 116)
        self._voice_label.place(x=0, y=258)
        self._voice_menu.place(x=88, y=252, width=inner_w - 88, height=30)

    def _refresh_settings_status(self):
        if not hasattr(self, "_settings_status_primary"):
            return
        cfg = load_app_config()
        gemini_ready = bool(str(cfg.get("gemini_api_key", "") or "").strip())
        cloud_ready = all(
            str(cfg.get(key, "") or "").strip()
            for key in ("cloud_base_url", "cloud_model", "cloud_api_key")
        )
        local_provider = str(cfg.get("local_provider", "foundry_local") or "foundry_local").strip()
        local_ready = bool(
            (local_provider == "foundry_local" and str(cfg.get("local_foundry_model_alias", "") or "").strip())
            or (str(cfg.get("local_base_url", "") or "").strip() and str(cfg.get("local_model", "") or "").strip())
        )
        provider = str(cfg.get("agent_mode", "hybrid") or "hybrid").strip()
        yt_key_ready = bool(str(cfg.get("youtube_api_key", "") or "").strip())
        yt_handle = str(cfg.get("youtube_channel_handle", "") or "").strip()
        tavily_ready = bool(str(cfg.get("tavily_api_key", "") or "").strip())
        calendar_provider = str(cfg.get("calendar_provider", "outlook") or "outlook").strip()

        primary = [
            "Gemini hazir" if gemini_ready else "Gemini API eksik",
            f"Mod: {provider}",
            "Cloud hazir" if cloud_ready else "Cloud eksik",
            "Local hazir" if local_ready else "Local eksik",
            "Tavily hazir" if tavily_ready else "Tavily opsiyonel",
            f"Takvim: {calendar_provider}",
        ]
        if yt_handle:
            handle_text = yt_handle
        else:
            handle_text = "@handle girilmedi"
        voice_mode = str(cfg.get("voice_input_mode", "ptt_wake") or "ptt_wake")
        secondary = f"Kanal: {handle_text}  ·  Ses: {voice_mode}  ·  {self.wake_status[:90]}"

        self._settings_status_primary.configure(text="  ·  ".join(primary))
        self._settings_status_secondary.configure(text=secondary)

    def _build_wake_toggle(self, parent=None):
        parent = parent or self.root
        cfg = load_app_config()
        self._wake_toggle_var = tk.BooleanVar(value=bool(cfg.get("wake_word_enabled", False)))
        self._wake_check = tk.Checkbutton(
            parent,
            text="WAKE",
            variable=self._wake_toggle_var,
            command=self._on_wake_toggle_clicked,
            fg=C_TEXT,
            bg=parent.cget("bg"),
            activeforeground=C_PRI,
            activebackground=parent.cget("bg"),
            selectcolor="#000d12",
            font=font_body_bold(9),
            borderwidth=0,
        )
        self._wake_status_label = tk.Label(
            parent,
            text=self.wake_status,
            fg=C_GREEN if self.wake_ready else C_GOLD,
            bg=parent.cget("bg"),
            font=font_body(9),
            anchor="w",
        )

    def _on_wake_toggle_clicked(self):
        enabled = bool(self._wake_toggle_var.get()) if self._wake_toggle_var is not None else False
        save_app_config({"wake_word_enabled": enabled})
        self.write_log(f"SYS: Wake word {'acildi' if enabled else 'kapatildi'}.")
        if self.on_wake_toggle:
            threading.Thread(target=self.on_wake_toggle, args=(enabled,), daemon=True).start()

    def write_debug(self, text: str, level: str = "INFO"):
        clean = " ".join(str(text or "").split())
        if not clean:
            return
        self.root.after(0, self._append_debug_entry, clean, level)

    def _append_debug_entry(self, text: str, level: str = "INFO"):
        stamp = time.strftime("%H:%M:%S")
        lvl = (level or "INFO").upper()
        self._debug_entries.append((lvl, f"[{stamp}] {lvl}: {text}"))
        self._render_debug_logs()

    def _render_debug_logs(self):
        if not hasattr(self, "_debug_text"):
            return
        self._debug_text.configure(state="normal")
        self._debug_text.delete("1.0", tk.END)
        if not self._debug_entries:
            self._debug_text.insert(tk.END, "Henüz not edilebilir hata yok.\n", "info")
        else:
            for level, line in self._debug_entries:
                tag = "err" if level == "ERROR" else "warn" if level == "WARN" else "info"
                self._debug_text.insert(tk.END, line + "\n", tag)
        self._debug_text.see(tk.END)
        self._debug_text.configure(state="disabled")

    def _build_api_button(self, parent=None):
        parent = parent or self.root
        bw, bh = 154, 28
        self._api_canvas = tk.Canvas(
            parent, width=bw, height=bh,
            bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._api_canvas.bind("<Button-1>", lambda e: self._open_api_settings())
        self._draw_api_button()

    def _draw_api_button(self):
        c = self._api_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=C_BLUE, width=1)
            c.create_line(bx, by, bx, by + sy * bl, fill=C_BLUE, width=1)
        c.create_text(bw // 2, bh // 2, text="⌘ API SETTINGS",
                      fill=C_BLUE, font=font_body_bold(10))

    def _build_integrations_button(self, parent=None):
        parent = parent or self.root
        bw, bh = 154, 28
        self._integrations_canvas = tk.Canvas(
            parent, width=bw, height=bh,
            bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._integrations_canvas.bind("<Button-1>", lambda e: self._open_integrations_settings())
        self._draw_integrations_button()

    def _draw_integrations_button(self):
        c = self._integrations_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=C_GOLD, width=1)
            c.create_line(bx, by, bx, by + sy * bl, fill=C_GOLD, width=1)
        c.create_text(bw // 2, bh // 2, text="INTEGRATIONS",
                      fill=C_GOLD, font=font_body_bold(10))

    def _build_fx_slider(self, parent=None):
        parent = parent or self.root
        slider_w = 280
        self._volume_label = tk.Label(
            parent,
            text=f"FX LEVEL  {int(self.sound.get_volume() * 100)}%",
            fg=C_PRI,
            bg=parent.cget("bg"),
            font=font_body_bold(10),
        )
        self._volume_scale = tk.Scale(
            parent,
            from_=0,
            to=100,
            orient="horizontal",
            length=slider_w,
            showvalue=False,
            resolution=1,
            troughcolor="#071818",
            bg=parent.cget("bg"),
            fg=C_TEXT,
            activebackground=C_PRI,
            highlightthickness=0,
            borderwidth=0,
            sliderlength=18,
            width=10,
            command=self._on_volume_change,
        )
        self._volume_scale.set(int(self.sound.get_volume() * 100))

    def _on_volume_change(self, value):
        try:
            volume = max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return
        self._volume_label.configure(text=f"FX LEVEL  {volume}%")
        self.sound.set_volume(volume / 100.0)

    def _play_startup_sfx_once(self):
        pass

    def _sync_sound_state(self):
        enabled = self._sfx_on and not self.paused
        self.sound.set_enabled(enabled)
        if enabled and self._jarvis_state == "THINKING":
            self.sound.start_thinking()
        if enabled != self._effects_active:
            self._effects_active = enabled
            if self.on_effects_state_change:
                threading.Thread(
                    target=self.on_effects_state_change,
                    args=(enabled,),
                    daemon=True,
                ).start()

    def _open_api_settings(self):
        self._close_integrations_ui()
        self._close_plugins_ui()
        self._show_setup_ui(edit_mode=self._api_key_ready)

    def _close_setup_ui(self):
        if self.setup_frame and self.setup_frame.winfo_exists():
            self.setup_frame.destroy()
        self.setup_frame = None
        self.api_entry = None
        self.youtube_api_entry = None
        self.youtube_handle_entry = None
        self.tavily_api_entry = None
        self.agent_provider_var = None
        self.ninerouter_url_entry = None
        self.ninerouter_model_entry = None
        self.ninerouter_key_entry = None
        self.local_provider_var = None
        self.local_url_entry = None
        self.local_model_entry = None
        self.local_key_entry = None
        self.local_foundry_alias_entry = None
        self.local_auto_start_var = None

    def _open_integrations_settings(self):
        self._close_plugins_ui()
        self._show_integrations_ui()

    def _close_integrations_ui(self):
        if self.integrations_frame and self.integrations_frame.winfo_exists():
            self.integrations_frame.destroy()
        self.integrations_frame = None
        self.calendar_provider_var = None
        self.outlook_client_entry = None
        self.outlook_tenant_entry = None
        self.google_client_entry = None
        self.google_secret_entry = None

    def _build_plugins_button(self, parent=None):
        parent = parent or self.root
        bw, bh = 154, 28
        self._plugins_canvas = tk.Canvas(
            parent, width=bw, height=bh,
            bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._plugins_canvas.bind("<Button-1>", lambda e: self._open_plugins_settings())
        self._draw_plugins_button()

    def _draw_plugins_button(self):
        c = self._plugins_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=C_GREEN, width=1)
            c.create_line(bx, by, bx, by + sy * bl, fill=C_GREEN, width=1)
        c.create_text(bw // 2, bh // 2, text="PLUGINS",
                      fill=C_GREEN, font=font_body_bold(10))

    def _open_plugins_settings(self):
        self._close_setup_ui()
        self._close_integrations_ui()
        self._show_plugins_ui()

    def _close_plugins_ui(self):
        if self.plugins_frame and self.plugins_frame.winfo_exists():
            self.plugins_frame.destroy()
        self.plugins_frame = None
        self.plugin_id_entry = None
        self.plugin_config_text = None
        self.plugin_output_text = None

    def _plugin_output(self, text: str):
        if self.plugin_output_text and self.plugin_output_text.winfo_exists():
            self.plugin_output_text.configure(state="normal")
            self.plugin_output_text.delete("1.0", tk.END)
            self.plugin_output_text.insert(tk.END, str(text or ""))
            self.plugin_output_text.configure(state="disabled")

    def _selected_plugin_id(self) -> str:
        return self.plugin_id_entry.get().strip() if self.plugin_id_entry else ""

    def _show_plugins_ui(self):
        self._close_plugins_ui()
        frame = tk.Frame(self.root, bg="#00080d", highlightbackground=C_GREEN, highlightthickness=1)
        self.plugins_frame = frame
        setup_w = min(820, max(620, int(self.W * 0.44)))
        setup_h = min(max(560, self.H - 150), max(650, int(self.H * 0.62)))
        frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        frame.pack_propagate(False)

        tk.Label(frame, text="PLUGINS / MCP",
                 fg=C_GREEN, bg="#00080d", font=font_display(18)).pack(pady=(16, 4))
        tk.Label(frame, text="Pluginler varsayilan kapali; MCP icin stdio veya Streamable HTTP config gir.",
                 fg=C_MID, bg="#00080d", font=font_body(10)).pack(pady=(0, 8))

        row = tk.Frame(frame, bg="#00080d")
        row.pack(fill="x", padx=24, pady=(0, 6))
        tk.Label(row, text="PLUGIN ID",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(side="left", padx=(0, 8))
        self.plugin_id_entry = tk.Entry(row, width=24, fg=C_TEXT, bg="#000d12",
                                        insertbackground=C_TEXT, borderwidth=0, font=font_body(10))
        self.plugin_id_entry.pack(side="left", ipady=3)
        self.plugin_id_entry.insert(0, "github")

        tk.Label(frame, text="CONFIG JSON",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(anchor="w", padx=24, pady=(4, 2))
        self.plugin_config_text = tk.Text(frame, height=6, width=86, fg=C_TEXT, bg="#000d12",
                                          insertbackground=C_TEXT, borderwidth=0, font=font_body(9),
                                          wrap="word")
        self.plugin_config_text.pack(fill="x", padx=24, pady=(0, 6))
        self.plugin_config_text.insert(
            tk.END,
            '{\n  "transport": "stdio",\n  "command": "",\n  "args": []\n}'
        )

        self.plugin_output_text = tk.Text(frame, height=13, width=86, fg=C_TEXT, bg="#020a0a",
                                          insertbackground=C_TEXT, borderwidth=0, font=font_body(9),
                                          wrap="word", padx=10, pady=8)
        self.plugin_output_text.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        self.plugin_output_text.configure(state="disabled")
        self._plugin_output(list_plugins())

        buttons = tk.Frame(frame, bg="#00080d")
        buttons.pack(side="bottom", pady=(8, 14))
        for label, command, fg in (
            ("YENILE", lambda: self._plugin_output(list_plugins()), C_PRI),
            ("DURUM", lambda: self._plugin_output(plugin_status(self._selected_plugin_id())), C_BLUE),
            ("AC", self._plugin_enable_from_ui, C_GREEN),
            ("KAPAT", self._plugin_disable_from_ui, C_RED),
            ("CONFIG KAYDET", self._plugin_save_config_from_ui, C_GOLD),
            ("DISCOVER", self._plugin_discover_from_ui, C_PRI),
            ("PANEL KAPAT", self._close_plugins_ui, C_DIM),
        ):
            tk.Button(buttons, text=label, command=command, bg="#08111a", fg=fg,
                      activebackground="#10202b", font=font_body_bold(10),
                      borderwidth=0, padx=10, pady=7).pack(side="left", padx=4)

    def _plugin_config_json(self) -> str:
        if not self.plugin_config_text:
            return "{}"
        return self.plugin_config_text.get("1.0", tk.END).strip() or "{}"

    def _plugin_enable_from_ui(self):
        result = enable_plugin(self._selected_plugin_id())
        self._plugin_output(result)
        self.write_log("SYS: " + result.replace("\n", " | "))

    def _plugin_disable_from_ui(self):
        result = disable_plugin(self._selected_plugin_id())
        self._plugin_output(result)
        self.write_log("SYS: " + result.replace("\n", " | "))

    def _plugin_save_config_from_ui(self):
        result = set_plugin_config(self._selected_plugin_id(), self._plugin_config_json(), True)
        self._plugin_output(result)
        self.write_log("SYS: Plugin config kaydedildi.")

    def _plugin_discover_from_ui(self):
        plugin_id = self._selected_plugin_id()
        self._plugin_output("MCP tool kesfi baslatildi...")

        def worker():
            result = discover_plugin_tools(plugin_id)
            self.root.after(0, lambda: self._plugin_output(result))
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))

        threading.Thread(target=worker, daemon=True).start()

    def _show_integrations_ui(self):
        self._close_setup_ui()
        self._close_integrations_ui()
        config = load_app_config()
        frame = tk.Frame(self.root, bg="#00080d", highlightbackground=C_GOLD, highlightthickness=1)
        self.integrations_frame = frame
        setup_w = min(760, max(560, int(self.W * 0.40)))
        setup_h = min(max(500, self.H - 160), max(560, int(self.H * 0.58)))
        frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        frame.pack_propagate(False)

        tk.Label(frame, text="INTEGRATIONS / OAUTH",
                 fg=C_GOLD, bg="#00080d", font=font_display(18)).pack(pady=(18, 4))
        tk.Label(frame, text="Outlook/Google takvim, animsatici ve sonraki e-posta hazirligi",
                 fg=C_MID, bg="#00080d", font=font_body(10)).pack(pady=(0, 8))

        tk.Label(frame, text="CALENDAR PROVIDER",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        provider_label = "Google" if str(config.get("calendar_provider", "outlook")).lower() == "google" else "Outlook"
        self.calendar_provider_var = tk.StringVar(value=provider_label)
        provider_menu = tk.OptionMenu(frame, self.calendar_provider_var, "Outlook", "Google")
        provider_menu.config(width=48, fg=C_TEXT, bg="#000d12", activeforeground=C_BG,
                             activebackground=C_PRI, font=font_body(10), borderwidth=0,
                             highlightthickness=1, highlightbackground=C_MID)
        provider_menu["menu"].config(fg=C_PRI, bg=C_PANEL, font=font_body(10),
                                      activeforeground=C_BG, activebackground=C_PRI)
        provider_menu.pack(pady=(0, 4), ipady=2)

        tk.Label(frame, text="OUTLOOK CLIENT ID",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        self.outlook_client_entry = tk.Entry(frame, width=56, fg=C_TEXT, bg="#000d12",
                                             insertbackground=C_TEXT, borderwidth=0, font=font_body(10))
        self.outlook_client_entry.pack(pady=(0, 3), ipady=3)
        if config.get("outlook_client_id"):
            self.outlook_client_entry.insert(0, str(config.get("outlook_client_id", "")))

        tk.Label(frame, text="OUTLOOK TENANT ID / common",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        self.outlook_tenant_entry = tk.Entry(frame, width=56, fg=C_TEXT, bg="#000d12",
                                             insertbackground=C_TEXT, borderwidth=0, font=font_body(10))
        self.outlook_tenant_entry.pack(pady=(0, 3), ipady=3)
        self.outlook_tenant_entry.insert(0, str(config.get("outlook_tenant_id", "common") or "common"))

        tk.Label(frame, text="GOOGLE OAUTH CLIENT ID",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        self.google_client_entry = tk.Entry(frame, width=56, fg=C_TEXT, bg="#000d12",
                                            insertbackground=C_TEXT, borderwidth=0, font=font_body(10))
        self.google_client_entry.pack(pady=(0, 3), ipady=3)
        if config.get("google_oauth_client_id"):
            self.google_client_entry.insert(0, str(config.get("google_oauth_client_id", "")))

        tk.Label(frame, text="GOOGLE OAUTH CLIENT SECRET",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        self.google_secret_entry = tk.Entry(frame, width=56, fg=C_TEXT, bg="#000d12",
                                            insertbackground=C_TEXT, borderwidth=0, font=font_body(10), show="*")
        self.google_secret_entry.pack(pady=(0, 3), ipady=3)
        if config.get("google_oauth_client_secret"):
            self.google_secret_entry.insert(0, str(config.get("google_oauth_client_secret", "")))

        status = tk.Label(frame, text=calendar_auth_status(), fg=C_MID, bg="#00080d",
                          font=font_body(9), justify="left", wraplength=setup_w - 70)
        status.pack(pady=(6, 4))

        buttons = tk.Frame(frame, bg="#00080d")
        buttons.pack(side="bottom", pady=(8, 14))
        tk.Button(buttons, text="KAYDET",
                  command=lambda: self._save_integrations_settings(close=False),
                  bg=C_BG, fg=C_PRI, activebackground="#003344",
                  font=font_body_bold(11), borderwidth=0, padx=14, pady=8).pack(side="left", padx=5)
        tk.Button(buttons, text="BAGLAN",
                  command=lambda: self._run_calendar_oauth("start"),
                  bg="#08111a", fg=C_GOLD, activebackground="#10202b",
                  font=font_body_bold(11), borderwidth=0, padx=14, pady=8).pack(side="left", padx=5)
        tk.Button(buttons, text="TAMAMLA/TEST",
                  command=lambda: self._run_calendar_oauth("complete"),
                  bg="#08111a", fg=C_BLUE, activebackground="#10202b",
                  font=font_body_bold(11), borderwidth=0, padx=14, pady=8).pack(side="left", padx=5)
        tk.Button(buttons, text="BAGLANTIYI KES",
                  command=self._disconnect_calendar_oauth,
                  bg="#180b10", fg=C_RED, activebackground="#2a1018",
                  font=font_body_bold(11), borderwidth=0, padx=14, pady=8).pack(side="left", padx=5)
        tk.Button(buttons, text="KAPAT",
                  command=self._close_integrations_ui,
                  bg="#08111a", fg=C_DIM, activebackground="#10202b",
                  font=font_body_bold(11), borderwidth=0, padx=14, pady=8).pack(side="left", padx=5)

    def _integration_provider_key(self) -> str:
        label = self.calendar_provider_var.get().strip() if self.calendar_provider_var else "Outlook"
        return "google" if label == "Google" else "outlook"

    def _save_integrations_settings(self, close: bool = False):
        updates = {
            "calendar_provider": self._integration_provider_key(),
            "outlook_client_id": self.outlook_client_entry.get().strip() if self.outlook_client_entry else "",
            "outlook_tenant_id": self.outlook_tenant_entry.get().strip() if self.outlook_tenant_entry else "common",
            "google_oauth_client_id": self.google_client_entry.get().strip() if self.google_client_entry else "",
            "google_oauth_client_secret": self.google_secret_entry.get().strip() if self.google_secret_entry else "",
        }
        save_app_config(updates)
        self._refresh_settings_status()
        self.write_log("SYS: Integration ayarlari kaydedildi.")
        if close:
            self._close_integrations_ui()

    def _run_calendar_oauth(self, mode: str):
        provider = self._integration_provider_key()
        self._save_integrations_settings(close=False)

        def worker():
            result = connect_calendar_provider(provider, mode)
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))

        threading.Thread(target=worker, daemon=True).start()

    def _disconnect_calendar_oauth(self):
        provider = self._integration_provider_key()
        self._save_integrations_settings(close=False)

        def worker():
            result = disconnect_calendar_provider(provider)
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))

        threading.Thread(target=worker, daemon=True).start()

    # ── SFX toggle ───────────────────────────────────────────────────────────
    def _build_sfx_button(self, parent=None):
        parent = parent or self.root
        BW, BH = 98, 36
        self._sfx_canvas = tk.Canvas(parent, width=BW, height=BH,
                                     bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._sfx_canvas.bind("<Button-1>", lambda e: self._toggle_sfx())
        self._sfx_on = True
        self._draw_sfx_button()

    def _draw_sfx_button(self):
        c = self._sfx_canvas
        BW = int(c["width"])
        BH = int(c["height"])
        c.delete("all")
        col  = C_PRI if self._sfx_on else C_MID
        text = "♪ SFX ON"  if self._sfx_on else "♪ SFX OFF"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=1)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=1)
        c.create_text(BW//2, BH//2, text=text, fill=col, font=font_body_bold(9))

    def _toggle_sfx(self):
        self._sfx_on = not self._sfx_on
        self._draw_sfx_button()
        self._sync_sound_state()

    # ── Voice selector ───────────────────────────────────────────────────────
    def _build_voice_selector(self, parent=None):
        parent = parent or self.root
        self._voice_var = tk.StringVar(value=self._current_voice)
        self._voice_label = tk.Label(parent, text="VOICE", fg=C_MID, bg=parent.cget("bg"),
                                     font=font_body_bold(8))

        self._voice_menu = tk.OptionMenu(parent, self._voice_var, *VOICES,
                                         command=self._on_voice_select)
        self._voice_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=12)
        self._voice_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_voice_select(self, voice: str):
        self._current_voice = voice
        save_app_config({"voice": voice})
        if self.on_voice_change:
            threading.Thread(target=self.on_voice_change, args=(voice,), daemon=True).start()

    # ── Mute button ──────────────────────────────────────────────────────────
    def _build_mute_button(self):
        self._mute_canvas = tk.Canvas(self.root, width=126, height=36,
                                      bg=C_BG, highlightthickness=0, cursor="hand2")
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.muted:
            col, icon, lbl = C_MUTED, "🔇", " MUTED"
        else:
            col, icon, lbl = C_GREEN, "🎙", " LIVE"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                                (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=f"{icon}{lbl}",
                      fill=col, font=font_body_bold(11))

    def _build_pause_button(self):
        self._pause_canvas = tk.Canvas(self.root, width=126, height=36,
                                       bg=C_BG, highlightthickness=0, cursor="hand2")
        self._pause_canvas.bind("<Button-1>", lambda e: self._toggle_pause())
        self._draw_pause_button()

    def _draw_pause_button(self):
        c = self._pause_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.paused:
            col, text = C_GOLD, "▶ RESUME"
        else:
            col, text = C_BLUE, "⏸ PAUSE"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                               (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=text, fill=col, font=font_body_bold(11))

    def _build_ptt_button(self):
        self._ptt_canvas = tk.Canvas(self.root, width=164, height=36,
                                     bg=C_BG, highlightthickness=0, cursor="hand2")
        self._ptt_canvas.bind("<ButtonPress-1>", lambda e: self._start_ptt())
        self._ptt_canvas.bind("<ButtonRelease-1>", lambda e: self._stop_ptt())
        self._ptt_canvas.bind("<Leave>", lambda e: self._stop_ptt())
        self._draw_ptt_button()

    def _draw_ptt_button(self):
        c = self._ptt_canvas
        bw, bh = 164, 36
        c.delete("all")
        col = C_BLUE if self.ptt_active else C_PRI
        fill = "#071b24" if self.ptt_active else ""
        c.create_rectangle(1, 1, bw-1, bh-1, outline=col, width=1, fill=fill)
        label = "PTT ACTIVE" if self.ptt_active else "HOLD TO TALK"
        c.create_text(bw//2, bh//2, text=label, fill=col, font=font_body_bold(10))

    def _start_ptt(self):
        if self.ptt_active:
            return
        self.ptt_active = True
        self._draw_ptt_button()
        self.mark_user_activity(True)
        if self.on_ptt_start:
            threading.Thread(target=self.on_ptt_start, daemon=True).start()

    def _stop_ptt(self):
        if not self.ptt_active:
            return
        self.ptt_active = False
        self._draw_ptt_button()
        if self.on_ptt_stop:
            threading.Thread(target=self.on_ptt_stop, daemon=True).start()

    def _on_ptt_key_press(self, event=None):
        keysym = str(getattr(event, "keysym", "") or "")
        state = int(getattr(event, "state", 0) or 0)
        control_down = bool(state & 0x0004)
        if keysym.lower() != "space" or not control_down or self._ptt_key_down:
            return
        self._ptt_key_down = True
        self._start_ptt()

    def _on_ptt_key_release(self, event=None):
        keysym = str(getattr(event, "keysym", "") or "")
        if keysym.lower() != "space":
            return
        self._ptt_key_down = False
        self._stop_ptt()

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.write_log("SYS: Mikrofon kapatıldı.")
        else:
            self.write_log("SYS: Mikrofon açık.")
        self._sync_sound_state()

    # ── Orb tıklama = pause ──────────────────────────────────────────────────
    def _on_canvas_click(self, event):
        dx = event.x - self.FCX
        dy = event.y - self.FCY
        if dx*dx + dy*dy <= (self.FACE * 0.40)**2:
            self._toggle_pause()

    def _toggle_pause(self):
        self.paused = not self.paused
        self._draw_pause_button()
        if self.paused:
            self.set_state("PAUSED")
            self.write_log("SYS: JARVIS duraklatıldı.")
        else:
            self.set_state("THINKING")
            self.write_log("SYS: JARVIS devam ediyor...")
        self._sync_sound_state()
        if self.on_pause_toggle:
            threading.Thread(target=self.on_pause_toggle, args=(self.paused,), daemon=True).start()

    def _shutdown(self):
        self.sound.stop_all()
        self.write_log("SYS: JARVIS kapatılıyor...")
        self.root.after(380, os._exit, 0)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._enter_fullscreen()
        else:
            self.root.attributes("-fullscreen", False)
            self.root.geometry(self._window_geometry)
            self._resize_surface(*self._normal_size)

    def _resize_surface(self, width: int, height: int):
        self._set_layout_metrics(width, height)
        self.bg.configure(width=self.W, height=self.H)
        self.bg.place(x=0, y=0)
        self._place_layout_widgets()
        for p in self.particles:
            p["x"] %= self.W
            p["y"] %= self.H

    # ── Input bar ────────────────────────────────────────────────────────────
    def _build_input_bar(self, lw: int):
        x0 = self.CHAT_X
        btn_w = 76
        gap = 8
        inp_w = lw - btn_w - gap

        self._input_var   = tk.StringVar()
        self._input_entry = tk.Entry(
            self.root, textvariable=self._input_var,
            fg=C_TEXT, bg="#041212", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11),
            highlightthickness=1, highlightbackground=C_DIM,
            highlightcolor=C_PRI)
        self._input_entry.place(
            x=x0, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._input_entry.bind("<Return>",   self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root, text="SEND ▸",
            command=self._on_input_submit,
            fg=C_ORG, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_ORG,
            font=font_body_bold(10),
            borderwidth=0, cursor="hand2",
            highlightthickness=1, highlightbackground=C_ORG)
        self._send_btn.place(
            x=x0+inp_w+gap, y=self.CHAT_INPUT_Y,
            width=btn_w, height=INPUT_H)

    def _place_layout_widgets(self):
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y, width=self.CHAT_W, height=self.CHAT_H)
        gap = 12
        mute_w = 126
        pause_w = 126
        ptt_w = 164
        shutdown_w = int(self._shutdown_canvas["width"])
        total = mute_w + pause_w + ptt_w + shutdown_w + gap * 3
        start_x = self.FCX - total // 2
        row1_y = self.CTRL_Y + 20

        self._mute_canvas.place(x=start_x, y=row1_y)
        self._pause_canvas.place(x=start_x + mute_w + gap, y=row1_y)
        self._ptt_canvas.place(x=start_x + mute_w + pause_w + gap * 2, y=row1_y)
        self._shutdown_canvas.place(x=start_x + mute_w + pause_w + ptt_w + gap * 3, y=row1_y)

        geo = self._settings_geometry
        panel_x = geo["panel_x"]
        panel_y = geo["panel_y"]
        panel_w = geo["panel_w"]
        panel_h = geo["panel_h"]
        if self._settings_open:
            self._settings_panel.place(x=panel_x, y=panel_y, width=panel_w, height=panel_h)
            self._settings_panel.lift()
            self._settings_title.place(x=14, y=12)
            self._settings_tab_settings.place(x=14, y=40)
            self._settings_tab_debug.place(x=130, y=40)
            if self._settings_tab == "debug":
                self._settings_body.place_forget()
                self._debug_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._debug_text.place(x=0, y=0, width=panel_w - 24, height=panel_h - 88)
                self._debug_body.lift()
            else:
                self._debug_body.place_forget()
                self._settings_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._settings_body.lift()
        else:
            self._settings_panel.place_forget()
            self._settings_title.place_forget()
            self._settings_tab_settings.place_forget()
            self._settings_tab_debug.place_forget()
            self._settings_body.place_forget()
            self._debug_body.place_forget()

        inp_w = self.CHAT_W - 84
        self._input_entry.place(x=self.CHAT_X, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._send_btn.place(x=self.CHAT_X + inp_w + 8, y=self.CHAT_INPUT_Y, width=76, height=INPUT_H)

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        if text.lower() in ("sus", "dur", "stop", "sessiz", "kes"):
            self.write_log("SYS: ⏹ Ses kesildi.")
            if self.on_stop_command:
                threading.Thread(target=self.on_stop_command, daemon=True).start()
            return
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    # ── State & callbacks ────────────────────────────────────────────────────
    def set_state(self, state: str):
        previous = getattr(self, "_jarvis_state", "")
        self._jarvis_state = state
        self.speaking = (state == "SPEAKING")
        if state in {"THINKING", "RESEARCHING"}:
            self.sound.start_thinking()
        elif previous in {"THINKING", "RESEARCHING"}:
            self.sound.stop_thinking()
        if state == "ERROR" and previous != "ERROR":
            self.sound.play_error()

    def set_user_speaking(self, value: bool):
        self.mark_user_activity(value)

    def mark_user_activity(self, active: bool = True):
        self.user_speaking = active
        self._user_speaking_until = time.time() + (0.9 if active else 0.0)

    def set_text_mode(self, active: bool):
        self.text_mode = bool(active)

    def set_ptt_active(self, active: bool):
        self.ptt_active = bool(active)
        if hasattr(self, "_ptt_canvas"):
            self.root.after(0, self._draw_ptt_button)

    def set_wake_status(self, ready: bool, status: str = ""):
        self.wake_ready = bool(ready)
        self.wake_status = status or ("Wake ready" if ready else "Wake hazir degil")
        if hasattr(self, "_wake_status_label"):
            self.root.after(
                0,
                lambda: self._wake_status_label.configure(
                    text=self.wake_status[:90],
                    fg=C_GREEN if self.wake_ready else C_GOLD,
                ),
            )
        if self._wake_toggle_var is not None:
            try:
                self._wake_toggle_var.set(bool(load_app_config().get("wake_word_enabled", False)))
            except Exception:
                pass

    def get_effects_volume(self) -> float:
        return self.sound.get_volume()

    def effects_enabled(self) -> bool:
        return bool(self._effects_active)

    def play_success_sfx(self):
        self.root.after(0, self.sound.play_success)

    def play_error_sfx(self):
        self.root.after(0, self.sound.play_error)

    def focus_panel(self, section: str, duration_ms: int = 4200):
        section = (section or "").strip().lower()
        if not section:
            return

        def _apply():
            self._panel_focus = section
            self._panel_focus_until = time.time() + max(0.8, duration_ms / 1000.0)

        self.root.after(0, _apply)

    def _state_color(self, state: str | None = None) -> str:
        effective = state or self._jarvis_state
        if effective == "PAUSED":
            return C_MID
        return STATE_HEX_COLORS.get(effective, C_PRI)

    @staticmethod
    def _state_badge_text(state: str) -> str:
        return STATE_LABELS_TR.get(state, state or "ONLINE")

    @staticmethod
    def _state_display_text(state: str) -> str:
        return STATE_LABELS_TR.get(state, state or "DİNLİYOR")

    def _secondary_badges(self) -> list[tuple[str, str]]:
        badges: list[tuple[str, str]] = []
        if self.paused:
            badges.append(("PAUSED", C_MID))
        if self.muted:
            badges.append(("MUTED", C_MUTED))
        if self.text_mode:
            badges.append(("TEXT MODE", C_GOLD))
        if self.ptt_active:
            badges.append(("PTT ACTIVE", C_BLUE))
        if self.wake_ready:
            badges.append(("WAKE READY", C_GREEN))
        return badges

    # ── Log ──────────────────────────────────────────────────────────────────
    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        if tl.startswith("siz:") or tl.startswith("you:"):
            self.mark_user_activity(True)
            self.set_state("THINKING")
        elif tl.startswith("err:") or "error" in tl:
            self._error_hold_until = time.time() + 8.0
            self.set_state("ERROR")
            self.write_debug(text, level="ERROR")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if self._jarvis_state == "ERROR" and time.time() < self._error_hold_until:
                return
            if not self.speaking:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if   tl.startswith("siz:") or tl.startswith("you:"):   tag = "you"
        elif tl.startswith("jarvis:") or tl.startswith("ai:"): tag = "ai"
        elif tl.startswith("err:") or "error" in tl:           tag = "err"
        else:                                                    tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(7, self._type_char, text, i+1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(20, self._start_typing)

    # ── Stats ────────────────────────────────────────────────────────────────
    def _update_stats(self):
        try:
            self._stats['cpu']  = psutil.cpu_percent()
            self._stats['ram']  = psutil.virtual_memory().percent
            self._stats['disk'] = psutil.disk_usage('/').percent
            batt = psutil.sensors_battery()
            self._stats['battery'] = batt.percent if batt else 100.0
            now = time.time()
            net = psutil.net_io_counters()
            dt  = now - self._last_net_t
            if dt > 0:
                self._stats['net_up']   = max(0, (net.bytes_sent - self._last_net.bytes_sent) / dt / 1024)
                self._stats['net_down'] = max(0, (net.bytes_recv - self._last_net.bytes_recv) / dt / 1024)
            self._last_net   = net
            self._last_net_t = now
            self._cpu_hist.pop(0)
            self._cpu_hist.append(self._stats['cpu'])
        except Exception:
            pass

    # ── Animation loop ───────────────────────────────────────────────────────
    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if self.user_speaking and now > self._user_speaking_until:
            self.user_speaking = False

        if t % 90 == 0:
            threading.Thread(target=self._update_stats, daemon=True).start()
        if t % 1800 == 1:
            self._kick_brief_refresh()

        if self.speaking and t % 3 == 0:
            self._wave_jarvis = [random.randint(6, 30) for _ in range(18)]
        if self.user_speaking and t % 3 == 0:
            self._wave_user = [random.randint(5, 24) for _ in range(18)]

        if now - self.last_t > (0.12 if self.speaking else 0.50):
            if self.paused:
                self.target_scale = random.uniform(0.58, 0.64)
                self.target_halo  = random.uniform(5, 10)
            elif self.speaking:
                self.target_scale = random.uniform(0.98, 1.10)
                self.target_halo  = random.uniform(180, 250)
            elif self.user_speaking:
                self.target_scale = random.uniform(0.88, 0.98)
                self.target_halo  = random.uniform(120, 175)
            elif self._jarvis_state in ("THINKING", "INITIALISING"):
                self.target_scale = random.uniform(0.80, 0.88)
                self.target_halo  = random.uniform(95, 145)
            else:
                self.target_scale = random.uniform(0.72, 0.80)
                self.target_halo  = random.uniform(34, 58)
            self.last_t = now

        sp          = 0.34 if self.speaking else 0.18
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo   - self.halo_a) * sp

        if self.paused:
            spds = [0.0, 0.0, 0.0, 0.0]
        elif self.speaking:
            spds = [1.6, -1.1, 2.4, -0.7]
        else:
            spds = [0.55, -0.35, 0.90, -0.28]
        for i, spd in enumerate(spds):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        # Pulse rings
        pspd  = 4.2 if self.speaking else 1.8
        limit = self.FACE * 0.68
        self.pulse_r = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(self.pulse_r) < 3 and random.random() < (0.07 if self.speaking else 0.02):
            self.pulse_r.append(0.0)

        for p in self.particles:
            p['x'] = (p['x'] + p['vx']) % self.W
            p['y'] = (p['y'] + p['vy']) % self.H

        if t % 38 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        self.root.after(33, self._animate)

    # ── Yardımcı ─────────────────────────────────────────────────────────────
    @staticmethod
    def _ac(r, g, b, a):
        f = max(0, min(255, int(a))) / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _orb_rgb(self):
        state = "PAUSED" if self.paused else self._jarvis_state
        return ORB_COLORS.get(state, ORB_COLORS["LISTENING"])

    @staticmethod
    def _split_summary_lines(text: str, limit: int = 4) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        raw = raw.replace(" ve ", ", ")
        parts = [part.strip(" .") for part in raw.split(",") if part.strip()]
        return parts[:limit]

    def _parse_weather_card(self, text: str) -> dict:
        if not text or "alınamadı" in text.lower() or "alınamadi" in text.lower():
            return {
                "city": "Istanbul",
                "primary": "--",
                "details": ["Hava durumu alınamadı."],
            }

        prefix, _, body = text.partition(":")
        city = "Istanbul"
        if " için" in prefix:
            city = prefix.split(" için", 1)[0].strip().title()

        details = [part.strip(" .") for part in body.split(",") if part.strip()]
        primary = "--"
        if details:
            primary = details[0].replace(" derece", "°C")
        return {
            "city": city,
            "primary": primary,
            "details": details[1:4] or ["Anlık veri hazır."],
        }

    def _parse_health_card(self, text: str) -> list[str]:
        if not text or "alınamadı" in text.lower() or "alınamadi" in text.lower():
            return ["Sağlık verisi alınamadı."]
        lines = self._split_summary_lines(text, limit=4)
        return lines or ["Sağlık özeti hazır değil."]

    def _kick_brief_refresh(self):
        if self._brief_refresh_busy:
            return
        self._brief_refresh_busy = True
        threading.Thread(target=self._refresh_brief_cards, daemon=True).start()

    def _refresh_brief_cards(self):
        try:
            weather = get_weather_summary("Istanbul")
            self._weather_card = self._parse_weather_card(weather)
        except Exception:
            self._weather_card = {
                "city": "Istanbul",
                "primary": "--",
                "details": ["Hava durumu alınamadı."],
            }
        finally:
            self._brief_refresh_busy = False

    def _bar(self, c, x, y, w, h, pct, color):
        c.create_rectangle(x, y, x+w, y+h, fill="#061212", outline=C_DIM, width=1)
        fw = max(1, int(w * pct / 100))
        c.create_rectangle(x+1, y+1, x+fw, y+h-1, fill=color, outline="")

    def _sparkline(self, c, x, y, w, h, data):
        c.create_rectangle(x, y, x+w, y+h, fill="#050e0e", outline=C_DIM, width=1)
        n = len(data)
        if n < 2:
            return
        step = (w - 2) / (n - 1)
        h2   = h - 2
        coords = []
        for i, v in enumerate(data):
            coords.append(x + 1 + i * step)
            coords.append(y + h - 1 - int(h2 * v / 100))
        c.create_line(*coords, fill=C_PRI, width=1, smooth=True)

    def _bracket(self, c, x0, y0, pw, ph, col=None, bl=12):
        col = col or C_PRI
        for bx, by, sx, sy in [(x0, y0, 1, 1), (x0+pw, y0, -1, 1),
                                (x0, y0+ph, 1, -1), (x0+pw, y0+ph, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)

    def _draw_info_card(self, c, x0, y0, pw, ph, title, accent=C_PRI):
        focus = max(0.0, min(1.0, getattr(self, "_card_focus_boost", 0.0)))
        dimmed = bool(getattr(self, "_card_dimmed", False))
        glow = int(55 + 120 * focus)
        border = accent if focus > 0.08 else ("#35504d" if dimmed else self._ac(0, 120, 112, 190))
        fill = "#071111" if dimmed else "#030d0d"
        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill=fill, outline="")
        if focus > 0.08:
            for inset in range(3):
                c.create_rectangle(
                    x0-inset, y0-inset, x0+pw+inset, y0+ph+inset,
                    outline=self._ac(*ORB_COLORS["LISTENING"], max(12, glow - inset * 28)),
                    width=1,
                )
        self._bracket(c, x0, y0, pw, ph, col=border, bl=10)
        title_fill = "#6f7d7b" if dimmed else accent
        line_fill = "#173130" if dimmed else C_DIM
        c.create_text(x0+14, y0+14, text=title, fill=title_fill,
                      font=font_display(10), anchor="w")
        c.create_line(x0+12, y0+28, x0+pw-12, y0+28, fill=line_fill)

    def _focus_boost_for(self, section: str) -> float:
        if self._panel_focus != section:
            return 0.0
        remaining = self._panel_focus_until - time.time()
        if remaining <= 0:
            return 0.0
        pulse = 0.65 + 0.35 * math.sin(self.tick * 0.12)
        return min(1.0, remaining / 4.0) * pulse

    # ── Health overlay (sol panel) ────────────────────────────────────────────
    def show_health_hologram(self, query: str, data_str: str):
        def _show():
            self._health_visible = True
            self._health_query   = query.lower()
            self._health_display = data_str
            self._panel_focus = "health"
            self._panel_focus_until = time.time() + 5.0
            if self._health_hide_job:
                self.root.after_cancel(self._health_hide_job)
            self._health_hide_job = self.root.after(14000, self._hide_health_hologram)
        self.root.after(0, _show)

    def _hide_health_hologram(self):
        self._health_visible  = False
        self._health_hide_job = None

    def _draw_health_overlay(self, c):
        x0, y0 = 4, HDR_H + 4
        pw = self.LEFT_W - 8
        ph = self.H - HDR_H - FOOTER_H - 90
        pulse = 0.5 + 0.5 * math.sin(self.tick * 0.08)

        c.create_rectangle(x0, y0, x0+pw, y0+ph,
                           fill="#011510", outline=C_PRI, width=1)
        self._bracket(c, x0, y0, pw, ph, col=C_ORG, bl=10)

        title_col = self._ac(0, 212, 192, int(200 + 55*pulse))
        c.create_text(x0+pw//2, y0+18, text="◈ HEALTH ◈",
                      fill=title_col, font=font_display(11))
        c.create_line(x0+8, y0+30, x0+pw-8, y0+30, fill=C_MID)

        lines = [l for l in self._health_display.split('\n') if l.strip()]
        ly = y0 + 44
        for line in lines:
            if ly > y0 + ph - 14:
                break
            if line.startswith("──"):
                c.create_line(x0+8, ly, x0+pw-8, ly, fill=C_DIM)
                ly += 10
            elif ":" in line:
                parts = line.split(":", 1)
                lbl   = parts[0].strip()
                val   = parts[1].strip() if len(parts) > 1 else ""
                c.create_text(x0+10, ly, text=lbl+":", fill=C_MID,
                              font=font_body(10), anchor="w")
                c.create_text(x0+pw-10, ly, text=val, fill=C_ORG,
                              font=font_body_bold(10), anchor="e")
                ly += 20
            else:
                c.create_text(x0+10, ly, text=line, fill=C_TEXT,
                              font=font_body(9), anchor="w")
                ly += 17

    # ── Sol panel ─────────────────────────────────────────────────────────────
    def _draw_left_panel(self, c):
        if self._health_visible:
            self._draw_health_overlay(c)
            return

        x0 = 10
        y0 = HDR_H + 10
        pw = self.LEFT_W - 18
        gap = 14
        total_h = self.H - HDR_H - FOOTER_H - 20
        card_area_h = total_h - gap * 3
        pad = 14
        bw = pw - 2 * pad

        cards = [
            ("time", 0.22, "TIME", C_GOLD),
            ("weather", 0.20, "WEATHER · ISTANBUL", C_BLUE),
            ("system", 0.28, "SYSTEM STATUS", C_PRI),
            ("health", 0.30, "HEALTH SUMMARY", C_GREEN),
        ]
        any_focus_active = bool(self._panel_focus) and (self._panel_focus_until > time.time())
        weights = []
        for section, weight, _, _ in cards:
            weights.append(weight + (0.12 if self._focus_boost_for(section) > 0.08 else 0.0))
        total_weight = sum(weights)
        heights = [int(card_area_h * (weight / total_weight)) for weight in weights]
        heights[-1] += card_area_h - sum(heights)

        current_y = y0
        for (section, _, title, accent), ph in zip(cards, heights):
            focus_boost = self._focus_boost_for(section)
            dimmed = any_focus_active and focus_boost <= 0.08
            shift_x = int(14 * focus_boost)
            extra_w = int(22 * focus_boost)
            section_x = x0 + shift_x
            section_pw = pw + extra_w
            section_pad = pad + int(2 * focus_boost)
            section_bw = section_pw - 2 * section_pad
            muted_label = "#647270" if dimmed else C_MID
            muted_text = "#7e8a88" if dimmed else C_TEXT
            muted_primary = "#8ea19d" if dimmed else C_PRI
            muted_blue = "#829594" if dimmed else C_BLUE
            muted_green = "#85a393" if dimmed else C_GREEN
            muted_gold = "#a1997e" if dimmed else C_GOLD
            muted_warn = "#8d7f77" if dimmed else C_ORG2
            muted_red = "#8a7779" if dimmed else C_RED
            self._card_focus_boost = focus_boost
            self._card_dimmed = dimmed
            self._draw_info_card(c, section_x, current_y, section_pw, ph, title, accent=accent if not dimmed else "#72807f")

            if section == "time":
                c.create_text(section_x+section_pad, current_y+64, text=time.strftime("%H:%M"),
                              fill=muted_primary, font=font_display(36 if focus_boost > 0.08 else 34), anchor="w")
                c.create_text(section_x+section_pad, current_y+92, text=time.strftime(":%S"),
                              fill=muted_label, font=font_body_bold(13), anchor="w")
                c.create_text(section_x+section_pad, current_y+118, text=time.strftime("%d %B %Y").upper(),
                              fill=muted_gold, font=font_body_bold(11), anchor="w")
                c.create_text(section_x+section_pad, current_y+138, text=time.strftime("%A").upper(),
                              fill=muted_text, font=font_body(10), anchor="w")

            elif section == "weather":
                c.create_text(section_x+section_pad, current_y+58, text=self._weather_card["primary"],
                              fill=muted_primary, font=font_display(30 if focus_boost > 0.08 else 28), anchor="w")
                c.create_text(section_x+section_pad, current_y+84, text=self._weather_card["city"].upper(),
                              fill=muted_label, font=font_body_bold(10), anchor="w")
                wy = current_y + 108
                for line in self._weather_card["details"][:3]:
                    c.create_text(section_x+section_pad, wy, text=f"• {line}", fill=muted_text,
                                  font=font_body(10), anchor="w")
                    wy += 17

            elif section == "system":
                cy = current_y + 44
                uptime = int(time.time() - self._started_at)
                up_min, up_sec = divmod(uptime, 60)
                up_hr, up_min = divmod(up_min, 60)
                c.create_text(section_x+section_pad, cy, text=f"UPTIME  {up_hr:02d}:{up_min:02d}:{up_sec:02d}",
                              fill=muted_label, font=font_body_bold(9), anchor="w")
                cy += 22
                for label, key, unit in [("CPU", "cpu", "%"), ("RAM", "ram", "%"), ("DISK", "disk", "%"), ("BATTERY", "battery", "%")]:
                    val = self._stats[key]
                    col = C_RED if val > 80 and key != "battery" else C_ORG if val > 55 and key != "battery" else (C_RED if key == "battery" and val < 20 else C_GREEN if key == "battery" else C_PRI)
                    if dimmed:
                        col = muted_red if col == C_RED else muted_warn if col == C_ORG else muted_green if col == C_GREEN else muted_primary
                    c.create_text(section_x+section_pad, cy, text=label, fill=muted_label, font=font_body(10), anchor="w")
                    c.create_text(section_x+section_pw-section_pad, cy, text=f"{val:.0f}{unit}", fill=col, font=font_body_bold(10), anchor="e")
                    cy += 14
                    self._bar(c, section_x+section_pad, cy, section_bw, 7, val, col)
                    cy += 16
                up = self._stats["net_up"]
                down = self._stats["net_down"]
                up_s = f"{up:.1f} KB/s" if up < 1000 else f"{up/1024:.1f} MB/s"
                down_s = f"{down:.1f} KB/s" if down < 1000 else f"{down/1024:.1f} MB/s"
                c.create_line(section_x+section_pad, cy-4, section_x+section_pw-section_pad, cy-4, fill="#173130" if dimmed else C_DIM)
                c.create_text(section_x+section_pad, cy+10, text=f"▲ {up_s}", fill=muted_warn, font=font_body(10), anchor="w")
                c.create_text(section_x+section_pw-section_pad, cy+10, text=f"▼ {down_s}", fill=muted_green, font=font_body(10), anchor="e")

            elif section == "health":
                hy = current_y + 48
                for line in self._health_card_lines[:5]:
                    c.create_text(section_x+section_pad, hy, text=f"• {line}", fill=muted_text,
                                  font=font_body(10), anchor="w")
                    hy += 21

            current_y += ph + gap

        self._card_focus_boost = 0.0
        self._card_dimmed = False

    # ── Sağ panel ─────────────────────────────────────────────────────────────
    def _draw_right_panel(self, c):
        x0  = self.CHAT_PANEL_X
        y0  = self.CHAT_PANEL_Y
        pw  = self.CHAT_PANEL_W
        ph  = self.CHAT_PANEL_H
        pad = 10

        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill="#030d0d", outline="")
        self._bracket(c, x0, y0, pw, ph, col=C_MID)

        if self.paused:
            sc, st = C_MID, "PAUSED"
        else:
            sc, st = self._state_color(self._jarvis_state), self._jarvis_state

        c.create_text(x0+14, y0+16, text="CONVERSATION", fill=C_PRI,
                      font=font_display(11), anchor="w")
        c.create_text(x0+pw-pad, y0+16, text=self._state_display_text(st), fill=sc,
                      font=font_body_bold(10), anchor="e")
        c.create_line(x0+pad, y0+28, x0+pw-pad, y0+28, fill=C_DIM)

    # ── ORB (ana çizim) ───────────────────────────────────────────────────────
    def _draw_orb(self, c):
        state = "PAUSED" if self.paused else self._jarvis_state
        t    = self.tick
        speak_pulse = 1.0
        if self.speaking:
            speak_pulse = 1.0 + 0.12 * math.sin(t * 0.23) + 0.05 * math.sin(t * 0.11 + 1.2)
        elif self.user_speaking:
            speak_pulse = 1.0 + 0.06 * math.sin(t * 0.18 + 0.7)
        elif state in ("THINKING", "RESEARCHING", "WAITING_APPROVAL", "INITIALISING"):
            speak_pulse = 1.0 + 0.03 * math.sin(t * 0.10)
        else:
            speak_pulse = 1.0 + 0.01 * math.sin(t * 0.07)

        move_x = 0
        move_y = 0
        if self.user_speaking:
            move_x = int(6 * math.sin(t * 0.06))
            move_y = int(4 * math.cos(t * 0.09 + 0.5))
        elif state in ("THINKING", "INITIALISING"):
            move_x = int(3 * math.sin(t * 0.045))
            move_y = int(2 * math.cos(t * 0.05 + 0.4))

        FCX  = self.FCX + move_x
        FCY  = self.FCY + move_y
        FW   = int(self.FACE * self.scale * speak_pulse)
        R, G, B = self._orb_rgb()
        ha   = self.halo_a
        field_r = int(FW * 0.49)
        inner_r = int(FW * 0.34)
        activity = (
            0.10 if self.paused else
            1.00 if self.speaking else
            0.78 if self.user_speaking else
            0.62 if state in ("THINKING", "RESEARCHING", "WAITING_APPROVAL", "INITIALISING") else
            0.26
        )
        if state in ("THINKING", "RESEARCHING", "WAITING_APPROVAL", "INITIALISING"):
            accent_rgb = (255, 210, 72)
        elif self.speaking:
            accent_rgb = (170, 220, 255)
        elif self.user_speaking:
            accent_rgb = (118, 200, 255)
        else:
            accent_rgb = (120, 255, 185)

        # Pulse rings
        for pr in self.pulse_r:
            alpha = max(0, int(160 * (1.0 - pr / (FW * 0.70))))
            rr = int(pr + field_r * 0.96)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, alpha),
                width=1,
            )

        # Large outer glow
        if not self.paused:
            for i in range(10, 0, -1):
                frac = i / 10
                rr = int(field_r * (1.02 + 0.045 * frac))
                alpha = int(ha * 0.10 * frac)
                if self.speaking:
                    ox = 0
                    oy = 0
                else:
                    ox = int(3 * math.sin(t * 0.010 + i))
                    oy = int(3 * math.cos(t * 0.009 + i * 1.3))
                c.create_oval(
                    FCX-rr+ox, FCY-rr+oy, FCX+rr+ox, FCY+rr+oy,
                    outline=self._ac(R, G, B, alpha),
                    width=3,
                )

        # Structural circles
        for frac, width, alpha_mult in (
            (1.00, 2, 0.34),
            (0.90, 2, 0.24),
            (0.76, 1, 0.18),
            (0.62, 1, 0.12),
        ):
            rr = int(field_r * frac)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, int(ha * alpha_mult * (0.4 if self.paused else 1.0))),
                width=width,
            )

        speak_shell_push = 1.16 if self.speaking else 1.07 if self.user_speaking else 1.0
        # Orb shell particles
        shell_r = field_r * 0.93 * speak_shell_push
        for idx, sp in enumerate(self.orb_shell_particles):
            angle = sp['angle'] + t * sp['speed'] * (2.8 if self.speaking else 1.6 if self.user_speaking else 1.1)
            wobble = 1.0 + (0.07 if self.speaking else 0.035) * math.sin(t * 0.08 + sp['phase'])
            x = FCX + math.cos(angle) * shell_r * wobble
            y = FCY + math.sin(angle) * shell_r * wobble
            alpha = int((70 + 120 * sp['glow']) * (0.26 if self.paused else 0.52 + activity * 0.45))
            if idx % 9 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, alpha + 30))
            else:
                col = self._ac(R, G, B, alpha)
            pr = sp['size'] * (1.0 + 0.24 * math.sin(t * 0.05 + sp['phase']))
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")

        # Rotating segmented arcs
        arc_r1 = int(field_r * 0.96)
        arc_r2 = int(field_r * 0.78)
        for start, extent, width, accent in (
            (self.rings_spin[0], 52 if self.speaking else 34, 3, False),
            ((self.rings_spin[0] + 148) % 360, 26, 2, True),
            ((self.rings_spin[2] + 28) % 360, 64 if self.user_speaking else 40, 3, False),
            ((self.rings_spin[2] + 212) % 360, 18, 2, True),
        ):
            rr = arc_r1 if width == 3 else arc_r2
            if accent and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], int(120 + 80 * activity))
            else:
                col = self._ac(R, G, B, int(ha * (1.2 if width == 3 else 0.7)))
            c.create_arc(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                start=start, extent=extent,
                outline=col, width=width, style="arc",
            )

        # Particle orb field
        field_limit = inner_r * (
            0.82 if self.paused else
            1.36 if self.speaking else
            1.16 if self.user_speaking else
            1.0
        )
        for idx, p in enumerate(self.orb_particles):
            speed_mult = (
                0.10 if self.paused else
                3.10 if self.speaking else
                2.00 if self.user_speaking else
                1.10
            )
            angle = p['angle'] + t * p['speed'] * speed_mult
            wobble = 1.0 + (0.30 if self.speaking else 0.18) * math.sin(t * p['wobble'] + p['phase'])
            orbit = field_limit * p['orbit'] * wobble
            depth = 0.5 + 0.5 * math.sin(angle * 2.0 + t * 0.013 + p['phase'])
            y_squash = 0.62 + depth * 0.38
            drift = (8.0 if self.speaking else 5.0 if self.user_speaking else 4.0) * p['depth']
            x = FCX + math.cos(angle) * orbit + math.sin(t * 0.011 + p['phase']) * drift
            y = FCY + math.sin(angle) * orbit * y_squash + math.cos(t * 0.010 + p['phase']) * drift
            base_alpha = int((18 + 155 * p['depth']) * (0.24 + activity * 0.86) * (0.45 + depth * 0.75))
            if self.paused:
                base_alpha = int(base_alpha * 0.40)
            if idx % 11 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, base_alpha + 25))
            elif self.user_speaking and idx % 7 == 0:
                col = self._ac(120, 205, 255, min(255, base_alpha + 20))
            else:
                col = self._ac(R, G, B, base_alpha)
            pr = p['size'] * (0.70 if self.paused else 0.90 + depth * 0.65 + 0.30 * activity * p['depth'])
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")
            if idx % 18 == 0 and not self.paused:
                c.create_line(
                    FCX + (x-FCX) * 0.18,
                    FCY + (y-FCY) * 0.18,
                    x, y,
                    fill=self._ac(R, G, B, int(18 + 35 * p['depth'] * activity)),
                    width=1,
                )

        # Center void keeps the orb airy instead of lens-like.
        void_r = int(inner_r * (0.18 if self.paused else 0.12))
        if void_r > 0:
            c.create_oval(
                FCX-void_r, FCY-void_r, FCX+void_r, FCY+void_r,
                fill=C_BG,
                outline="",
            )

    # ── Ana çizim ─────────────────────────────────────────────────────────────
    def _draw(self):
        c  = self.bg
        W  = self.W
        H  = self.H
        t  = self.tick
        c.delete("all")

        # ── Arka plan ────────────────────────────────────────────────────────
        # Nokta ızgarası — çok ince
        step = 48
        for x in range(0, W, step):
            for y in range(0, H, step):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        # Tarama çizgisi (yavaş, çok soluk)
        scan_y = (t * 0.7) % (H + 60) - 30
        for i in range(2):
            ly = (scan_y + i * 20) % H
            c.create_line(0, ly, W, ly+35, fill="#081818", width=1)

        # Partiküller
        R, G, B = self._orb_rgb()
        for p in self.particles:
            if self.speaking:
                col = self._ac(255, 110, 0, p['a'])
            else:
                col = self._ac(R, G, B, p['a'])
            r = p['r']
            c.create_oval(p['x']-r, p['y']-r, p['x']+r, p['y']+r,
                          fill=col, outline="")

        # ── Bölücü çizgiler (ince, soluk) ────────────────────────────────────
        c.create_line(self.LEFT_W, HDR_H, self.LEFT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)
        c.create_line(W-self.RIGHT_W, HDR_H, W-self.RIGHT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)

        # ── Yan paneller ──────────────────────────────────────────────────────
        self._draw_left_panel(c)
        self._draw_right_panel(c)

        # ── Orb ──────────────────────────────────────────────────────────────
        self._draw_orb(c)

        state_label = "PAUSED" if self.paused else self._jarvis_state
        state_col = self._state_color(state_label)
        c.create_text(self.FCX, self.CTRL_Y - 34, text=SYSTEM_NAME,
                      fill=C_TEXT, font=font_display(18))
        c.create_text(self.FCX, self.CTRL_Y - 12, text=f"● {self._state_display_text(state_label)}",
                      fill=state_col, font=font_body_bold(11))

        # ── HEADER ───────────────────────────────────────────────────────────
        c.create_rectangle(0, 0, W, HDR_H, fill="#010a0a", outline="")
        # Alt çizgi — teal parlak
        c.create_line(0, HDR_H, W, HDR_H, fill=C_MID, width=1)
        for i in range(3):
            a = 60 - i * 18
            c.create_line(0, HDR_H-1-i, W, HDR_H-1-i,
                          fill=self._ac(0, 180, 165, a), width=1)

        # Büyük başlık
        c.create_text(W//2, 24, text=SYSTEM_NAME,
                      fill=C_PRI, font=font_display(26))
        c.create_text(W//2, 52, text="Just A Rather Very Intelligent System",
                      fill=C_MID, font=font_body(11))

        # Sol: model badge
        c.create_text(22, 36, text=MODEL_BADGE,
                      fill=C_DIM, font=font_body(10), anchor="w")

        # Sağ: durum indikatörü
        indicator_state = "PAUSED" if self.paused else self._jarvis_state
        ind_col = self._state_color(indicator_state)
        indicator_text = self._state_badge_text(indicator_state)
        sym = "●" if self.status_blink else "○"
        c.create_text(W-22, 36, text=f"{sym}  {indicator_text}",
                      fill=ind_col, font=font_body_bold(11), anchor="e")
        bx = W - 22
        by = 56
        for label, color in reversed(self._secondary_badges()[:5]):
            tw = max(62, len(label) * 8 + 18)
            bx -= tw
            c.create_rectangle(bx, by-9, bx+tw-8, by+9, outline=color, fill="", width=1)
            c.create_text(bx + (tw-8)//2, by, text=label, fill=color, font=font_body_bold(8))
            bx -= 6

        # ── FOOTER ───────────────────────────────────────────────────────────
        c.create_rectangle(0, H-FOOTER_H, W, H, fill="#010a0a", outline="")
        c.create_line(0, H-FOOTER_H, W, H-FOOTER_H, fill=C_DIM, width=1)
        c.create_text(W//2, H-13, fill=C_DIM, font=font_body(9),
                      text="JARVIS · Desktop Edition · Realtime Voice Core")
        c.create_text(W-18, H-13, fill=C_DIM, font=font_body(9),
                      text="[CTRL+SPACE] PTT  [F4] MUTE  [F5] PAUSE  [ESC] EXIT", anchor="e")

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self, edit_mode: bool = False):
        self._close_setup_ui()

        self.setup_frame = tk.Frame(self.root, bg="#00080d",
                                    highlightbackground=C_PRI,
                                    highlightthickness=1)
        setup_w = min(820, max(620, int(self.W * 0.46)))
        setup_h = min(max(560, self.H - 90), max(620, int(self.H * 0.66)))
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        self.setup_frame.pack_propagate(False)

        title = "◈ API AYARLARI" if edit_mode else "◈ İLK KURULUM GEREKLİ"
        subtitle = (
            "Gemini, Cloud/OpenAI-compatible, Local AI ve YouTube ayarlarinizi guncelleyin."
            if edit_mode else
            "Cloud, Local veya Hybrid ajan modunu secin. YouTube/Tavily alanlari opsiyoneldir."
        )
        config = load_app_config()

        tk.Label(self.setup_frame, text=title,
                 fg=C_PRI, bg="#00080d", font=font_display(18)).pack(pady=(18, 4))
        tk.Label(self.setup_frame, text=subtitle,
                 fg=C_MID, bg="#00080d", font=font_body(11)).pack(pady=(0, 8))
        tk.Label(self.setup_frame, text="GEMINI API KEY",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))

        self.api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11), show="*")
        self.api_entry.pack(pady=(0, 4), ipady=3)

        current_key = str(config.get("gemini_api_key", "") or "")
        if current_key:
            self.api_entry.insert(0, current_key)

        tk.Label(self.setup_frame, text="MODEL MODE",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        provider_map = {
            "hybrid": "Hybrid",
            "cloud": "Cloud",
            "local": "Local",
        }
        current_provider = str(config.get("agent_mode", "hybrid") or "hybrid")
        self.agent_provider_var = tk.StringVar(value=provider_map.get(current_provider, "Hybrid"))
        self.agent_provider_var.trace_add("write", lambda *_: self._refresh_setup_provider_state())
        provider_menu = tk.OptionMenu(
            self.setup_frame,
            self.agent_provider_var,
            "Hybrid",
            "Cloud",
            "Local",
        )
        provider_menu.config(
            width=54, fg=C_TEXT, bg="#000d12", activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10), borderwidth=0,
            highlightthickness=1, highlightbackground=C_MID,
        )
        provider_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI,
        )
        provider_menu.pack(pady=(0, 4), ipady=2)

        tk.Label(self.setup_frame, text="CLOUD / OPENAI-COMPATIBLE URL(S)",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_url_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10))
        self.ninerouter_url_entry.pack(pady=(0, 3), ipady=3)
        current_url = str(config.get("cloud_base_url", "") or config.get("ninerouter_base_url", "") or "")
        if current_url:
            self.ninerouter_url_entry.insert(0, current_url)

        tk.Label(self.setup_frame, text="CLOUD MODEL",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_model_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10))
        self.ninerouter_model_entry.pack(pady=(0, 3), ipady=3)
        current_model = str(config.get("cloud_model", "") or config.get("ninerouter_model", "") or "")
        if current_model:
            self.ninerouter_model_entry.insert(0, current_model)

        tk.Label(self.setup_frame, text="CLOUD API KEY",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_key_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10), show="*")
        self.ninerouter_key_entry.pack(pady=(0, 3), ipady=3)
        current_ninerouter_key = str(config.get("cloud_api_key", "") or config.get("ninerouter_api_key", "") or "")
        if current_ninerouter_key:
            self.ninerouter_key_entry.insert(0, current_ninerouter_key)

        tk.Label(self.setup_frame, text="LOCAL PROVIDER",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        local_provider_map = {
            "foundry_local": "Microsoft Foundry Local",
            "openai_compatible": "Manual OpenAI-Compatible",
        }
        current_local_provider = str(config.get("local_provider", "foundry_local") or "foundry_local")
        self.local_provider_var = tk.StringVar(
            value=local_provider_map.get(current_local_provider, "Microsoft Foundry Local")
        )
        local_provider_menu = tk.OptionMenu(
            self.setup_frame,
            self.local_provider_var,
            "Microsoft Foundry Local",
            "Manual OpenAI-Compatible",
        )
        local_provider_menu.config(
            width=54, fg=C_TEXT, bg="#000d12", activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10), borderwidth=0,
            highlightthickness=1, highlightbackground=C_MID,
        )
        local_provider_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI,
        )
        local_provider_menu.pack(pady=(0, 3), ipady=2)

        local_row = tk.Frame(self.setup_frame, bg="#00080d")
        local_row.pack(pady=(0, 3))
        self.local_auto_start_var = tk.BooleanVar(value=bool(config.get("local_auto_start", True)))
        tk.Checkbutton(
            local_row,
            text="Foundry auto-start",
            variable=self.local_auto_start_var,
            fg=C_TEXT,
            bg="#00080d",
            activeforeground=C_PRI,
            activebackground="#00080d",
            selectcolor="#000d12",
            font=font_body(9),
            borderwidth=0,
        ).pack(side="left", padx=(0, 12))

        tk.Label(local_row, text="ALIAS",
                 fg=C_DIM, bg="#00080d", font=font_body(9)).pack(side="left", padx=(0, 6))
        self.local_foundry_alias_entry = tk.Entry(
            local_row, width=18,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(9))
        self.local_foundry_alias_entry.pack(side="left", ipady=2)
        self.local_foundry_alias_entry.insert(
            0,
            str(config.get("local_foundry_model_alias", "qwen2.5-0.5b") or "qwen2.5-0.5b"),
        )

        tk.Label(self.setup_frame, text="LOCAL URL / MODEL / KEY (manuel endpoint icin)",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(2, 2))
        local_endpoint_row = tk.Frame(self.setup_frame, bg="#00080d")
        local_endpoint_row.pack(pady=(0, 3))
        self.local_url_entry = tk.Entry(
            local_endpoint_row, width=29,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(9))
        self.local_url_entry.pack(side="left", padx=(0, 6), ipady=2)
        current_local_url = str(config.get("local_base_url", "") or "")
        if current_local_url:
            self.local_url_entry.insert(0, current_local_url)
        self.local_model_entry = tk.Entry(
            local_endpoint_row, width=18,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(9))
        self.local_model_entry.pack(side="left", padx=(0, 6), ipady=2)
        current_local_model = str(config.get("local_model", "") or "")
        if current_local_model:
            self.local_model_entry.insert(0, current_local_model)
        self.local_key_entry = tk.Entry(
            local_endpoint_row, width=18,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(9), show="*")
        self.local_key_entry.pack(side="left", ipady=2)
        current_local_key = str(config.get("local_api_key", "") or "")
        if current_local_key:
            self.local_key_entry.insert(0, current_local_key)
        self._refresh_setup_provider_state()

        tk.Label(self.setup_frame, text="TAVILY API KEY",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))
        self.tavily_api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10), show="*")
        self.tavily_api_entry.pack(pady=(0, 3), ipady=3)
        current_tavily_key = str(config.get("tavily_api_key", "") or "")
        if current_tavily_key:
            self.tavily_api_entry.insert(0, current_tavily_key)

        tk.Label(self.setup_frame, text="YOUTUBE API KEY",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))

        self.youtube_api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11), show="*")
        self.youtube_api_entry.pack(pady=(0, 4), ipady=3)
        current_youtube_key = str(config.get("youtube_api_key", "") or "")
        if current_youtube_key:
            self.youtube_api_entry.insert(0, current_youtube_key)

        tk.Label(self.setup_frame, text="YOUTUBE HANDLE / CHANNEL",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(4, 2))

        self.youtube_handle_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11))
        self.youtube_handle_entry.pack(pady=(0, 4), ipady=3)
        current_handle = str(config.get("youtube_channel_handle", "") or "")
        if current_handle:
            self.youtube_handle_entry.insert(0, current_handle)

        buttons = tk.Frame(self.setup_frame, bg="#00080d")
        buttons.pack(side="bottom", pady=(8, 14))

        tk.Button(buttons, text="▸ KAYDET",
                  command=self._save_api_key, bg=C_BG, fg=C_PRI,
                  activebackground="#003344", font=font_body_bold(13),
                  borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

        tk.Button(buttons, text="LOCAL TEST",
                  command=self._test_local_ai_from_setup, bg="#06131a", fg=C_GOLD,
                  activebackground="#10202b", font=font_body_bold(13),
                  borderwidth=0, padx=18, pady=10).pack(side="left", padx=8)

        if edit_mode:
            tk.Button(buttons, text="KAPAT",
                      command=self._close_setup_ui, bg="#08111a", fg=C_DIM,
                      activebackground="#10202b", font=font_body_bold(13),
                      borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

    def _refresh_setup_provider_state(self):
        if not self.agent_provider_var:
            return
        label = self.agent_provider_var.get().strip()
        cloud_state = "normal" if label in {"Hybrid", "Cloud"} else "disabled"
        local_state = "normal" if label in {"Hybrid", "Local"} else "disabled"
        for entry in (self.ninerouter_url_entry, self.ninerouter_model_entry, self.ninerouter_key_entry):
            if entry:
                entry.configure(state=cloud_state)
        for entry in (self.local_url_entry, self.local_model_entry, self.local_key_entry, self.local_foundry_alias_entry):
            if entry:
                entry.configure(state=local_state)
        if self.api_entry:
            self.api_entry.configure(state="normal")

    def _setup_mode_key(self) -> str:
        label = self.agent_provider_var.get().strip() if self.agent_provider_var else "Hybrid"
        return {"Hybrid": "hybrid", "Cloud": "cloud", "Local": "local"}.get(label, "hybrid")

    def _setup_local_provider_key(self) -> str:
        label = self.local_provider_var.get().strip() if self.local_provider_var else "Microsoft Foundry Local"
        if label == "Manual OpenAI-Compatible":
            return "openai_compatible"
        return "foundry_local"

    def _collect_setup_updates(self) -> dict:
        key = self.api_entry.get().strip() if self.api_entry else ""
        cloud_url = self.ninerouter_url_entry.get().strip() if self.ninerouter_url_entry else ""
        cloud_model = self.ninerouter_model_entry.get().strip() if self.ninerouter_model_entry else ""
        cloud_key = self.ninerouter_key_entry.get().strip() if self.ninerouter_key_entry else ""
        youtube_key = self.youtube_api_entry.get().strip() if self.youtube_api_entry else ""
        youtube_handle = self.youtube_handle_entry.get().strip() if self.youtube_handle_entry else ""
        tavily_key = self.tavily_api_entry.get().strip() if self.tavily_api_entry else ""
        return {
            "gemini_api_key": key,
            "youtube_api_key": youtube_key,
            "youtube_channel_handle": youtube_handle,
            "tavily_api_key": tavily_key,
            "voice": self._current_voice,
            "agent_mode": self._setup_mode_key(),
            "agent_provider": "ninerouter" if self._setup_mode_key() == "cloud" else "hybrid",
            "cloud_base_url": cloud_url,
            "cloud_model": cloud_model,
            "cloud_api_key": cloud_key,
            "ninerouter_base_url": cloud_url,
            "ninerouter_model": cloud_model,
            "ninerouter_api_key": cloud_key,
            "local_provider": self._setup_local_provider_key(),
            "local_base_url": self.local_url_entry.get().strip() if self.local_url_entry else "",
            "local_model": self.local_model_entry.get().strip() if self.local_model_entry else "",
            "local_api_key": self.local_key_entry.get().strip() if self.local_key_entry else "",
            "local_foundry_model_alias": self.local_foundry_alias_entry.get().strip() if self.local_foundry_alias_entry else "qwen2.5-0.5b",
            "local_auto_start": bool(self.local_auto_start_var.get()) if self.local_auto_start_var else True,
        }

    def _save_api_key(self):
        was_ready = self._api_key_ready
        updates = self._collect_setup_updates()
        key = str(updates.get("gemini_api_key", "") or "")
        cloud_ready = all(str(updates.get(k, "") or "").strip() for k in ("cloud_base_url", "cloud_model", "cloud_api_key"))
        local_provider = str(updates.get("local_provider", "") or "")
        local_ready = (
            local_provider == "foundry_local"
            and bool(str(updates.get("local_foundry_model_alias", "") or "").strip())
            and bool(updates.get("local_auto_start", True))
        ) or (
            bool(str(updates.get("local_base_url", "") or "").strip())
            and bool(str(updates.get("local_model", "") or "").strip())
        )
        if not key and not cloud_ready and not local_ready:
            self.write_log("ERR: Kaydetmek icin Gemini, Cloud endpoint veya Local AI alanlarini doldur.")
            return
        save_app_config(updates)
        self._close_setup_ui()
        self._api_key_ready = True
        self._refresh_settings_status()
        if was_ready:
            self.write_log("SYS: API ayarlari guncellendi.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: JARVIS hazır. Dinliyorum...")

    def _test_local_ai_from_setup(self):
        updates = self._collect_setup_updates()
        save_app_config(updates)
        self.write_log("SYS: Local AI testi baslatildi...")

        def worker():
            result = test_local_ai("Merhaba, JARVIS local testine tek cumle cevap ver.")
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))
            self.root.after(0, self._refresh_settings_status)

        threading.Thread(target=worker, daemon=True).start()
