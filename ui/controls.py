import os, time, threading, tkinter as tk
from pathlib import Path

from ui.constants import (
    C_BG, C_PRI, C_ORG, C_ORG2, C_MID, C_DIM, C_DIMMER, C_TEXT,
    C_PANEL, C_GREEN, C_RED, C_MUTED, C_BLUE, C_GOLD, C_WARN,
    HDR_H, FOOTER_H, INPUT_H, CONTROL_H,
    VOICES,
    font_body, font_body_bold, font_display,
)


class ControlsMixin:

    def _load_voice(self):
        try:
            from app_config import load_app_config
            return str(load_app_config().get("voice", "Charon") or "Charon")
        except Exception:
            return "Charon"

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
        bl = 8
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=C_RED, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=C_RED, width=2)
        c.create_text(BW//2, BH//2, text="\u23fb  SHUTDOWN",
                      fill=C_RED, font=font_display(11))

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
            col, icon, lbl = C_MUTED, "\u23f9\u20dd", " MUTED"
        else:
            col, icon, lbl = C_GREEN, "\u23fa\u2714", " LIVE"
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
            col, text = C_GOLD, "\u25b6 RESUME"
        else:
            col, text = C_BLUE, "\u23f8 PAUSE"
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
            self.write_log("SYS: Mikrofon kapat\u0131ld\u0131.")
        else:
            self.write_log("SYS: Mikrofon a\u00e7\u0131k.")
        self._sync_sound_state()

    def _toggle_pause(self):
        self.paused = not self.paused
        self._draw_pause_button()
        if self.paused:
            self.set_state("PAUSED")
            self.write_log("SYS: JARVIS duraklat\u0131ld\u0131.")
        else:
            self.set_state("THINKING")
            self.write_log("SYS: JARVIS devam ediyor...")
        self._sync_sound_state()
        if self.on_pause_toggle:
            threading.Thread(target=self.on_pause_toggle, args=(self.paused,), daemon=True).start()

    def _shutdown(self):
        self.sound.stop_all()
        self.write_log("SYS: JARVIS kapat\u0131l\u0131yor...")
        self.root.after(380, os._exit, 0)

    def _build_input_bar(self, lw):
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
            self.root, text="SEND \u2b62",
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
            self.write_log("SYS: \u23f9 Ses kesildi.")
            if self.on_stop_command:
                threading.Thread(target=self.on_stop_command, daemon=True).start()
            return
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

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
        text = "\u266b SFX ON"  if self._sfx_on else "\u266b SFX OFF"
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

    def _on_voice_select(self, voice):
        self._current_voice = voice
        from app_config import save_app_config
        save_app_config({"voice": voice})
        if self.on_voice_change:
            threading.Thread(target=self.on_voice_change, args=(voice,), daemon=True).start()

    def _build_wake_toggle(self, parent=None):
        parent = parent or self.root
        from app_config import load_app_config
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
        from app_config import save_app_config
        save_app_config({"wake_word_enabled": enabled})
        self.write_log(f"SYS: Wake word {'acildi' if enabled else 'kapatildi'}.")
        if self.on_wake_toggle:
            threading.Thread(target=self.on_wake_toggle, args=(enabled,), daemon=True).start()

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
