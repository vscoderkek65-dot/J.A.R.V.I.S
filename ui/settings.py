import os, time, threading
import tkinter as tk
from actions.plugin_system import list_plugins, plugin_status

from ui.constants import (
    C_BG, C_PRI, C_ORG, C_ORG2, C_MID, C_DIM, C_DIMMER, C_TEXT,
    C_PANEL, C_GREEN, C_RED, C_MUTED, C_BLUE, C_GOLD, C_WARN,
    HDR_H, FOOTER_H, INPUT_H, CONTROL_H,
    SYSTEM_NAME, MODEL_BADGE,
    font_body, font_body_bold, font_display,
)


class SettingsMixin:

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
        c.create_text(bw - 14, bh // 2, text="\u25b6" if self._settings_open else "\u25c0",
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

    def _set_settings_tab(self, tab):
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
        from app_config import load_app_config
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
            "OpenAI/9Router hazir" if cloud_ready else "OpenAI/9Router eksik",
            "Local hazir" if local_ready else "Local eksik",
            "Tavily hazir" if tavily_ready else "Tavily opsiyonel",
            f"Takvim: {calendar_provider}",
        ]
        if yt_handle:
            handle_text = yt_handle
        else:
            handle_text = "@handle girilmedi"
        voice_mode = str(cfg.get("voice_input_mode", "ptt_wake") or "ptt_wake")
        secondary = f"Kanal: {handle_text}  \u2502  Ses: {voice_mode}  \u2502  {self.wake_status[:90]}"

        self._settings_status_primary.configure(text="  \u2502  ".join(primary))
        self._settings_status_secondary.configure(text=secondary)

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
        c.create_text(bw // 2, bh // 2, text="\u29d7 API SETTINGS",
                      fill=C_BLUE, font=font_body_bold(10))

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

    def _plugin_output(self, text):
        if self.plugin_output_text and self.plugin_output_text.winfo_exists():
            self.plugin_output_text.configure(state="normal")
            self.plugin_output_text.delete("1.0", tk.END)
            self.plugin_output_text.insert(tk.END, str(text or ""))
            self.plugin_output_text.configure(state="disabled")

    def _selected_plugin_id(self):
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

    def _plugin_config_json(self):
        if not self.plugin_config_text:
            return "{}"
        return self.plugin_config_text.get("1.0", tk.END).strip() or "{}"

    def _plugin_enable_from_ui(self):
        from actions.plugin_system import enable_plugin
        result = enable_plugin(self._selected_plugin_id())
        self._plugin_output(result)
        self.write_log("SYS: " + result.replace("\n", " | "))

    def _plugin_disable_from_ui(self):
        from actions.plugin_system import disable_plugin
        result = disable_plugin(self._selected_plugin_id())
        self._plugin_output(result)
        self.write_log("SYS: " + result.replace("\n", " | "))

    def _plugin_save_config_from_ui(self):
        from actions.plugin_system import set_plugin_config
        result = set_plugin_config(self._selected_plugin_id(), self._plugin_config_json(), True)
        self._plugin_output(result)
        self.write_log("SYS: Plugin config kaydedildi.")

    def _plugin_discover_from_ui(self):
        from actions.plugin_system import discover_plugin_tools
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
        from app_config import load_app_config
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

        from actions.calendar_integrations import calendar_auth_status
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

    def _integration_provider_key(self):
        label = self.calendar_provider_var.get().strip() if self.calendar_provider_var else "Outlook"
        return "google" if label == "Google" else "outlook"

    def _save_integrations_settings(self, close=False):
        from app_config import save_app_config
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

    def _run_calendar_oauth(self, mode):
        from actions.calendar_integrations import connect_calendar_provider
        provider = self._integration_provider_key()
        self._save_integrations_settings(close=False)

        def worker():
            result = connect_calendar_provider(provider, mode)
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))

        threading.Thread(target=worker, daemon=True).start()

    def _disconnect_calendar_oauth(self):
        from actions.calendar_integrations import disconnect_calendar_provider
        provider = self._integration_provider_key()
        self._save_integrations_settings(close=False)

        def worker():
            result = disconnect_calendar_provider(provider)
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))

        threading.Thread(target=worker, daemon=True).start()

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self, edit_mode=False):
        self._close_setup_ui()
        from app_config import load_app_config

        self.setup_frame = tk.Frame(self.root, bg="#00080d",
                                    highlightbackground=C_PRI,
                                    highlightthickness=1)
        setup_w = min(820, max(620, int(self.W * 0.46)))
        setup_h = min(max(560, self.H - 90), max(620, int(self.H * 0.66)))
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        self.setup_frame.pack_propagate(False)

        title = "\u2316 API AYARLARI" if edit_mode else "\u2316 \u0130LK KURULUM GEREKL\u0130"
        subtitle = (
            "Gemini, OpenAI API/9Router, Local AI ve YouTube ayarlarinizi guncelleyin."
            if edit_mode else
            "OpenAI API/9Router, Local veya Hybrid ajan modunu secin. YouTube/Tavily alanlari opsiyoneldir."
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
            "cloud": "OpenAI API / 9Router",
            "local": "Local",
        }
        current_provider = str(config.get("agent_mode", "hybrid") or "hybrid")
        self.agent_provider_var = tk.StringVar(value=provider_map.get(current_provider, "Hybrid"))
        self.agent_provider_var.trace_add("write", lambda *_: self._refresh_setup_provider_state())
        provider_menu = tk.OptionMenu(
            self.setup_frame,
            self.agent_provider_var,
            "Hybrid",
            "OpenAI API / 9Router",
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

        tk.Label(self.setup_frame, text="OPENAI API / 9ROUTER URL",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_url_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10))
        self.ninerouter_url_entry.pack(pady=(0, 3), ipady=3)
        current_url = str(config.get("cloud_base_url", "") or config.get("ninerouter_base_url", "") or "")
        if current_url:
            self.ninerouter_url_entry.insert(0, current_url)

        tk.Label(self.setup_frame, text="OPENAI-COMPATIBLE MODEL",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_model_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10))
        self.ninerouter_model_entry.pack(pady=(0, 3), ipady=3)
        current_model = str(config.get("cloud_model", "") or config.get("ninerouter_model", "") or "")
        if current_model:
            self.ninerouter_model_entry.insert(0, current_model)

        tk.Label(self.setup_frame, text="OPENAI-COMPATIBLE API KEY",
                 fg=C_DIM, bg="#00080d", font=font_body(10)).pack(pady=(3, 2))
        self.ninerouter_key_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#000d12", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(10), show="*")
        self.ninerouter_key_entry.pack(pady=(0, 3), ipady=3)
        current_ninerouter_key = str(config.get("cloud_api_key", "") or config.get("ninerouter_api_key", "") or "")
        if current_ninerouter_key:
            self.ninerouter_key_entry.insert(0, current_ninerouter_key)

        tk.Label(
            self.setup_frame,
            text="Not: ChatGPT Plus/Business OAuth, model API key yerine gecmez.",
            fg=C_WARN,
            bg="#00080d",
            font=font_body(9),
            wraplength=520,
            justify="center",
        ).pack(pady=(0, 4))

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

        tk.Button(buttons, text="\u2714 KAYDET",
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
        cloud_state = "normal" if label in {"Hybrid", "OpenAI API / 9Router"} else "disabled"
        local_state = "normal" if label in {"Hybrid", "Local"} else "disabled"
        for entry in (self.ninerouter_url_entry, self.ninerouter_model_entry, self.ninerouter_key_entry):
            if entry:
                entry.configure(state=cloud_state)
        for entry in (self.local_url_entry, self.local_model_entry, self.local_key_entry, self.local_foundry_alias_entry):
            if entry:
                entry.configure(state=local_state)
        if self.api_entry:
            self.api_entry.configure(state="normal")

    def _setup_mode_key(self):
        label = self.agent_provider_var.get().strip() if self.agent_provider_var else "Hybrid"
        return {"Hybrid": "hybrid", "OpenAI API / 9Router": "cloud", "Local": "local"}.get(label, "hybrid")

    def _setup_local_provider_key(self):
        label = self.local_provider_var.get().strip() if self.local_provider_var else "Microsoft Foundry Local"
        if label == "Manual OpenAI-Compatible":
            return "openai_compatible"
        return "foundry_local"

    def _collect_setup_updates(self):
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
        from app_config import save_app_config
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
            self.write_log("ERR: Kaydetmek icin Gemini, OpenAI/9Router endpoint veya Local AI alanlarini doldur.")
            return
        save_app_config(updates)
        self._close_setup_ui()
        self._api_key_ready = True
        self._refresh_settings_status()
        if was_ready:
            self.write_log("SYS: API ayarlari guncellendi.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: JARVIS haz\u0131r. Dinliyorum...")

    def _test_local_ai_from_setup(self):
        from app_config import save_app_config
        updates = self._collect_setup_updates()
        save_app_config(updates)
        self.write_log("SYS: Local AI testi baslatildi...")

        def worker():
            from actions.local_ai import test_local_ai
            result = test_local_ai("Merhaba, JARVIS local testine tek cumle cevap ver.")
            self.root.after(0, lambda: self.write_log("SYS: " + result.replace("\n", " | ")))
            self.root.after(0, self._refresh_settings_status)

        threading.Thread(target=worker, daemon=True).start()
