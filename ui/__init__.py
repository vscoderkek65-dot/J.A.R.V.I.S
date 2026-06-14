"""JARVIS desktop UI v3 - Package structure"""

import os, time, math, random, signal, threading
import platform
import tkinter as tk
from collections import deque
from pathlib import Path
import psutil

from app_config import has_gemini_api_key, has_text_agent_config, load_app_config, save_app_config
from actions.plugin_system import list_plugins, plugin_status

from ui.constants import (
    C_BG, C_PRI, C_ORG, C_ORG2, C_MID, C_DIM, C_DIMMER, C_TEXT,
    C_PANEL, C_GREEN, C_RED, C_MUTED, C_BLUE, C_GOLD, C_WARN,
    ORB_COLORS, STATE_HEX_COLORS, STATE_LABELS_TR,
    W_TARGET, H_TARGET, LEFT_W_T, RIGHT_W_T, HDR_H, FOOTER_H, INPUT_H, CONTROL_H,
    VOICES, SYSTEM_NAME, MODEL_BADGE,
    font_body, font_body_bold, font_display,
)
from ui.sfx import SoundManager
from ui.orb import OrbMixin
from ui.panels import PanelsMixin
from ui.controls import ControlsMixin
from ui.settings import SettingsMixin
from ui.conversations import ConversationsMixin


class JarvisUI(OrbMixin, PanelsMixin, ControlsMixin, SettingsMixin, ConversationsMixin):
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.update_idletasks()

        app_cfg = load_app_config()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        requested_w = int(app_cfg.get("window_width", 1360) or 1360)
        requested_h = int(app_cfg.get("window_height", 860) or 860)
        self.W = min(max(960, requested_w), max(960, sw - 48), W_TARGET)
        self.H = min(max(680, requested_h), max(680, sh - 80), H_TARGET)
        _geo = f"{self.W}x{self.H}+{(sw-self.W)//2}+{max(0, (sh-self.H)//2 - 8)}"
        self.root.geometry(_geo)
        self.root.minsize(min(960, sw), min(680, sh))
        self.root.resizable(True, True)
        self.root.configure(bg=C_BG)
        self.root.attributes('-topmost', bool(app_cfg.get("window_always_on_top", False)))
        self.root.lift()
        self.root.focus_force()
        for delay in (80, 220, 600, 1200):
            self.root.after(delay, self._force_startup_size)

        self._window_geometry = _geo
        self._normal_size = (self.W, self.H)
        self._fullscreen = app_cfg.get("window_mode", "windowed") == "fullscreen"

        self._set_layout_metrics(self.W, self.H)

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
        self.rings_spin      = [0.0, 45.0, 90.0, 200.0]
        self.pulse_r         = []
        self.status_blink    = True
        self._jarvis_state   = "INITIALISING"
        self._user_speaking_until = 0.0

        self._health_visible  = False
        self._health_query    = "all"
        self._health_display  = ""
        self._health_hide_job = None
        self._weather_card = {
            "city": "Istanbul",
            "primary": "--",
            "details": ["Hava durumu y\u00fckleniyor..."],
        }
        self._health_card_lines = ["Sa\u011fl\u0131k \u00f6zeti y\u00fckleniyor..."]
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
        self.setup_dialog = None
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

        self.on_text_command = None
        self.on_pause_toggle = None
        self.on_stop_command = None
        self.on_voice_change = None
        self.on_effects_state_change = None
        self.on_ptt_start = None
        self.on_ptt_stop = None
        self.on_wake_toggle = None
        self.on_new_conversation = None
        self.on_select_conversation = None

        self._current_voice = self._load_voice()

        self.sound = SoundManager()

        self._stats      = {'cpu': 0.0, 'ram': 0.0, 'disk': 0.0,
                            'battery': 100.0, 'net_up': 0.0, 'net_down': 0.0}
        self._cpu_hist   = [0.0] * 24
        self._last_net   = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._wave_jarvis = [random.randint(4, 26) for _ in range(18)]
        self._wave_user   = [random.randint(2, 10) for _ in range(18)]

        self.typing_queue = deque()
        self.is_typing    = False

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

        self.bg = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)

        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y,
                             width=self.CHAT_W, height=self.CHAT_H)
        self.chat_header = tk.Frame(self.log_frame, bg=C_PANEL, height=42)
        self.chat_header.pack(fill="x")
        self.chat_title = tk.Label(
            self.chat_header, text="AKTİF SOHBET", fg=C_TEXT, bg=C_PANEL,
            font=font_body_bold(11), anchor="w",
        )
        self.chat_title.pack(side="left", padx=14, pady=11)
        self.chat_context_badge = tk.Label(
            self.chat_header, text="BAĞLAM AÇIK", fg=C_PRI, bg=C_DIMMER,
            font=font_body_bold(8), padx=8, pady=4,
        )
        self.chat_context_badge.pack(side="right", padx=12, pady=8)
        self.log_text = tk.Text(
            self.log_frame, fg=C_TEXT, bg=C_PANEL,
            insertbackground=C_TEXT, borderwidth=0,
            wrap="word", font=font_body(12), padx=16, pady=12, spacing3=7)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#f8fafc")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_GOLD)
        self.log_text.tag_config("err", foreground=C_RED)

        self._build_input_bar(self.CHAT_W)
        self._build_conversation_sidebar()
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
        if self._fullscreen:
            self.root.after(120, self._enter_fullscreen)
        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)
