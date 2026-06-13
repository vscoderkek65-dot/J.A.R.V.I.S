import math, time, threading
from collections import deque

from ui.constants import (
    C_BG, C_PRI, C_ORG, C_ORG2, C_MID, C_DIM, C_DIMMER, C_TEXT,
    C_PANEL, C_GREEN, C_RED, C_MUTED, C_BLUE, C_GOLD, C_WARN,
    ORB_COLORS, STATE_HEX_COLORS,
    HDR_H, FOOTER_H, INPUT_H,
    font_body, font_body_bold, font_display,
)


class PanelsMixin:

    @staticmethod
    def _split_summary_lines(text, limit=4):
        raw = (text or "").strip()
        if not raw:
            return []
        raw = raw.replace(" ve ", ", ")
        parts = [part.strip(" .") for part in raw.split(",") if part.strip()]
        return parts[:limit]

    def _parse_weather_card(self, text):
        if not text or "al\u0131namad\u0131" in text.lower() or "al\u0131namadi" in text.lower():
            return {
                "city": "Istanbul",
                "primary": "--",
                "details": ["Hava durumu al\u0131namad\u0131."],
            }

        prefix, _, body = text.partition(":")
        city = "Istanbul"
        if " i\u00e7in" in prefix:
            city = prefix.split(" i\u00e7in", 1)[0].strip().title()

        details = [part.strip(" .") for part in body.split(",") if part.strip()]
        primary = "--"
        if details:
            primary = details[0].replace(" derece", "\u00b0C")
        return {
            "city": city,
            "primary": primary,
            "details": details[1:4] or ["Anl\u0131k veri haz\u0131r."],
        }

    def _parse_health_card(self, text):
        if not text or "al\u0131namad\u0131" in text.lower() or "al\u0131namadi" in text.lower():
            return ["Sa\u011fl\u0131k verisi al\u0131namad\u0131."]
        lines = self._split_summary_lines(text, limit=4)
        return lines or ["Sa\u011fl\u0131k \u00f6zeti haz\u0131r de\u011fil."]

    def _kick_brief_refresh(self):
        if self._brief_refresh_busy:
            return
        self._brief_refresh_busy = True
        threading.Thread(target=self._refresh_brief_cards, daemon=True).start()

    def _refresh_brief_cards(self):
        try:
            from actions.weather import get_weather_summary
            weather = get_weather_summary("Istanbul")
            self._weather_card = self._parse_weather_card(weather)
        except Exception:
            self._weather_card = {
                "city": "Istanbul",
                "primary": "--",
                "details": ["Hava durumu al\u0131namad\u0131."],
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

    def show_health_hologram(self, query, data_str):
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
        c.create_text(x0+pw//2, y0+18, text="\u2316 HEALTH \u2316",
                      fill=title_col, font=font_display(11))
        c.create_line(x0+8, y0+30, x0+pw-8, y0+30, fill=C_MID)

        lines = [l for l in self._health_display.split('\n') if l.strip()]
        ly = y0 + 44
        for line in lines:
            if ly > y0 + ph - 14:
                break
            if line.startswith("\u2500"):
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
            ("weather", 0.20, "WEATHER \u2502 ISTANBUL", C_BLUE),
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
                    c.create_text(section_x+section_pad, wy, text=f"\u25b8 {line}", fill=muted_text,
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
                    col = C_RED if val > 80 and key != "battery" else C_ORG if val > 55 and key != "battery" else (C_RED if key == "battery" and (val < 20) else C_GREEN if key == "battery" else C_PRI)
                    if dimmed:
                        col = muted_red if col == C_RED else muted_warn if col == C_ORG else muted_green if col == C_GREEN else muted_primary