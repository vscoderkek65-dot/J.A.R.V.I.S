import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = f"VOICE CORE \u2502 {platform.system() or 'Desktop'}"

C_BG      = "#080b10"
C_PRI     = "#5eead4"
C_ORG     = "#f97316"
C_ORG2    = "#f59e0b"
C_MID     = "#355261"
C_DIM     = "#1c2a33"
C_DIMMER  = "#111820"
C_TEXT    = "#e5eef5"
C_PANEL   = "#101720"
C_GREEN   = "#34d399"
C_RED     = "#fb4b5b"
C_MUTED   = "#d94670"
C_BLUE    = "#60a5fa"
C_GOLD    = "#fbbf24"
C_WARN    = "#f59e0b"

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

W_TARGET = 1680
H_TARGET = 1050
LEFT_W_T = 270
RIGHT_W_T = 500
HDR_H    = 72
FOOTER_H = 26
INPUT_H  = 34
CONTROL_H = 146

VOICES = ["Charon", "Puck", "Aoede", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"]

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
    "LISTENING": "D\u0130NL\u0130YOR",
    "THINKING": "D\u00dc\u015e\u00dcN\u00dcYOR",
    "RESEARCHING": "ARA\u015eTIRIYOR",
    "SPEAKING": "KONU\u015eUYOR",
    "WAITING_APPROVAL": "ONAY BEKL\u0130YOR",
    "ERROR": "HATA",
    "INITIALISING": "BA\u011eLANIYOR",
    "PAUSED": "DURAKLATILDI",
}
