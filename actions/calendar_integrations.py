from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import requests

from app_config import load_app_config


BASE_DIR = Path(__file__).resolve().parent.parent
OAUTH_DIR = BASE_DIR / "memory" / "oauth"
OUTLOOK_CACHE_PATH = OAUTH_DIR / "outlook_msal_cache.json"
OUTLOOK_FLOW_PATH = OAUTH_DIR / "outlook_device_flow.json"
GOOGLE_TOKEN_PATH = OAUTH_DIR / "google_calendar_token.json"

LOCAL_TZ = "Europe/Istanbul"
OUTLOOK_TZ = "Turkey Standard Time"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
OUTLOOK_SCOPES = ["User.Read", "Calendars.ReadWrite", "Tasks.ReadWrite", "offline_access"]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


class IntegrationAuthError(RuntimeError):
    pass


class IntegrationDependencyError(RuntimeError):
    pass


def _ensure_oauth_dir() -> None:
    OAUTH_DIR.mkdir(parents=True, exist_ok=True)


def _config() -> dict:
    return load_app_config()


def selected_calendar_provider(provider: str = "") -> str:
    value = (provider or _config().get("calendar_provider") or "outlook").strip().lower()
    if value in {"google", "google_calendar"}:
        return "google"
    return "outlook"


def _provider_label(provider: str = "") -> str:
    return "Google Calendar/Tasks" if selected_calendar_provider(provider) == "google" else "Outlook/Microsoft To Do"


def _dependency_message(package: str, feature: str) -> str:
    return (
        f"{feature} icin '{package}' paketi gerekli. "
        "setup_windows.ps1 dosyasini yeniden calistir veya requirements.txt paketlerini kur."
    )


def _parse_local_datetime(value: str) -> dt.datetime:
    raw = (value or "").strip()
    if not raw:
        return dt.datetime.now().astimezone()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    for candidate in (raw, raw.replace(" ", "T")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.astimezone()
            return parsed.astimezone()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            parsed = dt.datetime.strptime(raw, fmt)
            return parsed.astimezone()
        except ValueError:
            pass
    raise ValueError("Tarih formati gecersiz. YYYY-MM-DDTHH:MM veya YYYY-MM-DD kullan.")


def _month_start(value: dt.datetime) -> dt.datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(value: dt.datetime, months: int) -> dt.datetime:
    total = (value.year * 12 + (value.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    return value.replace(year=year, month=month, day=1)


def _calendar_window(query: str, limit: int) -> dict:
    q = (query or "today").strip().casefold()
    now = dt.datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    limit = max(1, min(60, int(limit or 6)))

    day_match = re.search(r"(\d+)\s*(gun|gün|day|days)", q)
    week_match = re.search(r"(\d+)\s*(hafta|week|weeks)", q)
    month_match = re.search(r"(\d+)\s*(ay|month|months)", q)

    if "gelecek ay" in q or "next month" in q:
        start = _add_months(_month_start(now), 1)
        end = _add_months(start, 1)
        return {"kind": "range", "start": start, "end": end, "limit": max(limit, 24), "header": "Gelecek ay icin {count} etkinlik buldum:", "empty": "Gelecek ay takviminde etkinlik gorunmuyor."}
    if "bu ay" in q or "this month" in q:
        start = _month_start(now)
        end = _add_months(start, 1)
        return {"kind": "range", "start": start, "end": end, "limit": max(limit, 24), "header": "Bu ay icin {count} etkinlik buldum:", "empty": "Bu ay takviminde etkinlik gorunmuyor."}
    if month_match:
        months = max(1, min(12, int(month_match.group(1))))
        return {"kind": "range", "start": today, "end": _add_months(_month_start(now), months), "limit": min(60, max(limit, months * 12)), "header": f"Onumuzdeki {months} ay icin {{count}} etkinlik buldum:", "empty": f"Onumuzdeki {months} ayda takviminde etkinlik gorunmuyor."}
    if week_match:
        weeks = max(1, min(12, int(week_match.group(1))))
        return {"kind": "range", "start": today, "end": today + dt.timedelta(days=weeks * 7), "limit": min(60, max(limit, weeks * 8)), "header": f"Onumuzdeki {weeks} hafta icin {{count}} etkinlik buldum:", "empty": f"Onumuzdeki {weeks} haftada takviminde etkinlik gorunmuyor."}
    if day_match:
        days = max(1, min(365, int(day_match.group(1))))
        return {"kind": "range", "start": today, "end": today + dt.timedelta(days=days), "limit": min(60, max(limit, days * 2)), "header": f"Onumuzdeki {days} gun icin {{count}} etkinlik buldum:", "empty": f"Onumuzdeki {days} gunde takviminde etkinlik gorunmuyor."}
    if any(token in q for token in ("yarin", "tomorrow")):
        return {"kind": "tomorrow", "start": today + dt.timedelta(days=1), "end": today + dt.timedelta(days=2), "limit": limit, "header": "Yarin icin {count} etkinlik buldum:", "empty": "Yarin takviminde etkinlik gorunmuyor."}
    if any(token in q for token in ("siradaki", "sıradaki", "sonraki", "next")):
        return {"kind": "next", "start": now, "end": now + dt.timedelta(days=365), "limit": 1, "header": "", "empty": "Siradaki takvim etkinligini bulamadim."}
    if any(token in q for token in ("ajanda", "agenda", "yaklasan", "yaklaşan", "upcoming")):
        return {"kind": "agenda", "start": now, "end": now + dt.timedelta(days=30), "limit": max(limit, 8), "header": "Yaklasan ajandanda {count} etkinlik var:", "empty": "Yaklasan takvim etkinligi gorunmuyor."}
    if any(token in q for token in ("hafta", "week", "7 gun", "7 gün")):
        return {"kind": "week", "start": today, "end": today + dt.timedelta(days=7), "limit": max(limit, 10), "header": "Onumuzdeki 7 gun icin {count} etkinlik buldum:", "empty": "Onumuzdeki 7 gunde takviminde etkinlik gorunmuyor."}
    return {"kind": "today", "start": today, "end": today + dt.timedelta(days=1), "limit": limit, "header": "Bugun icin {count} etkinlik buldum:", "empty": "Bugun takviminde etkinlik gorunmuyor."}


def _iso_no_offset(value: dt.datetime) -> str:
    return value.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _event_sort_key(item: dict) -> str:
    return str(item.get("start_iso") or "")


def _normalize_event(
    *,
    provider: str,
    event_id: str,
    title: str,
    start_iso: str,
    end_iso: str,
    calendar: str = "",
    calendar_id: str = "",
    location: str = "",
    all_day: bool = False,
) -> dict:
    return {
        "provider": provider,
        "id": str(event_id or ""),
        "title": str(title or "Adsiz etkinlik").strip() or "Adsiz etkinlik",
        "start_iso": str(start_iso or ""),
        "end_iso": str(end_iso or ""),
        "calendar": str(calendar or ""),
        "calendar_id": str(calendar_id or ""),
        "location": str(location or ""),
        "all_day": bool(all_day),
    }


def _format_event_line(event: dict) -> str:
    start_raw = str(event.get("start_iso") or "")
    end_raw = str(event.get("end_iso") or "")
    try:
        start = _parse_local_datetime(start_raw)
        end = _parse_local_datetime(end_raw) if end_raw else start
    except Exception:
        start = None
        end = None
    if start:
        date_part = start.strftime("%d.%m.%Y")
        time_part = "tum gun" if event.get("all_day") else f"{start.strftime('%H:%M')}-{end.strftime('%H:%M') if end else ''}"
        prefix = f"{date_part} {time_part}".strip()
    else:
        prefix = start_raw or "tarih yok"
    pieces = [f"{prefix} - {event.get('title', 'Adsiz etkinlik')}"]
    if event.get("calendar"):
        pieces.append(f"[{event['calendar']}]")
    if event.get("location"):
        pieces.append(f"@ {event['location']}")
    return " ".join(pieces)


def _format_event_list(events: list[dict], window: dict) -> str:
    if not events:
        return str(window.get("empty") or "Takvimde etkinlik gorunmuyor.")
    events = sorted(events, key=_event_sort_key)[: int(window.get("limit") or 6)]
    if window.get("kind") == "next":
        return f"Siradaki etkinlik: {_format_event_line(events[0])}."
    lines = [str(window.get("header") or "{count} etkinlik buldum:").format(count=len(events))]
    for event in events:
        lines.append(f"- {_format_event_line(event)}")
    return "\n".join(lines)


def _auth_required(provider: str) -> str:
    return f"{_provider_label(provider)} hesabi bagli degil. Ayarlardan {selected_calendar_provider(provider)} hesabini bagla."


def _outlook_config() -> tuple[str, str]:
    cfg = _config()
    client_id = str(cfg.get("outlook_client_id", "") or "").strip()
    tenant = str(cfg.get("outlook_tenant_id", "common") or "common").strip() or "common"
    return client_id, tenant


def _outlook_load_cache():
    try:
        import msal  # type: ignore
    except Exception as exc:
        raise IntegrationDependencyError(_dependency_message("msal", "Outlook/To Do entegrasyonu")) from exc
    cache = msal.SerializableTokenCache()
    if OUTLOOK_CACHE_PATH.exists():
        try:
            cache.deserialize(OUTLOOK_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return msal, cache


def _outlook_save_cache(cache) -> None:
    if getattr(cache, "has_state_changed", True):
        _ensure_oauth_dir()
        OUTLOOK_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _outlook_app():
    client_id, tenant = _outlook_config()
    if not client_id:
        raise IntegrationAuthError("Outlook OAuth client ID eksik. Integrations ayarlarindan outlook_client_id gir.")
    msal, cache = _outlook_load_cache()
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache,
    )
    return app, cache


def _outlook_get_token() -> str:
    app, cache = _outlook_app()
    accounts = app.get_accounts()
    result = app.acquire_token_silent(OUTLOOK_SCOPES, account=accounts[0] if accounts else None)
    _outlook_save_cache(cache)
    if not result or "access_token" not in result:
        raise IntegrationAuthError(_auth_required("outlook"))
    return str(result["access_token"])


def _graph_request(method: str, path: str, token: str, *, params: dict | None = None, json_body: dict | None = None) -> Any:
    url = path if path.startswith("http") else GRAPH_BASE + path
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": f'outlook.timezone="{OUTLOOK_TZ}"',
        },
        params=params,
        json=json_body,
        timeout=25,
    )
    if response.status_code == 204:
        return {}
    if response.status_code >= 400:
        detail = response.text[:700]
        raise RuntimeError(f"Microsoft Graph HTTP {response.status_code}: {detail}")
    return response.json()


def _outlook_calendar_id_by_name(token: str, calendar_name: str = "") -> tuple[str, str]:
    wanted = (calendar_name or "").strip().casefold()
    if not wanted:
        return "", ""
    data = _graph_request("GET", "/me/calendars", token)
    for item in data.get("value", []):
        name = str(item.get("name", "") or "")
        if wanted in {name.casefold(), str(item.get("id", "")).casefold()}:
            return str(item.get("id", "")), name
    for item in data.get("value", []):
        name = str(item.get("name", "") or "")
        if wanted in name.casefold():
            return str(item.get("id", "")), name
    return "", ""


def _outlook_list_events(start: dt.datetime, end: dt.datetime, limit: int, calendar_name: str = "") -> list[dict]:
    token = _outlook_get_token()
    calendar_id, resolved_calendar = _outlook_calendar_id_by_name(token, calendar_name)
    path = f"/me/calendars/{calendar_id}/calendarView" if calendar_id else "/me/calendarView"
    data = _graph_request(
        "GET",
        path,
        token,
        params={
            "startDateTime": _iso_no_offset(start),
            "endDateTime": _iso_no_offset(end),
            "$top": max(1, min(100, int(limit or 10))),
            "$orderby": "start/dateTime",
        },
    )
    events: list[dict] = []
    for item in data.get("value", []):
        start_info = item.get("start") or {}
        end_info = item.get("end") or {}
        events.append(
            _normalize_event(
                provider="outlook",
                event_id=item.get("id", ""),
                title=item.get("subject", ""),
                start_iso=start_info.get("dateTime", ""),
                end_iso=end_info.get("dateTime", ""),
                calendar=resolved_calendar,
                calendar_id=calendar_id,
                location=(item.get("location") or {}).get("displayName", ""),
                all_day=bool(item.get("isAllDay", False)),
            )
        )
    return events


def _event_body(title: str, start_iso: str, end_iso: str, notes: str, location: str, all_day: bool) -> dict:
    start = _parse_local_datetime(start_iso)
    if end_iso and end_iso.strip():
        end = _parse_local_datetime(end_iso)
    elif all_day:
        end = start + dt.timedelta(days=1)
    else:
        end = start + dt.timedelta(hours=1)
    if all_day:
        return {
            "subject": title,
            "isAllDay": True,
            "body": {"contentType": "Text", "content": notes or ""},
            "location": {"displayName": location or ""},
            "start": {"dateTime": start.date().isoformat(), "timeZone": OUTLOOK_TZ},
            "end": {"dateTime": end.date().isoformat(), "timeZone": OUTLOOK_TZ},
        }
    return {
        "subject": title,
        "isAllDay": False,
        "body": {"contentType": "Text", "content": notes or ""},
        "location": {"displayName": location or ""},
        "start": {"dateTime": _iso_no_offset(start), "timeZone": OUTLOOK_TZ},
        "end": {"dateTime": _iso_no_offset(end), "timeZone": OUTLOOK_TZ},
    }


def _outlook_add_event(title: str, start_iso: str, end_iso: str, notes: str, location: str, calendar_name: str, all_day: bool) -> dict:
    token = _outlook_get_token()
    calendar_id, resolved_calendar = _outlook_calendar_id_by_name(token, calendar_name)
    path = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"
    item = _graph_request("POST", path, token, json_body=_event_body(title, start_iso, end_iso, notes, location, all_day))
    start_info = item.get("start") or {}
    end_info = item.get("end") or {}
    return _normalize_event(
        provider="outlook",
        event_id=item.get("id", ""),
        title=item.get("subject", title),
        start_iso=start_info.get("dateTime", start_iso),
        end_iso=end_info.get("dateTime", end_iso),
        calendar=resolved_calendar,
        calendar_id=calendar_id,
        location=(item.get("location") or {}).get("displayName", location),
        all_day=bool(item.get("isAllDay", all_day)),
    )


def _match_events(events: list[dict], title: str, start_iso: str = "") -> list[dict]:
    wanted = (title or "").strip().casefold()
    if not wanted:
        return []
    matches = [event for event in events if wanted == str(event.get("title", "")).casefold()]
    if not matches:
        matches = [event for event in events if wanted in str(event.get("title", "")).casefold()]
    if start_iso and matches:
        try:
            wanted_date = _parse_local_datetime(start_iso).date()
            matches = [event for event in matches if _parse_local_datetime(str(event.get("start_iso", ""))).date() == wanted_date]
        except Exception:
            pass
    return matches


def _outlook_delete_events(title: str, start_iso: str, calendar_name: str, delete_all_matches: bool) -> tuple[list[dict], str]:
    token = _outlook_get_token()
    if start_iso:
        start = _parse_local_datetime(start_iso).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
    else:
        start = dt.datetime.now().astimezone()
        end = start + dt.timedelta(days=365)
    matches = _match_events(_outlook_list_events(start, end, 100, calendar_name), title, start_iso)
    if not matches:
        return [], "Eslesen takvim etkinligi bulunamadi."
    if len(matches) > 1 and not delete_all_matches:
        preview = " | ".join(_format_event_line(item) for item in matches[:5])
        return [], f"Birden fazla etkinlik eslesti; tarih belirt veya delete_all_matches=true kullan: {preview}"
    for event in matches:
        _graph_request("DELETE", f"/me/events/{event['id']}", token)
    return matches, ""


def _google_client_config() -> dict:
    cfg = _config()
    client_id = str(cfg.get("google_oauth_client_id", "") or "").strip()
    client_secret = str(cfg.get("google_oauth_client_secret", "") or "").strip()
    if not client_id or not client_secret:
        raise IntegrationAuthError("Google OAuth client ID/secret eksik. Integrations ayarlarindan Google bilgilerini gir.")
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _google_get_credentials(interactive: bool = False):
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
    except Exception as exc:
        raise IntegrationDependencyError(_dependency_message("google-auth-oauthlib", "Google Calendar/Tasks entegrasyonu")) from exc
    creds = None
    if GOOGLE_TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), GOOGLE_SCOPES)
        except Exception:
            creds = None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _ensure_oauth_dir()
        GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    if creds and creds.valid:
        return creds
    if not interactive:
        raise IntegrationAuthError(_auth_required("google"))
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except Exception as exc:
        raise IntegrationDependencyError(_dependency_message("google-auth-oauthlib", "Google OAuth baglantisi")) from exc
    flow = InstalledAppFlow.from_client_config(_google_client_config(), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)
    _ensure_oauth_dir()
    GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _google_get_service(service_name: str, version: str):
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as exc:
        raise IntegrationDependencyError(_dependency_message("google-api-python-client", "Google Calendar/Tasks entegrasyonu")) from exc
    return build(service_name, version, credentials=_google_get_credentials(False), cache_discovery=False)


def _google_calendar_id_by_name(service, calendar_name: str = "") -> tuple[str, str]:
    wanted = (calendar_name or "").strip().casefold()
    if not wanted:
        return "primary", "Primary"
    data = service.calendarList().list().execute()
    for item in data.get("items", []):
        summary = str(item.get("summary", "") or "")
        item_id = str(item.get("id", "") or "")
        if wanted in {summary.casefold(), item_id.casefold()}:
            return item_id, summary
    for item in data.get("items", []):
        summary = str(item.get("summary", "") or "")
        if wanted in summary.casefold():
            return str(item.get("id", "primary")), summary
    return "primary", "Primary"


def _google_normalize_event(item: dict, calendar: str, calendar_id: str) -> dict:
    start_info = item.get("start") or {}
    end_info = item.get("end") or {}
    all_day = "date" in start_info
    return _normalize_event(
        provider="google",
        event_id=item.get("id", ""),
        title=item.get("summary", ""),
        start_iso=start_info.get("dateTime") or start_info.get("date", ""),
        end_iso=end_info.get("dateTime") or end_info.get("date", ""),
        calendar=calendar,
        calendar_id=calendar_id,
        location=item.get("location", ""),
        all_day=all_day,
    )


def _google_list_events(start: dt.datetime, end: dt.datetime, limit: int, calendar_name: str = "") -> list[dict]:
    service = _google_get_service("calendar", "v3")
    calendar_id, calendar = _google_calendar_id_by_name(service, calendar_name)
    data = service.events().list(
        calendarId=calendar_id,
        timeMin=_iso_utc(start),
        timeMax=_iso_utc(end),
        maxResults=max(1, min(100, int(limit or 10))),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [_google_normalize_event(item, calendar, calendar_id) for item in data.get("items", [])]


def _google_event_body(title: str, start_iso: str, end_iso: str, notes: str, location: str, all_day: bool) -> dict:
    start = _parse_local_datetime(start_iso)
    end = _parse_local_datetime(end_iso) if end_iso and end_iso.strip() else start + (dt.timedelta(days=1) if all_day else dt.timedelta(hours=1))
    body = {"summary": title, "description": notes or "", "location": location or ""}
    if all_day:
        body["start"] = {"date": start.date().isoformat(), "timeZone": LOCAL_TZ}
        body["end"] = {"date": end.date().isoformat(), "timeZone": LOCAL_TZ}
    else:
        body["start"] = {"dateTime": start.isoformat(timespec="seconds"), "timeZone": LOCAL_TZ}
        body["end"] = {"dateTime": end.isoformat(timespec="seconds"), "timeZone": LOCAL_TZ}
    return body


def _google_add_event(title: str, start_iso: str, end_iso: str, notes: str, location: str, calendar_name: str, all_day: bool) -> dict:
    service = _google_get_service("calendar", "v3")
    calendar_id, calendar = _google_calendar_id_by_name(service, calendar_name)
    item = service.events().insert(
        calendarId=calendar_id,
        body=_google_event_body(title, start_iso, end_iso, notes, location, all_day),
    ).execute()
    return _google_normalize_event(item, calendar, calendar_id)


def _google_delete_events(title: str, start_iso: str, calendar_name: str, delete_all_matches: bool) -> tuple[list[dict], str]:
    service = _google_get_service("calendar", "v3")
    calendar_id, _calendar = _google_calendar_id_by_name(service, calendar_name)
    if start_iso:
        start = _parse_local_datetime(start_iso).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
    else:
        start = dt.datetime.now().astimezone()
        end = start + dt.timedelta(days=365)
    matches = _match_events(_google_list_events(start, end, 100, calendar_name), title, start_iso)
    if not matches:
        return [], "Eslesen takvim etkinligi bulunamadi."
    if len(matches) > 1 and not delete_all_matches:
        preview = " | ".join(_format_event_line(item) for item in matches[:5])
        return [], f"Birden fazla etkinlik eslesti; tarih belirt veya delete_all_matches=true kullan: {preview}"
    for event in matches:
        service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
    return matches, ""


def calendar_auth_status() -> str:
    provider = selected_calendar_provider()
    cfg = _config()
    lines = [f"Takvim saglayici: {_provider_label(provider)} ({provider})"]
    if provider == "outlook":
        client_id = bool(str(cfg.get("outlook_client_id", "") or "").strip())
        lines.append("Outlook credential: " + ("hazir" if client_id else "eksik"))
        lines.append("Outlook token cache: " + ("var" if OUTLOOK_CACHE_PATH.exists() else "yok"))
        lines.append("Bekleyen device-code: " + ("var" if OUTLOOK_FLOW_PATH.exists() else "yok"))
    else:
        google_ok = bool(str(cfg.get("google_oauth_client_id", "") or "").strip() and str(cfg.get("google_oauth_client_secret", "") or "").strip())
        lines.append("Google credential: " + ("hazir" if google_ok else "eksik"))
        lines.append("Google token: " + ("var" if GOOGLE_TOKEN_PATH.exists() else "yok"))
    lines.append("E-posta: bu fazda hazirlik modu; Mail.Read/Mail.Send izni istenmez.")
    return "\n".join(lines)


def connect_calendar_provider(provider: str = "", mode: str = "start") -> str:
    provider = selected_calendar_provider(provider)
    mode = (mode or "start").strip().lower()
    try:
        if provider == "outlook":
            app, cache = _outlook_app()
            accounts = app.get_accounts()
            silent = app.acquire_token_silent(OUTLOOK_SCOPES, account=accounts[0] if accounts else None)
            _outlook_save_cache(cache)
            if silent and silent.get("access_token"):
                return "Outlook/Microsoft To Do hesabi zaten bagli."
            if mode in {"complete", "finish", "test"}:
                if not OUTLOOK_FLOW_PATH.exists():
                    return "Bekleyen Outlook device-code akisi yok. Once mode=start ile baglanti baslat."
                flow = json.loads(OUTLOOK_FLOW_PATH.read_text(encoding="utf-8"))
                result = app.acquire_token_by_device_flow(flow)
                _outlook_save_cache(cache)
                if "access_token" not in result:
                    return f"Outlook baglantisi tamamlanamadi: {result.get('error_description') or result.get('error') or 'bilinmeyen hata'}"
                try:
                    OUTLOOK_FLOW_PATH.unlink()
                except Exception:
                    pass
                return "Outlook/Microsoft To Do hesabi baglandi ve token cache kaydedildi."
            flow = app.initiate_device_flow(scopes=OUTLOOK_SCOPES)
            if "user_code" not in flow:
                return "Outlook device-code akisi baslatilamadi."
            _ensure_oauth_dir()
            OUTLOOK_FLOW_PATH.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
            return (
                "Outlook baglantisi baslatildi.\n"
                f"{flow.get('message', '')}\n"
                "Giris yaptiktan sonra connect_calendar_provider(provider='outlook', mode='complete') calistir."
            )
        _google_get_credentials(interactive=True)
        return "Google Calendar/Tasks hesabi baglandi ve token kaydedildi."
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"{_provider_label(provider)} baglantisi basarisiz: {type(exc).__name__}: {exc}"


def disconnect_calendar_provider(provider: str = "") -> str:
    provider = selected_calendar_provider(provider)
    removed = []
    paths = [OUTLOOK_CACHE_PATH, OUTLOOK_FLOW_PATH] if provider == "outlook" else [GOOGLE_TOKEN_PATH]
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                removed.append(path.name)
        except Exception as exc:
            return f"{_provider_label(provider)} baglantisi kaldirilamadi: {exc}"
    if not removed:
        return f"{_provider_label(provider)} icin kayitli token yok."
    return f"{_provider_label(provider)} baglantisi kaldirildi: {', '.join(removed)}"


def list_calendars(provider: str = "") -> str:
    provider = selected_calendar_provider(provider)
    try:
        if provider == "outlook":
            token = _outlook_get_token()
            data = _graph_request("GET", "/me/calendars", token)
            items = data.get("value", [])
            if not items:
                return "Outlook takvimi bulunamadi."
            return "Outlook takvimleri:\n" + "\n".join(f"- {item.get('name', 'Adsiz')} ({item.get('id', '-')})" for item in items[:20])
        service = _google_get_service("calendar", "v3")
        data = service.calendarList().list().execute()
        items = data.get("items", [])
        if not items:
            return "Google takvimi bulunamadi."
        return "Google takvimleri:\n" + "\n".join(f"- {item.get('summary', 'Adsiz')} ({item.get('id', '-')})" for item in items[:20])
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Takvimler alinamadi: {type(exc).__name__}: {exc}"


def get_calendar_events_windows(query: str = "today", limit: int = 6) -> str:
    provider = selected_calendar_provider()
    window = _calendar_window(query, limit)
    try:
        if provider == "outlook":
            events = _outlook_list_events(window["start"], window["end"], window["limit"])
        else:
            events = _google_list_events(window["start"], window["end"], window["limit"])
        return _format_event_list(events, window)
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Takvim okunamadi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def add_calendar_event_windows(title: str, start_iso: str, end_iso: str = "", notes: str = "", location: str = "", calendar_name: str = "", all_day: bool = False) -> str:
    provider = selected_calendar_provider()
    title = (title or "").strip()
    if not title:
        return "Takvime eklemek icin etkinlik basligi gerekli."
    if not (start_iso or "").strip():
        return "Takvime eklemek icin baslangic tarihi gerekli."
    try:
        if provider == "outlook":
            event = _outlook_add_event(title, start_iso, end_iso, notes, location, calendar_name, all_day)
        else:
            event = _google_add_event(title, start_iso, end_iso, notes, location, calendar_name, all_day)
        return f"Takvime eklendi ({_provider_label(provider)}): {_format_event_line(event)}."
    except ValueError as exc:
        return str(exc)
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Takvim etkinligi eklenemedi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def delete_calendar_event_windows(title: str, start_iso: str = "", calendar_name: str = "", delete_all_matches: bool = False) -> str:
    provider = selected_calendar_provider()
    title = (title or "").strip()
    if not title:
        return "Takvimden silmek icin etkinlik basligi gerekli."
    try:
        if provider == "outlook":
            deleted, detail = _outlook_delete_events(title, start_iso, calendar_name, delete_all_matches)
        else:
            deleted, detail = _google_delete_events(title, start_iso, calendar_name, delete_all_matches)
        if detail:
            return detail
        lines = [f"Takvimden silindi ({_provider_label(provider)}):"]
        lines.extend(f"- {_format_event_line(event)}" for event in deleted)
        return "\n".join(lines)
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Takvim etkinligi silinemedi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def _task_window(query: str, limit: int) -> dict:
    q = (query or "upcoming").strip().casefold()
    now = dt.datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if any(token in q for token in ("bugun", "today")):
        return {"kind": "today", "start": today, "end": today + dt.timedelta(days=1), "limit": limit, "header": "Bugun icin {count} animsatici buldum:", "empty": "Bugun icin animsatici gorunmuyor."}
    if any(token in q for token in ("geciken", "gecmis", "overdue")):
        return {"kind": "overdue", "start": None, "end": now, "limit": limit, "header": "Gecikmis {count} animsatici buldum:", "empty": "Geciken animsatici gorunmuyor."}
    if any(token in q for token in ("siradaki", "sıradaki", "next")):
        return {"kind": "next", "start": now, "end": None, "limit": 1, "header": "", "empty": "Siradaki animsaticiyi bulamadim."}
    if any(token in q for token in ("hepsi", "tum", "tüm", "all", "listele")):
        return {"kind": "all", "start": None, "end": None, "limit": limit, "header": "Acik {count} animsatici buldum:", "empty": "Kayitli acik animsatici gorunmuyor."}
    return {"kind": "upcoming", "start": now, "end": now + dt.timedelta(days=30), "limit": limit, "header": "Yaklasan {count} animsatici buldum:", "empty": "Yaklasan animsatici gorunmuyor."}


def _normalize_task(provider: str, list_id: str, task_id: str, title: str, due_iso: str = "", list_name: str = "", notes: str = "", status: str = "", importance: str = "") -> dict:
    return {
        "provider": provider,
        "id": str(task_id or ""),
        "composite_id": f"{list_id}:{task_id}" if list_id and task_id else str(task_id or ""),
        "list_id": str(list_id or ""),
        "title": str(title or "Adsiz animsatici").strip() or "Adsiz animsatici",
        "due_iso": str(due_iso or ""),
        "list_name": str(list_name or ""),
        "notes": str(notes or ""),
        "status": str(status or ""),
        "importance": str(importance or ""),
    }


def _format_task_line(task: dict) -> str:
    due = str(task.get("due_iso") or "zaman atanmamis")
    try:
        if due and due != "zaman atanmamis":
            due = _parse_local_datetime(due).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass
    suffix = f" [{task['list_name']}]" if task.get("list_name") else ""
    return f"{task.get('composite_id') or task.get('id')}: {due} - {task.get('title', 'Adsiz')}{suffix}"


def _task_in_window(task: dict, window: dict) -> bool:
    if window["kind"] == "all":
        return True
    due_raw = str(task.get("due_iso") or "")
    if not due_raw:
        return window["kind"] not in {"today", "overdue", "next"}
    try:
        due = _parse_local_datetime(due_raw)
    except Exception:
        return True
    start = window.get("start")
    end = window.get("end")
    if start and due < start:
        return window["kind"] == "overdue"
    if end and due >= end:
        return False
    return True


def _format_task_list(tasks: list[dict], window: dict) -> str:
    tasks = [task for task in tasks if _task_in_window(task, window)]
    tasks.sort(key=lambda item: (not item.get("due_iso"), item.get("due_iso") or "", item.get("title") or ""))
    tasks = tasks[: max(1, min(50, int(window.get("limit") or 8)))]
    if not tasks:
        return str(window.get("empty") or "Animsatici gorunmuyor.")
    if window.get("kind") == "next":
        return "Siradaki animsatici: " + _format_task_line(tasks[0])
    lines = [str(window.get("header") or "{count} animsatici buldum:").format(count=len(tasks))]
    lines.extend(f"- {_format_task_line(task)}" for task in tasks)
    return "\n".join(lines)


def _outlook_task_lists(token: str) -> list[dict]:
    data = _graph_request("GET", "/me/todo/lists", token)
    return data.get("value", [])


def _outlook_task_list_by_name(token: str, list_name: str = "") -> tuple[str, str]:
    lists = _outlook_task_lists(token)
    wanted = (list_name or "").strip().casefold()
    if wanted:
        for item in lists:
            name = str(item.get("displayName", "") or "")
            if wanted in {name.casefold(), str(item.get("id", "")).casefold()}:
                return str(item.get("id", "")), name
        for item in lists:
            name = str(item.get("displayName", "") or "")
            if wanted in name.casefold():
                return str(item.get("id", "")), name
    if lists:
        return str(lists[0].get("id", "")), str(lists[0].get("displayName", "Tasks") or "Tasks")
    raise RuntimeError("Microsoft To Do listesi bulunamadi.")


def _outlook_tasks(list_name: str = "") -> list[dict]:
    token = _outlook_get_token()
    list_id, resolved_name = _outlook_task_list_by_name(token, list_name)
    data = _graph_request("GET", f"/me/todo/lists/{list_id}/tasks", token)
    tasks = []
    for item in data.get("value", []):
        if str(item.get("status", "")).casefold() == "completed":
            continue
        due_info = item.get("dueDateTime") or {}
        tasks.append(
            _normalize_task(
                "outlook",
                list_id,
                item.get("id", ""),
                item.get("title", ""),
                due_info.get("dateTime", ""),
                resolved_name,
                (item.get("body") or {}).get("content", ""),
                item.get("status", ""),
                item.get("importance", ""),
            )
        )
    return tasks


def _outlook_add_task(title: str, due_iso: str, notes: str, list_name: str, priority: str, all_day: bool) -> dict:
    token = _outlook_get_token()
    list_id, resolved_name = _outlook_task_list_by_name(token, list_name)
    body: dict[str, Any] = {"title": title, "body": {"content": notes or "", "contentType": "text"}}
    if due_iso and due_iso.strip():
        due = _parse_local_datetime(due_iso)
        body["dueDateTime"] = {"dateTime": due.date().isoformat() if all_day else _iso_no_offset(due), "timeZone": OUTLOOK_TZ}
    if (priority or "").strip().casefold() in {"high", "yuksek", "yüksek"}:
        body["importance"] = "high"
    item = _graph_request("POST", f"/me/todo/lists/{list_id}/tasks", token, json_body=body)
    due_info = item.get("dueDateTime") or {}
    return _normalize_task("outlook", list_id, item.get("id", ""), item.get("title", title), due_info.get("dateTime", due_iso), resolved_name, notes, item.get("status", ""), item.get("importance", ""))


def _google_task_lists(service) -> list[dict]:
    data = service.tasklists().list(maxResults=100).execute()
    return data.get("items", [])


def _google_task_list_by_name(service, list_name: str = "") -> tuple[str, str]:
    lists = _google_task_lists(service)
    wanted = (list_name or "").strip().casefold()
    if wanted:
        for item in lists:
            title = str(item.get("title", "") or "")
            if wanted in {title.casefold(), str(item.get("id", "")).casefold()}:
                return str(item.get("id", "")), title
        for item in lists:
            title = str(item.get("title", "") or "")
            if wanted in title.casefold():
                return str(item.get("id", "")), title
    if lists:
        return str(lists[0].get("id", "")), str(lists[0].get("title", "Tasks") or "Tasks")
    raise RuntimeError("Google Tasks listesi bulunamadi.")


def _google_tasks(list_name: str = "") -> list[dict]:
    service = _google_get_service("tasks", "v1")
    list_id, resolved_name = _google_task_list_by_name(service, list_name)
    data = service.tasks().list(tasklist=list_id, showCompleted=False, maxResults=100).execute()
    tasks = []
    for item in data.get("items", []):
        tasks.append(
            _normalize_task(
                "google",
                list_id,
                item.get("id", ""),
                item.get("title", ""),
                item.get("due", ""),
                resolved_name,
                item.get("notes", ""),
                item.get("status", ""),
            )
        )
    return tasks


def _google_add_task(title: str, due_iso: str, notes: str, list_name: str, _priority: str, _all_day: bool) -> dict:
    service = _google_get_service("tasks", "v1")
    list_id, resolved_name = _google_task_list_by_name(service, list_name)
    body = {"title": title, "notes": notes or ""}
    if due_iso and due_iso.strip():
        body["due"] = _parse_local_datetime(due_iso).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    item = service.tasks().insert(tasklist=list_id, body=body).execute()
    return _normalize_task("google", list_id, item.get("id", ""), item.get("title", title), item.get("due", due_iso), resolved_name, item.get("notes", notes), item.get("status", ""))


def _match_tasks(tasks: list[dict], reminder_id: str = "", title: str = "") -> list[dict]:
    rid = (reminder_id or "").strip()
    if rid:
        return [task for task in tasks if rid in {task.get("id", ""), task.get("composite_id", "")}]
    wanted = (title or "").strip().casefold()
    if not wanted:
        return []
    matches = [task for task in tasks if wanted == str(task.get("title", "")).casefold()]
    if not matches:
        matches = [task for task in tasks if wanted in str(task.get("title", "")).casefold()]
    return matches


def get_reminders_windows(query: str = "upcoming", limit: int = 8, list_name: str = "") -> str:
    provider = selected_calendar_provider()
    window = _task_window(query, max(1, min(50, int(limit or 8))))
    try:
        tasks = _outlook_tasks(list_name) if provider == "outlook" else _google_tasks(list_name)
        return _format_task_list(tasks, window)
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Animsaticilar okunamadi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def add_reminder_windows(title: str, due_iso: str = "", notes: str = "", list_name: str = "", priority: str = "", all_day: bool = False) -> str:
    provider = selected_calendar_provider()
    title = (title or "").strip()
    if not title:
        return "Animsatici basligi bos olamaz."
    try:
        task = _outlook_add_task(title, due_iso, notes, list_name, priority, all_day) if provider == "outlook" else _google_add_task(title, due_iso, notes, list_name, priority, all_day)
        return f"Animsatici eklendi ({_provider_label(provider)}): {_format_task_line(task)}"
    except ValueError as exc:
        return str(exc)
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Animsatici eklenemedi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def _outlook_complete_or_delete_task(reminder_id: str, title: str, list_name: str, delete: bool) -> tuple[list[dict], str]:
    token = _outlook_get_token()
    tasks = _outlook_tasks(list_name)
    matches = _match_tasks(tasks, reminder_id, title)
    if not matches:
        return [], "Eslesen animsatici bulunamadi."
    if len(matches) > 1:
        return [], "Birden fazla animsatici eslesti: " + " | ".join(_format_task_line(task) for task in matches[:5])
    task = matches[0]
    if delete:
        _graph_request("DELETE", f"/me/todo/lists/{task['list_id']}/tasks/{task['id']}", token)
    else:
        _graph_request("PATCH", f"/me/todo/lists/{task['list_id']}/tasks/{task['id']}", token, json_body={"status": "completed"})
    return [task], ""


def _google_complete_or_delete_task(reminder_id: str, title: str, list_name: str, delete: bool) -> tuple[list[dict], str]:
    service = _google_get_service("tasks", "v1")
    tasks = _google_tasks(list_name)
    matches = _match_tasks(tasks, reminder_id, title)
    if not matches:
        return [], "Eslesen animsatici bulunamadi."
    if len(matches) > 1:
        return [], "Birden fazla animsatici eslesti: " + " | ".join(_format_task_line(task) for task in matches[:5])
    task = matches[0]
    if delete:
        service.tasks().delete(tasklist=task["list_id"], task=task["id"]).execute()
    else:
        service.tasks().patch(tasklist=task["list_id"], task=task["id"], body={"status": "completed"}).execute()
    return [task], ""


def complete_reminder(reminder_id: str = "", title: str = "", list_name: str = "") -> str:
    provider = selected_calendar_provider()
    try:
        done, detail = _outlook_complete_or_delete_task(reminder_id, title, list_name, delete=False) if provider == "outlook" else _google_complete_or_delete_task(reminder_id, title, list_name, delete=False)
        if detail:
            return detail
        return f"Animsatici tamamlandi ({_provider_label(provider)}): {_format_task_line(done[0])}"
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Animsatici tamamlanamadi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"


def delete_reminder(reminder_id: str = "", title: str = "", list_name: str = "") -> str:
    provider = selected_calendar_provider()
    try:
        deleted, detail = _outlook_complete_or_delete_task(reminder_id, title, list_name, delete=True) if provider == "outlook" else _google_complete_or_delete_task(reminder_id, title, list_name, delete=True)
        if detail:
            return detail
        return f"Animsatici silindi ({_provider_label(provider)}): {_format_task_line(deleted[0])}"
    except (IntegrationAuthError, IntegrationDependencyError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Animsatici silinemedi ({_provider_label(provider)}): {type(exc).__name__}: {exc}"
