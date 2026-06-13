import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = f"VOICE CORE \u2502 {platform.system() or 'Desktop'}"

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
C_WARN    = "#ff9900"

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

W_TARGET = 2200
H_TARGET = 1320
LEFT_W_T = 360
RIGHT_W_T = 410
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
