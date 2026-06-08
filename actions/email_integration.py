from __future__ import annotations

from app_config import load_app_config


def email_integration_status() -> str:
    cfg = load_app_config()
    provider = str(cfg.get("email_provider", "") or "").strip() or "hazir degil"
    calendar_provider = str(cfg.get("calendar_provider", "outlook") or "outlook").strip()
    return (
        "E-posta entegrasyonu hazirlik modunda.\n"
        f"- Planlanan provider: {provider}\n"
        f"- Takvim provider baglami: {calendar_provider}\n"
        "- Bu fazda Mail.Read veya Mail.Send izni istenmez; okuma/gonderme tool'u acik degil."
    )
