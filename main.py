#!/usr/bin/env python3
"""
JARVIS desktop — Gercek zamanli sesli yardimci cekirdegi
Windows/macOS ortamina uyarlanmis calisma akisi
"""

import asyncio
import argparse
import datetime
import threading
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace

try:
    import pyaudio  # type: ignore[reportMissingModuleSource]
except Exception:  # PyAudio can be missing or broken on Windows; runtime falls back to text mode.
    pyaudio = None  # type: ignore[assignment]
from google import genai  # type: ignore[reportMissingImports]
from google.genai import types  # type: ignore[reportMissingImports]

from app_config import get_app_config_value, load_app_config, normalize_agent_mode, normalize_voice_mode
from core.agent_runtime import AgentRuntime
from core.trace import TraceManager
from ui import JarvisUI
from memory.memory_manager import (
    delete_memory,
    format_memory_for_prompt,
    list_memory,
    load_memory,
    memory_status,
    remember_file_note,
    search_memory,
    update_memory,
)
from memory.memory_store import (
    format_relevant_memories_for_prompt,
    infer_memory_from_text,
    save_conversation_summary,
)
from actions.open_app import open_app
from actions.sys_info  import sys_info
from actions.calendar import get_calendar_events, add_calendar_event, delete_calendar_event
from actions.reminders import get_reminders, add_reminder, complete_reminder, delete_reminder
from actions.browser   import browser_control
from actions.browser_agent import (
    browser_click,
    browser_fill,
    browser_read_url,
    browser_research,
    browser_submit,
)
from actions.shell     import shell_run
from actions.whatsapp  import (
    find_whatsapp_contact,
    import_phone_book_from_vcf,
    list_whatsapp_contacts,
    send_whatsapp_message,
    save_whatsapp_contact,
)
from actions.media     import play_media
from actions.weather   import get_weather_summary
from actions.screen_vision import analyze_screen
from actions.youtube_stats import get_youtube_channel_report
from actions.local_web import handle_local_web_command
from actions.local_tasks import handle_local_task_command
from actions.local_memory import handle_local_memory_command
from actions.logging_utils import safe_log_preview
from actions.smoke import build_timeout_report, run_smoke_sequence
from actions.tts import get_speech_controller
from actions.voice_control import (
    SpeechMemory,
    VoiceGate,
    parse_voice_control,
    set_voice_mode as set_voice_mode_config,
    voice_experience_status as build_voice_experience_status,
)
from actions.wake_word import WakeWordDetector, load_wake_word_config
from actions.files import (
    find_files,
    list_folder,
    read_text_file,
    summarize_text_file,
    open_file,
    create_folder,
    create_text_file,
    write_text_file,
    append_text_file,
    move_file,
    delete_file,
)
from actions.clipboard import get_clipboard, set_clipboard, summarize_clipboard, get_selected_text, summarize_selected_text
from actions.desktop import active_window_info, list_windows, focus_window, send_hotkey_safe
from actions.web_research import web_search, open_and_summarize_url, research_web, browse_url, tavily_search, answer_research_question
from actions.calendar_integrations import (
    calendar_auth_status,
    connect_calendar_provider,
    disconnect_calendar_provider,
    list_calendars,
)
from actions.local_ai import (
    cloud_agent_config,
    internet_available,
    local_agent_config,
    local_agent_config_ready,
    local_ai_status,
    set_agent_mode,
    test_local_ai,
)
from actions.plugin_system import (
    call_plugin_tool,
    disable_plugin,
    discover_plugin_tools,
    enable_plugin,
    list_plugins,
    plugin_status,
    set_plugin_config,
)
from actions.audit import audit_status, get_audit_logger
from actions.safety import (
    PendingActionManager,
    classify_tool,
    guard_tool_call,
    is_approval_text,
    is_cancel_text,
    tool_risk_status,
)
from actions.task_system import (
    TaskScheduler,
    cancel_task,
    create_followup_task,
    disable_startup_tracking,
    enable_startup_tracking,
    list_tasks,
    notify_windows,
    run_task_now,
    startup_tracking_status,
)

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"

OFFLINE_BLOCKED_TOOLS = {
    "web_search",
    "open_and_summarize_url",
    "research_web",
    "answer_research_question",
    "tavily_search",
    "browse_url",
    "browser_control",
    "browser_read_url",
    "browser_research",
    "get_weather",
    "get_youtube_channel_report",
}


CONTROL_TOKEN_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# ── Model ───────────────────────────────────────────────────────────────────
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-latest"

# ── Audio ───────────────────────────────────────────────────────────────────
FORMAT           = pyaudio.paInt16 if pyaudio is not None else 8
CHANNELS         = 1
SEND_SAMPLE_RATE = 16000
RECV_SAMPLE_RATE = 24000
CHUNK_SIZE       = 1024

# ── Tool tanımları ──────────────────────────────────────────────────────────
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": "Windows/macOS uzerinde herhangi bir uygulamayi acar. Spotify, Chrome, Terminal, Explorer, VS Code vb.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Uygulama adı (örn. 'Spotify', 'Safari', 'Terminal')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "sys_info",
        "description": "Sistem bilgisi alır: pil durumu, CPU, RAM, disk, saat, tarih, ağ bağlantısı.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "battery | cpu | ram | disk | time | date | network | all"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_weather",
        "description": (
            "Anlik hava durumunu ozetler. Varsayilan konum Istanbul'dur. "
            "Kullanici hava durumunu, sicakligi veya yagmur durumunu sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": {
                    "type": "STRING",
                    "description": "Sehir veya konum. Bos birakilirsa Istanbul kullanilir."
                }
            }
        }
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Takvim etkinliklerini okur. Windows'ta secili Outlook/Google Calendar provider'ini kullanir. "
            "Bugun, yarin, siradaki etkinlik veya yaklasan ajandayi ozetler. "
            "Kullanici toplanti, takvim, ajanda, etkinlik veya gunluk programini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "today | tomorrow | next | agenda | week veya dogal dilde "
                        "'onumuzdeki 30 gun', '2 hafta', 'bu ay', 'gelecek ay'"
                    )
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum etkinlik sayisi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_calendar_event",
        "description": (
            "Takvime yeni etkinlik ekler. Windows'ta secili Outlook/Google Calendar provider'ini kullanir. "
            "Kullanici toplanti, randevu, takvime ekleme veya etkinlik olusturma isterse kullan. "
            "Baslangic tarihini gercek tarih/saat olarak ver; bitis verilmezse varsayilan sure kullanilir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Baslangic tarih/saat. ISO veya yyyy-MM-dd HH:mm formatinda."
                },
                "end_iso": {
                    "type": "STRING",
                    "description": "Bitis tarih/saat. Opsiyonel."
                },
                "location": {
                    "type": "STRING",
                    "description": "Etkinlik konumu. Opsiyonel."
                },
                "notes": {
                    "type": "STRING",
                    "description": "Etkinlik notlari. Opsiyonel."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Eklenecek takvim adi. Opsiyonel."
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "true ise tum gun etkinligi olusturur."
                }
            },
            "required": ["title", "start_iso"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": (
            "Takvimden etkinlik siler. Windows'ta secili Outlook/Google Calendar provider'ini kullanir. "
            "Kullanici bir toplantiyi, randevuyu veya takvim kaydini silmek istediginde kullan. "
            "Ayni ada birden fazla etkinlik varsa dogru kaydi bulmak icin baslangic tarihini gercek tarih/saat olarak ver."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Silinecek etkinlik basligi. Ornek: 'Disci Randevusu'"
                },
                "start_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ayni isimli birden fazla etkinligi ayirt etmek icin kullan."
                },
                "calendar_name": {
                    "type": "STRING",
                    "description": "Opsiyonel takvim adi"
                },
                "delete_all_matches": {
                    "type": "BOOLEAN",
                    "description": "true ise eslesen tum etkinlikleri siler"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "get_reminders",
        "description": (
            "Animsaticilar listesini okur. Windows'ta Outlook seciliyse Microsoft To Do, Google seciliyse Google Tasks kullanir. "
            "Bugunku, yaklasan, geciken veya tum acik animsaticilari ozetler. "
            "Kullanici hatirlatma, animsatici, reminder veya yapilacaklar listesini sordugunda kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "today | upcoming | overdue | all | next"
                },
                "limit": {
                    "type": "NUMBER",
                    "description": "Maksimum animsatici sayisi"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Istenirse belirli bir animsatici listesi adi"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_reminder",
        "description": (
            "Yeni bir animsatici ekler. Windows'ta Outlook seciliyse Microsoft To Do, Google seciliyse Google Tasks kullanir. "
            "Kullanici 'hatirlat', 'animsatici ekle', 'reminder kur' dediginde kullan. "
            "Goreli zaman ifadelerini bugunku tarih baglamina gore due_iso alanina ISO formatinda cevir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Animsatici basligi"
                },
                "due_iso": {
                    "type": "STRING",
                    "description": "Opsiyonel tarih/saat. Ornek: 2026-04-13T09:00 veya tum gun icin 2026-04-13"
                },
                "notes": {
                    "type": "STRING",
                    "description": "Opsiyonel not"
                },
                "list_name": {
                    "type": "STRING",
                    "description": "Opsiyonel animsatici listesi"
                },
                "priority": {
                    "type": "STRING",
                    "description": "low | medium | high"
                },
                "all_day": {
                    "type": "BOOLEAN",
                    "description": "Tum gun animsatici ise true"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "calendar_auth_status",
        "description": "Outlook/Google Calendar ve Tasks OAuth baglanti durumunu ozetler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "connect_calendar_provider",
        "description": (
            "Secili veya verilen Outlook/Google takvim saglayicisi icin OAuth baglantisini baslatir/tamamlar. "
            "Outlook icin mode=start device-code verir, mode=complete giris sonrasi token kaydeder. "
            "Google icin tarayicida installed-app OAuth akisini baslatir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "provider": {"type": "STRING", "description": "outlook | google. Bos ise ayarlardaki calendar_provider kullanilir."},
                "mode": {"type": "STRING", "description": "start | complete | test. Varsayilan start."}
            }
        }
    },
    {
        "name": "disconnect_calendar_provider",
        "description": "Outlook/Google Calendar OAuth token/cache dosyasini kaldirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "provider": {"type": "STRING", "description": "outlook | google. Bos ise ayarlardaki calendar_provider kullanilir."}
            }
        }
    },
    {
        "name": "list_calendars",
        "description": "Secili Outlook/Google hesabindaki takvimleri listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "provider": {"type": "STRING", "description": "outlook | google. Bos ise ayarlardaki calendar_provider kullanilir."}
            }
        }
    },
    {
        "name": "complete_reminder",
        "description": "Microsoft To Do veya Google Tasks uzerindeki bir animsaticiyi tamamlandi olarak isaretler; onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reminder_id": {"type": "STRING", "description": "Animsatici ID veya list_id:task_id"},
                "title": {"type": "STRING", "description": "ID yoksa eslestirilecek animsatici basligi"},
                "list_name": {"type": "STRING", "description": "Opsiyonel liste adi"}
            }
        }
    },
    {
        "name": "delete_reminder",
        "description": "Microsoft To Do veya Google Tasks uzerindeki bir animsaticiyi siler; onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reminder_id": {"type": "STRING", "description": "Animsatici ID veya list_id:task_id"},
                "title": {"type": "STRING", "description": "ID yoksa eslestirilecek animsatici basligi"},
                "list_name": {"type": "STRING", "description": "Opsiyonel liste adi"}
            }
        }
    },
    {
        "name": "browser_control",
        "description": "Tarayıcıda URL açar, Google'da arama yapar veya YouTube'da ilk sonucu doğrudan oynatır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "open_url | search | play_youtube"},
                "url":    {"type": "STRING", "description": "Açılacak URL (open_url için)"},
                "query":  {"type": "STRING", "description": "Arama sorgusu (search veya play_youtube için)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "browser_read_url",
        "description": (
            "Playwright BrowserAgent ile bir URL'yi acar, sayfa basligini/metnini/linklerini/form alanlarini okur "
            "ve soruyla ilgili alt linkleri takip edebilir. Kullanici 'tarayicida', 'gorunur' veya 'ekranda gez' derse visible=true kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Okunacak URL"},
                "question": {"type": "STRING", "description": "Sayfa hakkindaki soru veya takip edilecek konu"},
                "max_pages": {"type": "NUMBER", "description": "Ana sayfa dahil maksimum sayfa sayisi"},
                "visible": {"type": "BOOLEAN", "description": "true ise gorunur Chromium acilir ve BrowserAgent oturumu acik kalir"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_research",
        "description": (
            "Playwright BrowserAgent ile arama yapar, sonuclari sayfalar arasinda gezerek okur ve kaynakli Turkce ozet dondurur. "
            "'Tarayicida arastir' gibi komutlarda visible=true kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arastirma sorgusu"},
                "max_pages": {"type": "NUMBER", "description": "Okunacak maksimum kaynak sayisi"},
                "visible": {"type": "BOOLEAN", "description": "true ise gorunur Chromium acilir ve BrowserAgent oturumu acik kalir"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "browser_click",
        "description": "Aktif BrowserAgent sayfasinda selector veya gorunen metne tiklar. Riskli oldugu icin onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "selector_or_text": {"type": "STRING", "description": "Tiklanacak CSS selector veya gorunen metin"},
                "visible": {"type": "BOOLEAN", "description": "true kalmali; aktif gorunur BrowserAgent oturumunda calisir"}
            },
            "required": ["selector_or_text"]
        }
    },
    {
        "name": "browser_fill",
        "description": "Aktif BrowserAgent sayfasinda form alanini doldurur. Riskli oldugu icin onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "selector_or_label": {"type": "STRING", "description": "Doldurulacak CSS selector veya alan etiketi"},
                "value": {"type": "STRING", "description": "Alana yazilacak deger"},
                "visible": {"type": "BOOLEAN", "description": "true kalmali; aktif gorunur BrowserAgent oturumunda calisir"}
            },
            "required": ["selector_or_label", "value"]
        }
    },
    {
        "name": "browser_submit",
        "description": "Aktif BrowserAgent sayfasinda form gondermeyi dener. Riskli oldugu icin onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "selector_or_text": {"type": "STRING", "description": "Opsiyonel submit butonu selector/metni; bos ise Enter basilir"},
                "visible": {"type": "BOOLEAN", "description": "true kalmali; aktif gorunur BrowserAgent oturumunda calisir"}
            }
        }
    },
    {
        "name": "shell_run",
        "description": "Dar kapsamli, salt-okuma terminal yardimcisi. Sadece allowlist komutlari calisir; dosya degistiren veya belirsiz komutlar reddedilir ve onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Salt-okuma allowlist komutu. Ornek: dir ., type requirements.txt, git status, python --version"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "play_media",
        "description": (
            "YouTube, Spotify veya Apple Music/Music uygulamasında şarkı, müzik veya video açar. "
            "Kullanıcı belirli bir platform söylerse onu kullan. "
            "Belirtmezse uygun olanı dene. "
            "Kullanıcı 'çal', 'oynat', 'aç' diyorsa autoplay=true kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Şarkı, sanatçı, albüm veya video arama ifadesi"
                },
                "provider": {
                    "type": "STRING",
                    "description": "auto | youtube | spotify | apple_music"
                },
                "autoplay": {
                    "type": "BOOLEAN",
                    "description": "true ise mümkünse doğrudan oynatır"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_youtube_channel_report",
        "description": (
            "YouTube kanalinin public istatistiklerini ve son videolarin performansini raporlar. "
            "Kullanici kanal istatistiklerini, abone sayisini, son videolarini, buyume hizini "
            "veya YouTube analizini sordugunda kullan. Bu arac Studio yerine public YouTube Data API verisini kullanir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Dogal dilde analiz istegi. Ornek: "
                        "'YouTube istatistiklerim nasil', 'son videolarimi analiz et', "
                        "'kanal buyumemi ozetle'"
                    )
                },
                "handle": {
                    "type": "STRING",
                    "description": (
                        "Opsiyonel kanal handle'i, kanal linki veya kanal ID'si. "
                        "Bos birakilirsa ayarlardaki youtube_channel_handle kullanilir."
                    )
                },
                "video_limit": {
                    "type": "NUMBER",
                    "description": "Analize dahil edilecek son video sayisi. Varsayilan 6."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "analyze_screen",
        "description": (
            "Aktif pencerenin ekran goruntusunu alip Gemini vision ile analiz eder. "
            "Kullanici ekranda ne oldugunu, bir hatayi, gorunen metni, butonlari veya pencere icerigini sordugunda kullan. "
            "Bu surum yalnizca aktif pencereyi destekler."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Kullanicinin ekranla ilgili sorusu. Ornek: 'Bu hatayi oku', 'Ekranda ne var?'"
                },
                "target": {
                    "type": "STRING",
                    "description": "Su an sadece active_window desteklenir."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_folder",
        "description": "Guvenli sekilde bir klasorun icindeki dosya ve klasorleri listeler. Desktop, Downloads, Documents, home ve workspace gibi adlari anlayabilir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Klasor yolu veya adlandirilmis konum. Bos ise kullanici klasoru."},
                "limit": {"type": "NUMBER", "description": "Listelenecek maksimum oge sayisi"}
            }
        }
    },
    {
        "name": "find_files",
        "description": "Dosya veya klasor adina gore guvenli arama yapar. venv, .git, node_modules gibi agir klasorleri atlar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Aranacak dosya adi veya kalip. Ornek: '*.py', 'rapor'"},
                "path": {"type": "STRING", "description": "Aranacak kok klasor. Bos ise kullanici klasoru."},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_text_file",
        "description": "Metin dosyasini guvenli sekilde okur. Buyuk veya binary dosyalari okumaz.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Okunacak dosya yolu"},
                "max_chars": {"type": "NUMBER", "description": "Dondurulecek maksimum karakter sayisi"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "summarize_text_file",
        "description": "Metin dosyasini guvenli sekilde okur ve yerel bir ozet/onizleme cikarir. Binary veya cok buyuk dosyalari atlar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Ozetlenecek metin dosyasi yolu"},
                "max_chars": {"type": "NUMBER", "description": "Ozet icin okunacak maksimum karakter sayisi"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "open_file",
        "description": "Dosya veya klasoru varsayilan Windows/macOS uygulamasi ile acar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Acilacak dosya veya klasor yolu"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "get_clipboard",
        "description": "Panodaki metni okur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_chars": {"type": "NUMBER", "description": "Dondurulecek maksimum karakter sayisi"}
            }
        }
    },
    {
        "name": "set_clipboard",
        "description": "Verilen metni panoya kopyalar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "Panoya yazilacak metin"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "summarize_clipboard",
        "description": "Panodaki metin icin kisa yerel ozet/onizleme uretir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_chars": {"type": "NUMBER", "description": "Okunacak maksimum pano karakteri"}
            }
        }
    },
    {
        "name": "get_selected_text",
        "description": "Aktif uygulamada secili metni Ctrl+C ile okur; mumkunse onceki pano icerigini geri yukler. Secili metin cevirme/ozetleme isteklerinde kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_chars": {"type": "NUMBER", "description": "Dondurulecek maksimum karakter sayisi"},
                "restore_clipboard": {"type": "BOOLEAN", "description": "true ise okuma sonrasi eski pano icerigi geri yuklenir"}
            }
        }
    },
    {
        "name": "summarize_selected_text",
        "description": "Aktif uygulamada secili metni okur ve kisa yerel ozet/onizleme uretir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_chars": {"type": "NUMBER", "description": "Okunacak maksimum secili metin karakteri"}
            }
        }
    },
    {
        "name": "active_window_info",
        "description": "Windows'ta aktif pencerenin baslik, uygulama, PID ve konum bilgisini verir.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "list_windows",
        "description": "Windows'ta gorunur pencereleri baslik, uygulama, HWND ve konum bilgisiyle listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Opsiyonel baslik veya uygulama filtresi"},
                "limit": {"type": "NUMBER", "description": "Maksimum pencere sayisi"}
            }
        }
    },
    {
        "name": "focus_window",
        "description": "Baslik veya uygulama adina gore gorunur bir pencereyi one getirir ve odaklar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Pencere basligi veya uygulama adi. Ornek: Chrome, Notepad, Spotify"},
                "exact": {"type": "BOOLEAN", "description": "true ise tam baslik/uygulama adi eslesmesi ister"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "send_hotkey_safe",
        "description": "Aktif pencereye guvenli listedeki basit kisayolu gonderir. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "hotkey": {"type": "STRING", "description": "Ornek: ctrl+c, ctrl+v, alt+tab, win+d"},
                "delay_seconds": {"type": "NUMBER", "description": "Gondermeden once beklenecek saniye"}
            },
            "required": ["hotkey"]
        }
    },
    {
        "name": "web_search",
        "description": "Sadece tarayicida web aramasi acar. Haber, guncel bilgi, oku veya arastir isteklerinde bunun yerine research_web kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arama sorgusu"},
                "open_results": {"type": "BOOLEAN", "description": "true ise tarayicida Google aramasini acar"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "open_and_summarize_url",
        "description": "URL'yi tarayicida acar, mumkunse sayfa metnini cekip kisa yerel ozet/onizleme dondurur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Acilacak ve ozetlenecek URL"},
                "max_chars": {"type": "NUMBER", "description": "Ozet icin kullanilacak maksimum karakter"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "research_web",
        "description": "Web'de dengeli arastirma yapar, Tavily/Google News/Bing/DuckDuckGo fallbacks ile sonuclari bulur, sayfalari okur ve Kisa cevap/Detaylar/Kaynaklar formatinda dondurur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arastirma sorgusu"},
                "max_pages": {"type": "NUMBER", "description": "Okunacak maksimum sayfa sayisi. Varsayilan 5."},
                "open_browser": {"type": "BOOLEAN", "description": "true ise gorunur tarayici da acmayi dener"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "answer_research_question",
        "description": "Herhangi bir konuda kisisel asistan arastirmasi yapar; kaynaklari okur, kisa cevap/detay/kaynak formatinda Turkce yanitlar. 'Oku' veya 'sesli oku' isteklerinde bunu tercih et.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arastirilacak soru veya konu"},
                "depth": {"type": "STRING", "description": "quick | balanced | deep. Varsayilan balanced."},
                "speak": {"type": "BOOLEAN", "description": "Kullanici sesli okuma istediyse true"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "tavily_search",
        "description": "Tavily API ile web/haber arastirmasi yapar, kaynakli cevap ve sayfa icerikleri dondurur. Tavily key varsa haber ve guncel arastirmalarda bunu tercih et.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Arastirma sorgusu"},
                "max_results": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
                "search_depth": {"type": "STRING", "description": "basic | advanced"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "browse_url",
        "description": "Bir URL'yi okur, sayfa metnini/linkleri cikarir ve gerekirse soruyla ilgili alt sayfalara gecerek ozetler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Gezilecek URL"},
                "question": {"type": "STRING", "description": "Sayfa hakkindaki soru veya aranan konu"},
                "max_pages": {"type": "NUMBER", "description": "Ana sayfa dahil maksimum sayfa sayisi"},
                "open_browser": {"type": "BOOLEAN", "description": "true ise gorunur tarayici da acmayi dener"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "create_folder",
        "description": "Yeni klasor olusturur. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Olusturulacak klasor yolu"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "create_text_file",
        "description": "Yeni metin dosyasi olusturur. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Olusturulacak dosya yolu"},
                "content": {"type": "STRING", "description": "Dosya icerigi"},
                "overwrite": {"type": "BOOLEAN", "description": "true ise var olan dosyanin uzerine yazar"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_text_file",
        "description": "Metin dosyasina yazar veya uzerine yazar. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Yazilacak dosya yolu"},
                "content": {"type": "STRING", "description": "Yazilacak icerik"},
                "overwrite": {"type": "BOOLEAN", "description": "true ise var olan dosyanin uzerine yazar"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "append_text_file",
        "description": "Metin dosyasinin sonuna icerik ekler. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Eklenecek dosya yolu"},
                "content": {"type": "STRING", "description": "Eklenecek icerik"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "move_file",
        "description": "Dosya veya klasor tasir/yeniden adlandirir. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_path": {"type": "STRING", "description": "Kaynak yol"},
                "destination_path": {"type": "STRING", "description": "Hedef yol"},
                "overwrite": {"type": "BOOLEAN", "description": "true ise hedef varsa uzerine yazar"}
            },
            "required": ["source_path", "destination_path"]
        }
    },
    {
        "name": "delete_file",
        "description": "Dosya veya klasor siler. Onay gerektirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Silinecek dosya veya klasor yolu"},
                "recursive": {"type": "BOOLEAN", "description": "true ise klasor icerigiyle silinir"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "pending_action_status",
        "description": "Onay bekleyen riskli islem olup olmadigini soyler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "approve_pending_action",
        "description": "Kullanicinin acik onayi sonrasi bekleyen islemi calistirir.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "cancel_pending_action",
        "description": "Onay bekleyen islemi iptal eder.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "audit_status",
        "description": "Son guvenlik/audit olaylarini listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {"type": "NUMBER", "description": "Maksimum audit olayi sayisi"}
            }
        }
    },
    {
        "name": "tool_risk_status",
        "description": "Bir tool'un veya tum tool registry'sinin risk sinifi ve onay/audit politikasini gosterir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tool_name": {"type": "STRING", "description": "Opsiyonel tool adi"}
            }
        }
    },
    {
        "name": "local_ai_status",
        "description": "Cloud/local/hybrid ajan modu, local endpoint, Foundry Local ve internet durumunu ozetler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "test_local_ai",
        "description": "Yerel AI endpointini veya Microsoft Foundry Local otomatik modunu kisa chat completion ile test eder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING", "description": "Opsiyonel test promptu"}
            }
        }
    },
    {
        "name": "set_agent_mode",
        "description": "JARVIS yazili ajan model modunu cloud, local veya hybrid olarak ayarlar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "cloud | local | hybrid"}
            },
            "required": ["mode"]
        }
    },
    {
        "name": "voice_experience_status",
        "description": "Mikrofon, text mode, PTT, wake word, cikis sesi ve ses modu durumunu ozetler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "set_voice_mode",
        "description": "JARVIS ses giris modunu ayarlar: ptt_wake, ptt_only, wake_only veya live_always.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "ptt_wake | ptt_only | wake_only | live_always"}
            },
            "required": ["mode"]
        }
    },
    {
        "name": "create_followup_task",
        "description": (
            "Kalici takip veya tek seferlik kontrol gorevi olusturur. "
            "'haber cikarsa bildir', 'bunu takip et', 'yarin kontrol et' gibi isteklerde kullan. "
            "Periyodik web_watch gorevleri ilk calismada baseline kaydeder, sonraki degisiklikte bildirim uretir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Kisa gorev basligi"},
                "task_type": {"type": "STRING", "description": "web_watch | one_shot_check"},
                "query": {"type": "STRING", "description": "Takip veya kontrol edilecek arastirma sorgusu"},
                "url": {"type": "STRING", "description": "Opsiyonel takip edilecek URL"},
                "schedule_kind": {"type": "STRING", "description": "interval | once"},
                "interval_minutes": {"type": "NUMBER", "description": "Periyodik gorev araligi. Varsayilan 180 dk."},
                "run_at": {"type": "STRING", "description": "Tek seferlik gorev icin ISO tarih/saat"},
                "baseline_now": {"type": "BOOLEAN", "description": "true ise ilk calisma baseline kaydeder"}
            }
        }
    },
    {
        "name": "list_tasks",
        "description": "Kalici takip/gorev listesini verir. Aktif takipleri sorunca kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "status_filter": {"type": "STRING", "description": "active | pending | running | done | failed | cancelled"},
                "limit": {"type": "NUMBER", "description": "Maksimum gorev sayisi"}
            }
        }
    },
    {
        "name": "cancel_task",
        "description": "Kalici takip veya gorevi iptal eder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "NUMBER", "description": "Iptal edilecek gorev ID'si"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "run_task_now",
        "description": "Secili takip/gorevi hemen calistirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "NUMBER", "description": "Calistirilacak gorev ID'si"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "startup_tracking_status",
        "description": "Windows baslangicinda JARVIS takip sisteminin acik/kapali durumunu soyler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "enable_startup_tracking",
        "description": "Windows baslangicinda JARVIS takip sistemini acmak icin onay bekleyen islem olusturur.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "disable_startup_tracking",
        "description": "Windows baslangicinda JARVIS takip sistemini kapatmak icin onay bekleyen islem olusturur.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "save_memory",
        "description": "Kullanıcı hakkında önemli bilgiyi kalıcı belleğe kaydeder. İsim, tercihler, projeler vb. duyunca sessizce çağır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "identity | preferences | projects | notes"
                },
                "key":   {"type": "STRING", "description": "Kısa anahtar (örn. 'name')"},
                "value": {"type": "STRING", "description": "Değer (İngilizce)"}
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "delete_memory",
        "description": (
            "Kalici hafizadaki bir kaydi siler. "
            "Kullanici 'bunu hafizandan kaldir', 'unut', 'sil' gibi bir sey derse kullan. "
            "Mumkunse category ve key ile sil; emin degilsen match_text ile ilgili kaydi bulup kaldir."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": "Kaydin kategorisi. Ornek: notes | identity | preferences | projects"
                },
                "key": {
                    "type": "STRING",
                    "description": "Silinecek anahtar. Ornek: claude_limit_refresh"
                },
                "match_text": {
                    "type": "STRING",
                    "description": "Kaydi bulmak icin kullanilacak dogal dil parcasi. Ornek: 'claude ai limit yenilenmesi'"
                }
            }
        }
    },
    {
        "name": "search_memory",
        "description": "SQLite hafiza katmaninda gecmis konusma, karar, tercih, proje/dosya notu veya gorev ozetlerini arar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Aranacak konu, tercih, karar veya gecmis konusma parcasi"},
                "kind": {"type": "STRING", "description": "Opsiyonel tur: profile | preference | conversation_summary | decision | project_note | file_note | task_summary"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_memory",
        "description": "SQLite hafiza kayitlarini tur/son guncelleme sirasiyla listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "description": "Opsiyonel hafiza turu filtresi"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"}
            }
        }
    },
    {
        "name": "memory_status",
        "description": "JSON profil hafizasi ve SQLite hafiza indeksinin durumunu ozetler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "remember_file_note",
        "description": "Kullanici acikca isterse bir dosya/proje hakkinda ozet notu hafizaya kaydeder. Ham dosya icerigi yerine ozet/metadata saklar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Not alinacak dosya veya klasor yolu"},
                "summary": {"type": "STRING", "description": "Kaydedilecek kisa ozet veya not"},
                "tags": {"type": "STRING", "description": "Virgulle ayrilmis etiketler"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "send_whatsapp_message",
        "description": (
            "WhatsApp Desktop veya WhatsApp Web üzerinden mesaj taslağı açar veya mesajı gönderir. "
            "Kişi adı veya telefon numarasıyla çalışabilir. "
            "Telefon numarası verilmemişse kişi adını önce kayıtlı WhatsApp kişileri ve içe aktarılan telefon rehberinde ara. "
            "Kullanıcı 'gönder', 'yolla', 'ile', 'hemen gönder' gibi açık bir gönderme niyeti söylüyorsa "
            "send_now=true kullan; sistem kullanici onayi bekletir. "
            "Yalnızca 'hazırla', 'taslak aç', 'yaz ama gönderme' diyorsa send_now=false kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "recipient_name": {
                    "type": "STRING",
                    "description": "Kişi adı. Örn: 'Anne', 'Ahmet', 'Ece'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "message": {
                    "type": "STRING",
                    "description": "Gönderilecek mesaj içeriği"
                },
                "app_target": {
                    "type": "STRING",
                    "description": "desktop | web | auto. Varsayılan auto, tercihen desktop."
                },
                "send_now": {
                    "type": "BOOLEAN",
                    "description": "true ise sohbet açıldıktan sonra mesajı otomatik gönderir"
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "find_whatsapp_contact",
        "description": "Kayitli WhatsApp kisileri ve ice aktarilan telefon rehberinde isim, takma ad veya telefonla kisi arar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Aranacak kisi adi, takma ad veya telefon"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_whatsapp_contacts",
        "description": "Kayitli WhatsApp kisilerini ve ice aktarilan rehber kisilerini listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
                "source_filter": {"type": "STRING", "description": "whatsapp veya phone_book gibi kaynak filtresi"}
            }
        }
    },
    {
        "name": "import_phone_book_from_vcf",
        "description": "Bir .vcf rehber dosyasini WhatsApp kisi aramasi icin memory/phone_book.json icine aktarir; bulk import oldugu icin onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "vcf_path": {"type": "STRING", "description": "Iceri aktarilacak .vcf dosya yolu"}
            },
            "required": ["vcf_path"]
        }
    },
    {
        "name": "save_whatsapp_contact",
        "description": (
            "Sık kullanılan bir WhatsApp kişisini adı ve telefon numarasıyla kalıcı belleğe kaydeder. "
            "Kullanıcı bir kişiyi 'annem', 'Ahmet', 'iş ortağım' gibi tekrar kullanılacak şekilde tanımladığında kullan."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "display_name": {
                    "type": "STRING",
                    "description": "Kaydedilecek kişi adı. Örn: 'Annem', 'Ahmet'"
                },
                "phone_number": {
                    "type": "STRING",
                    "description": "Uluslararası telefon numarası. Örn: +905551112233"
                },
                "aliases": {
                    "type": "STRING",
                    "description": "Virgülle ayrılmış alternatif hitaplar. Örn: 'anne, annem, mom'"
                }
            },
            "required": ["display_name", "phone_number"]
        }
    },
    {
        "name": "list_plugins",
        "description": "Kurulu JARVIS plugin manifestlerini, acik/kapali durumlarini, izinlerini ve risklerini listeler.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "plugin_status",
        "description": "Belirli bir plugin veya tum plugin registry durumu hakkinda detay verir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Opsiyonel plugin id. Ornek: github, google, filesystem"}
            }
        }
    },
    {
        "name": "enable_plugin",
        "description": "Kapali bir plugin'i acmak icin onay bekleyen islem olusturur. MCP baglantisi config verilmeden calismaz.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Acilacak plugin id"}
            },
            "required": ["plugin_id"]
        }
    },
    {
        "name": "disable_plugin",
        "description": "Bir plugin'i kapatir ve sonraki MCP tool cagrilarini engeller.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Kapatilacak plugin id"}
            },
            "required": ["plugin_id"]
        }
    },
    {
        "name": "set_plugin_config",
        "description": "Plugin MCP/config alanlarini kaydeder. Secret alanlar audit/trace'te maskelenir ve onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Config kaydedilecek plugin id"},
                "config_json": {"type": "STRING", "description": "JSON config. Ornek: {\"transport\":\"stdio\",\"command\":\"node\",\"args\":[\"server.js\"]}"},
                "merge": {"type": "BOOLEAN", "description": "true ise mevcut config ile birlestirir"}
            },
            "required": ["plugin_id", "config_json"]
        }
    },
    {
        "name": "discover_plugin_tools",
        "description": "Acik plugin icin MCP list_tools calistirir veya manifest tool'larini okur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Tool kesfi yapilacak plugin id"}
            },
            "required": ["plugin_id"]
        }
    },
    {
        "name": "call_plugin_tool",
        "description": (
            "Acik ve kesfedilmis bir plugin/MCP tool'unu generic gateway uzerinden cagirir. "
            "Plugin kapaliysa, tool registry disindaysa veya riskliyse safety/onay modeli devreye girer."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Plugin id"},
                "tool_name": {"type": "STRING", "description": "Kesfedilmis MCP tool adi"},
                "arguments_json": {"type": "STRING", "description": "Tool argumanlari JSON object olarak"}
            },
            "required": ["plugin_id", "tool_name"]
        }
    }
]


def get_api_key() -> str:
    return str(get_app_config_value("gemini_api_key", "") or "")


def load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Sen JARVIS'sin — Windows/macOS uzerinde calisan kisisel AI asistani. "
            "Türkçe konuş. Kısa ve net yanıtlar ver. "
            "Araçları kullanarak görevleri tamamla, asla taklit etme."
        )


class JarvisLive:
    def __init__(self, ui: JarvisUI, start_task_scheduler: bool = True):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._audio_input_available = True
        self._audio_output_available = True
        self._audio_notice_sent = set()
        self._text_mode = False
        self._pyaudio = None
        self._pyaudio_lock = threading.Lock()
        self.speech = get_speech_controller()
        self.speech_memory = SpeechMemory()
        cfg = load_app_config()
        self.voice_gate = VoiceGate(mode=normalize_voice_mode(cfg.get("voice_input_mode", "ptt_wake")))
        self._wake_detector = WakeWordDetector(load_wake_word_config(cfg))
        self.audit_logger = get_audit_logger()
        self.pending_actions = PendingActionManager()
        self.trace = TraceManager(
            BASE_DIR / "memory" / "traces",
            debug_sink=lambda message, level="INFO": self.ui.write_debug(message, level=level),
        )
        self.agent_runtime = AgentRuntime(TOOL_DECLARATIONS, trace_manager=self.trace)
        self.task_scheduler = TaskScheduler(notify_callback=self._notify_task_result)
        if start_task_scheduler:
            self.task_scheduler.start()
        self._voice_run_id = ""

        self.ui.on_text_command  = self._on_text_command
        self.ui.on_pause_toggle  = self._on_pause_toggle
        self.ui.on_effects_state_change = self._on_effects_state_change
        self.ui.on_ptt_start = self._on_ptt_start
        self.ui.on_ptt_stop = self._on_ptt_stop
        self.ui.on_stop_command = self._on_stop_command
        self.ui.on_wake_toggle = self._on_wake_toggle
        self._paused             = False
        self._sync_voice_ui()

    def _on_pause_toggle(self, paused: bool):
        self._paused = paused

    def _on_effects_state_change(self, enabled: bool):
        pass

    def _sync_voice_ui(self):
        status = self._wake_detector.status() if self._wake_detector else ""
        if hasattr(self.ui, "set_text_mode"):
            self.ui.set_text_mode(self._text_mode)
        if hasattr(self.ui, "set_ptt_active"):
            self.ui.set_ptt_active(bool(self.voice_gate.ptt_active))
        if hasattr(self.ui, "set_wake_status"):
            self.ui.set_wake_status(
                bool(self._wake_detector and self._wake_detector.ready),
                status,
            )

    def _refresh_wake_detector(self):
        try:
            if self._wake_detector:
                self._wake_detector.close()
        except Exception:
            pass
        cfg = load_app_config()
        self.voice_gate.set_mode(cfg.get("voice_input_mode", "ptt_wake"))
        self._wake_detector = WakeWordDetector(load_wake_word_config(cfg))
        self._sync_voice_ui()
        return self._wake_detector.status()

    def _on_ptt_start(self):
        self.voice_gate.start_ptt()
        self._sync_voice_ui()
        self.ui.mark_user_activity(True)
        if self._is_speaking or self.speech.is_speaking:
            self._interrupt_audio_from_thread()

    def _on_ptt_stop(self):
        self.voice_gate.stop_ptt()
        self._sync_voice_ui()
        if self._loop and self.session:
            asyncio.run_coroutine_threadsafe(self._send_audio_stream_end(), self._loop)

    def _on_wake_toggle(self, enabled: bool):
        from app_config import save_app_config

        save_app_config({"wake_word_enabled": bool(enabled)})
        status = self._refresh_wake_detector()
        self.ui.write_log(f"SYS: Wake word {'acildi' if enabled else 'kapatildi'}: {status}")

    def _on_stop_command(self):
        self._interrupt_audio_from_thread()

    def _interrupt_audio_from_thread(self):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._interrupt_audio(), self._loop)
        else:
            self.speech.stop()
            self.speech_memory.mark_stopped()
            self.set_speaking(False)

    async def _send_audio_stream_end(self):
        try:
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
        except Exception:
            pass

    def _arm_wake_capture(self):
        cfg = load_app_config()
        seconds = int(cfg.get("wake_capture_seconds", 8) or 8)
        self.voice_gate.arm_wake(seconds)
        self._sync_voice_ui()
        self.ui.mark_user_activity(True)
        if self._is_speaking or self.speech.is_speaking:
            self._interrupt_audio_from_thread()

    def _handle_voice_control_command(self, text: str, *, source: str = "text") -> bool:
        parsed = parse_voice_control(text)
        if not parsed.matched:
            return False
        action = parsed.action
        if action == "stop":
            self._interrupt_audio_from_thread()
            self.ui.write_log("SYS: Ses kesildi.")
            self.ui.set_state("LISTENING")
            return True
        if action == "resume":
            if self._paused:
                self._paused = False
                self.ui.paused = False
                if hasattr(self.ui, "_draw_pause_button"):
                    self.ui.root.after(0, self.ui._draw_pause_button)
                self.ui.write_log("SYS: JARVIS devam ediyor...")
            text_to_speak = self.speech_memory.resume()
            if text_to_speak and not self.ui.muted:
                self._speak_response(text_to_speak)
            else:
                self.ui.set_state("LISTENING")
            return True
        if action == "repeat":
            text_to_speak = self.speech_memory.repeat()
            if text_to_speak and not self.ui.muted:
                self._speak_response(text_to_speak)
            else:
                self.ui.write_log("SYS: Tekrar okunacak son yanit yok.")
                self.ui.set_state("LISTENING")
            return True
        if action == "shorten":
            short = self.speech_memory.shorten()
            if not short:
                self.ui.write_log("SYS: Kisaltacak son yanit yok.")
                self.ui.set_state("LISTENING")
                return True
            self.ui.write_log(f"JARVIS: {short}")
            if not self.ui.muted:
                self._speak_response(short)
            else:
                self.ui.set_state("LISTENING")
            return True
        return False

    def _speak_response(self, text: str, on_done=None) -> bool:
        spoken = str(text or "").strip()
        if not spoken:
            if on_done:
                on_done()
            return False
        self.speech_memory.set(spoken)
        self.set_speaking(True)

        def done():
            self.speech_memory.advance_by_text(spoken)
            self.set_speaking(False)
            if on_done:
                on_done()

        self.speech.speak(spoken, on_done=done, blocking=False)
        return True

    def _guarded_tool_action(self, tool_name: str, args: dict, runner, summary: str = "") -> str:
        run_id = self.agent_runtime.current_run_id or self.trace.current_run_id
        return guard_tool_call(
            tool_name,
            args or {},
            runner,
            self.pending_actions,
            self.audit_logger,
            run_id=run_id,
            summary_override=summary,
        )

    def _notify_task_result(self, title: str, body: str):
        summary = self._speech_excerpt(body, limit=700) or str(body or "").strip()
        message = f"Takip bildirimi: {title}\n{summary}"
        self.ui.write_log(f"SYS: {message}")
        toast_result = notify_windows(title, summary)
        if "gonderilemedi" in toast_result.casefold():
            self.ui.write_debug(toast_result, level="WARN")
        else:
            self.ui.write_debug(toast_result, level="INFO")
        if not self.ui.muted and summary:
            self._speak_response(summary)

    def _start_user_run(self, text: str, source: str = "text") -> str:
        run_id = self.trace.start_run(text, source=source)
        self.agent_runtime.set_current_run(run_id)
        return run_id

    def _auto_learn_from_user_text(self, text: str, run_id: str):
        try:
            learned = infer_memory_from_text(text, source_id=run_id)
            if learned.get("saved"):
                item = learned.get("item") or {}
                self.trace.log_event(run_id, "auto_memory_saved", {"id": item.get("id"), "kind": item.get("kind"), "title": item.get("title")})
                self.ui.write_debug(f"Hafiza ogrenildi: #{item.get('id')} {item.get('title')}", level="INFO")
        except Exception as exc:
            self.trace.log_event(run_id, "auto_memory_skipped", {"error": f"{type(exc).__name__}: {exc}"})

    @staticmethod
    def _is_trace_explain_request(text: str) -> bool:
        folded = (text or "").casefold()
        return any(
            marker in folded
            for marker in (
                "neden bulamadin",
                "neden bulamadın",
                "niye bulamadin",
                "niye bulamadın",
                "ne denedin",
                "son arastirma logu",
                "son araştırma logu",
                "trace durumu",
                "debug durumu",
            )
        )

    def _focus_ui_section_for_tool(self, tool_name: str, args: dict):
        if tool_name == "sys_info":
            query = str(args.get("query", "")).strip().lower()
            if query in {"time", "saat", "zaman", "date", "tarih"}:
                self.ui.focus_panel("time", duration_ms=5200)
            else:
                self.ui.focus_panel("system", duration_ms=5200)
        elif tool_name == "get_weather":
            self.ui.focus_panel("weather", duration_ms=5600)

    def _audio_notice(self, key: str, message: str, level: str = "WARN"):
        if key in self._audio_notice_sent:
            return
        self._audio_notice_sent.add(key)
        self.ui.write_log(f"SYS: {message}")
        self.ui.write_debug(message, level=level)

    @staticmethod
    def _wants_spoken_reading(text: str) -> bool:
        normalized = unicodedata.normalize("NFKD", text or "")
        folded = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold().replace("ı", "i")
        return any(marker in folded for marker in (" oku", "sesli", "sesli oku", "okur musun", "okuyabilir misin"))

    @staticmethod
    def _speech_excerpt(text: str, limit: int = 900) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        spoken: list[str] = []
        capture_answer = False
        for line in lines:
            folded = line.casefold()
            if folded.startswith(("kaynak:", "icerik:", "içerik:", "arama kaynagi:", "arama kaynağı:")):
                continue
            if folded.startswith("tavily arastirma"):
                spoken.append(line.replace("Tavily arastirma:", "Araştırma:"))
                continue
            if folded.startswith("kisa cevap"):
                capture_answer = True
                continue
            if re.match(r"^\[\d+\]", line):
                spoken.append(line)
                capture_answer = False
                continue
            if capture_answer or len(spoken) < 5:
                spoken.append(line)
            if len(" ".join(spoken)) >= limit:
                break
        value = " ".join(spoken) if spoken else raw
        value = re.sub(r"https?://\S+", "", value)
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) > limit:
            value = value[:limit].rsplit(" ", 1)[0] + "..."
        return value

    def _speak_if_requested(self, user_text: str, response_text: str) -> bool:
        if not self._wants_spoken_reading(user_text) or self.ui.muted:
            return False
        spoken = self._speech_excerpt(response_text)
        if not spoken:
            return False
        self._speak_response(spoken)
        return True

    def _on_text_command(self, text: str):
        self.ui.write_log(f"Siz: {text}")
        run_id = self._start_user_run(text, source="text")
        folded = (text or "").strip().casefold()
        if self._handle_voice_control_command(text, source="text"):
            self.trace.log_event(run_id, "voice_control_command", {"text": text})
            return
        if self.pending_actions.has_pending():
            if is_approval_text(text):
                result = self.pending_actions.approve()
                self.trace.log_event(run_id, "pending_action_approved", {"result": result})
                self.ui.write_log(f"SYS: {result}")
                self.ui.set_state("LISTENING")
                return
            if is_cancel_text(text):
                result = self.pending_actions.cancel()
                self.trace.log_event(run_id, "pending_action_cancelled", {"result": result})
                self.ui.write_log(f"SYS: {result}")
                self.ui.set_state("LISTENING")
                return
            if "onay bekleyen" in folded or "ne bekliyor" in folded or "bekleyen islem" in folded:
                result = self.pending_actions.describe()
                self.trace.log_event(run_id, "pending_action_status", {"result": result})
                self.ui.write_log(f"SYS: {result}")
                self.ui.set_state("LISTENING")
                return
        self._auto_learn_from_user_text(text, run_id)
        if self._is_trace_explain_request(text):
            result = self.trace.debug_snapshot() if "trace" in folded or "debug" in folded else self.trace.explain_last_research()
            self.trace.log_event(run_id, "trace_explain", {"result": result})
            self.ui.write_log(f"SYS: {result}")
            self.ui.set_state("LISTENING")
            return
        local_memory_result = handle_local_memory_command(text)
        if local_memory_result:
            self.trace.log_event(run_id, "local_memory_command", {"text": text, "result": local_memory_result})
            self.ui.write_log(f"SYS: {local_memory_result}")
            self.ui.set_state("LISTENING")
            return
        local_task_result = handle_local_task_command(text, self.trace)
        if local_task_result:
            self.trace.log_event(run_id, "local_task_command", {"text": text, "result": local_task_result})
            self.ui.write_log(f"SYS: {local_task_result}")
            self.ui.set_state("LISTENING")
            return
        local_result = self.agent_runtime.execute_local_command(text, handle_local_web_command)
        if local_result:
            self.ui.write_log(f"SYS: {local_result}")
            if not self._speak_if_requested(text, local_result):
                self.ui.set_state("LISTENING")
            return
        if self._should_use_text_agent(text):
            self.ui.set_state("THINKING")
            self._schedule_text_agent(text, run_id)
            return
        if self._paused:
            self.ui.write_log("SYS: JARVIS duraklatilmis durumda. Yazili ajan icin Ninerouter ayarlarini girebilir veya devam etmek icin pause'u kapatabilirsin.")
            return
        if not self._loop or not self.session:
            self.ui.write_log("ERR: JARVIS baglantisi henuz hazir degil. Ninerouter ayari varsa yazili ajan modu calisir; yoksa Google'da ... ara yazabilirsin.")
            return
        self._send_text_to_gemini_live(text)

    def _send_text_to_gemini_live(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _text_agent_route(self, text: str):
        cfg = load_app_config()
        cloud_ready = not cloud_agent_config(cfg).missing_fields()
        local_ready = local_agent_config_ready(cfg)
        mode = normalize_agent_mode(cfg.get("agent_mode", "hybrid"))
        return self.agent_runtime.choose_model_route(
            text,
            mode,
            cloud_ready=cloud_ready,
            local_ready=local_ready,
        )

    def _should_use_text_agent(self, text: str = "") -> bool:
        route = self._text_agent_route(text)
        return bool(route.primary)

    def _schedule_text_agent(self, text: str, run_id: str):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._handle_text_agent(text, run_id), self._loop)
            return

        def runner():
            asyncio.run(self._handle_text_agent(text, run_id))

        threading.Thread(target=runner, daemon=True).start()

    async def _handle_text_agent(self, text: str, run_id: str):
        self.agent_runtime.set_current_run(run_id)
        cfg = load_app_config()
        route = self._text_agent_route(text)
        self.trace.log_event(
            run_id,
            "model_route",
            {"primary": route.primary, "fallback": route.fallback, "reason": route.reason},
        )
        self.ui.write_debug(
            f"Model route: {route.primary or '-'} fallback={route.fallback or '-'} ({route.reason})",
            level="INFO",
        )
        result = ""
        for route_name in route.order():
            try:
                provider_config = (
                    local_agent_config(cfg, start_foundry=True)
                    if route_name == "local"
                    else cloud_agent_config(cfg)
                )
            except Exception as exc:
                result = f"{route_name} model hazirlanamadi: {type(exc).__name__}: {exc}"
                self.trace.log_error(run_id, f"{route_name}_model_prepare", result)
                continue
            self.trace.log_event(
                run_id,
                "model_route_attempt",
                {"route": route_name, "provider": provider_config.provider_name},
            )
            result = await self.agent_runtime.run_text_agent(
                provider_config,
                self._build_system_instruction(text),
                text,
                TOOL_DECLARATIONS,
                self._execute_tool_for_text_agent,
                run_id=run_id,
            )
            if not self._result_looks_like_error(result):
                break
            if route_name == route.primary and route.fallback:
                self.ui.write_debug(f"{route_name} model sonucu yetersiz; fallback deneniyor.", level="WARN")
                self.trace.log_event(run_id, "model_route_fallback", {"from": route_name, "to": route.fallback, "result": result})
                continue
            break
        if not result:
            result = "Yazili ajan modeli hazir degil. " + local_ai_status()
        self.trace.log_event(run_id, "text_agent_result", {"result": result})
        self.ui.write_log(f"JARVIS: {result}")
        if result and not self._result_looks_like_error(result):
            self.speech_memory.set(self._speech_excerpt(result) or result)
        if not self._result_looks_like_error(result):
            saved_summary = save_conversation_summary(text, result, run_id)
            if saved_summary and not saved_summary.get("blocked") and saved_summary.get("id"):
                self.trace.log_event(run_id, "conversation_summary_saved", {"id": saved_summary.get("id")})
        speaking = self._speak_if_requested(text, result)
        if self._result_looks_like_error(result):
            self.ui.set_state("ERROR")
        elif not speaking:
            self.ui.set_state("LISTENING")

    async def _execute_tool_for_text_agent(self, name: str, args: dict) -> str:
        fc = SimpleNamespace(name=name, args=args or {}, id=f"text-{name}")
        response = await self._execute_tool_direct(fc)
        try:
            return str(response.response.get("result", ""))
        except Exception:
            return str(response)

    async def _interrupt_audio(self):
        try:
            self.speech.stop()
            self.speech_memory.mark_stopped()
            if self.audio_in_queue:
                while not self.audio_in_queue.empty():
                    try:
                        self.audio_in_queue.get_nowait()
                    except Exception:
                        break
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)
            self.set_speaking(False)
            self.ui.mark_user_activity(False)
        except Exception:
            pass


    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        else:
            if self.pending_actions.has_pending():
                self.ui.set_state("WAITING_APPROVAL")
            else:
                self.ui.set_state("LISTENING")

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.ui.write_debug(f"{tool_name}: {short}", level="ERROR")
        self.ui.set_state("ERROR")

    @staticmethod
    def _result_looks_like_error(result) -> bool:
        text = str(result or "").strip().lower()
        if not text:
            return False
        error_markers = (
            "hata",
            "error",
            "alinamadi",
            "alınamadı",
            "bulunamadi",
            "bulunamadı",
            "acilamadi",
            "açılamadı",
            "tamamlanamadi",
            "tamamlanamadı",
            "gecersiz",
            "geçersiz",
            "izin gerekiyor",
            "izin gerekli",
            "basarisiz",
            "başarısız",
            "eksik",
            "baglanti",
            "bağlantı",
            "gerekli.",
        )
        return any(marker in text for marker in error_markers)

    @staticmethod
    def _format_exception_summary(exc: Exception) -> str:
        children = getattr(exc, "exceptions", None)
        if children:
            return " | ".join(
                f"{type(child).__name__}: {child}" for child in children[:3]
            )
        return f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _should_play_success_sfx(tool_name: str, args: dict, result) -> bool:
        action_tools = {
            "open_app",
            "add_calendar_event",
            "add_reminder",
            "delete_calendar_event",
            "complete_reminder",
            "delete_reminder",
            "remove_calendar_event",
        }
        if tool_name in action_tools:
            return True

        if tool_name == "send_whatsapp_message":
            text = str(result or "").lower()
            if bool(args.get("send_now", False)):
                return "gönderildi" in text or "gonderildi" in text
            return False

        return False

    @staticmethod
    def _clean_transcript_text(text: str) -> tuple[str, bool]:
        raw = str(text or "")
        had_noise = False
        if CONTROL_TOKEN_RE.search(raw):
            had_noise = True
            raw = CONTROL_TOKEN_RE.sub(" ", raw)
        cleaned = []
        for ch in raw:
            if ch in "\n\r\t" or ord(ch) >= 32:
                cleaned.append(ch)
            else:
                had_noise = True
        normalized = " ".join("".join(cleaned).split())
        return normalized.strip(), had_noise

    def _build_system_instruction(self, query: str = "") -> str:
        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)
        relevant_mem = format_relevant_memories_for_prompt(query) if query else ""
        sys_p   = load_system_prompt()
        now     = datetime.datetime.now()
        time_ctx = f"[ŞU ANKİ ZAMAN]\n{now.strftime('%A, %d %B %Y — %H:%M')}\n\n"

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str + "\n\n")
        if relevant_mem:
            parts.append(relevant_mem + "\n\n")
        parts.append(sys_p)
        return "\n".join(parts)

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=self._build_system_instruction(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=str(get_app_config_value("voice", "Charon") or "Charon")
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        tool_id = getattr(fc, "id", f"runtime-{name}")
        if not self.agent_runtime.current_run_id:
            run_id = self.trace.start_run(f"tool call: {name}", source="tool")
            self.agent_runtime.set_current_run(run_id)

        async def run_direct(tool_name: str, tool_args: dict) -> str:
            direct_fc = SimpleNamespace(name=tool_name, args=tool_args or {}, id=tool_id)
            response = await self._execute_tool_direct(direct_fc)
            try:
                return str(response.response.get("result", ""))
            except Exception:
                return str(response)

        result = await self.agent_runtime.execute_tool(name, args, run_direct)
        return types.FunctionResponse(
            id=tool_id,
            name=name,
            response={"result": result},
        )

    async def _execute_tool_direct(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        print(f"[JARVIS] tool {name} {safe_log_preview(args, limit=700, redact_content_keys=True)}")
        if name in {"research_web", "answer_research_question", "tavily_search", "browser_research", "browser_read_url", "browse_url", "open_and_summarize_url"}:
            self.ui.set_state("RESEARCHING")
        else:
            self.ui.set_state("THINKING")
        policy = classify_tool(name, args)
        if policy.unknown:
            result = self._guarded_tool_action(name, args, lambda: "blocked")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result}
            )
        if name in OFFLINE_BLOCKED_TOOLS and not internet_available():
            result = (
                "Internet baglantisi yok/offline mod aktif. Bu arac dis kaynak gerektiriyor; "
                "yerel dosya, hafiza, pano ve sistem araclari calismaya devam eder."
            )
            self.trace.log_event(
                self.agent_runtime.current_run_id or self.trace.current_run_id,
                "offline_external_blocked",
                {"tool_name": name, "args": args},
            )
            return types.FunctionResponse(id=fc.id, name=name, response={"result": result})

        loop   = asyncio.get_event_loop()
        result = "Tamam."
        had_exception = False

        try:
            if name == "save_memory":
                cat = args.get("category", "notes")
                key = args.get("key", "")
                val = args.get("value", "")
                if key and val:
                    update_memory({cat: {key: {"value": val}}})
                    print(f"[Memory] saved {cat}/{key}")
                result = "ok"

            elif name == "delete_memory":
                result = delete_memory(
                    args.get("category", ""),
                    args.get("key", ""),
                    args.get("match_text", ""),
                )

            elif name == "search_memory":
                r = await loop.run_in_executor(
                    None,
                    lambda: search_memory(
                        args.get("query", ""),
                        args.get("kind", ""),
                        int(args.get("limit", 8) or 8),
                    ),
                )
                result = r or "Hafiza aramasi tamamlandi."

            elif name == "list_memory":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_memory(
                        args.get("kind", ""),
                        int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Hafiza listelendi."

            elif name == "memory_status":
                r = await loop.run_in_executor(None, memory_status)
                result = r or "Hafiza durumu alindi."

            elif name == "remember_file_note":
                r = await loop.run_in_executor(
                    None,
                    lambda: remember_file_note(
                        args.get("path", ""),
                        args.get("summary", ""),
                        args.get("tags", ""),
                    ),
                )
                result = r or "Dosya notu hafizaya kaydedildi."

            elif name == "pending_action_status":
                result = self.pending_actions.describe()

            elif name == "approve_pending_action":
                result = self.pending_actions.approve()

            elif name == "cancel_pending_action":
                result = self.pending_actions.cancel()

            elif name == "audit_status":
                result = audit_status(int(args.get("limit", 10) or 10), self.audit_logger)

            elif name == "tool_risk_status":
                result = tool_risk_status(args.get("tool_name", ""))

            elif name == "local_ai_status":
                r = await loop.run_in_executor(None, local_ai_status)
                result = r or "Yerel AI durumu alindi."

            elif name == "test_local_ai":
                r = await loop.run_in_executor(
                    None,
                    lambda: test_local_ai(args.get("prompt", "")),
                )
                result = r or "Yerel AI testi tamamlandi."

            elif name == "set_agent_mode":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: set_agent_mode(args.get("mode", "hybrid")),
                )

            elif name == "voice_experience_status":
                result = build_voice_experience_status(
                    config=load_app_config(),
                    audio_input_available=self._audio_input_available,
                    audio_output_available=self._audio_output_available,
                    text_mode=self._text_mode,
                    ptt_active=self.voice_gate.ptt_active,
                    wake_ready=bool(self._wake_detector and self._wake_detector.ready),
                    wake_error=self._wake_detector.status() if self._wake_detector else "",
                )

            elif name == "set_voice_mode":
                def _set_voice():
                    value = set_voice_mode_config(args.get("mode", "ptt_wake"))
                    status = self._refresh_wake_detector()
                    return f"{value}\n{status}"

                result = self._guarded_tool_action(name, args, _set_voice)

            elif name == "list_plugins":
                r = await loop.run_in_executor(None, list_plugins)
                result = r or "Pluginler listelendi."

            elif name == "plugin_status":
                r = await loop.run_in_executor(
                    None,
                    lambda: plugin_status(args.get("plugin_id", "")),
                )
                result = r or "Plugin durumu alindi."

            elif name == "enable_plugin":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: enable_plugin(args.get("plugin_id", "")),
                )

            elif name == "disable_plugin":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: disable_plugin(args.get("plugin_id", "")),
                )

            elif name == "set_plugin_config":
                config_value = args.get("config")
                if config_value is None:
                    config_value = args.get("config_json", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: set_plugin_config(
                        args.get("plugin_id", ""),
                        config_value,
                        bool(args.get("merge", True)),
                    ),
                )

            elif name == "discover_plugin_tools":
                r = await loop.run_in_executor(
                    None,
                    lambda: discover_plugin_tools(args.get("plugin_id", "")),
                )
                result = r or "Plugin tool kesfi tamamlandi."

            elif name == "call_plugin_tool":
                arguments_value = args.get("arguments")
                if arguments_value is None:
                    arguments_value = args.get("arguments_json", "{}")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: call_plugin_tool(
                        args.get("plugin_id", ""),
                        args.get("tool_name", ""),
                        arguments_value,
                    ),
                )

            elif name == "create_followup_task":
                r = await loop.run_in_executor(
                    None,
                    lambda: create_followup_task(
                        args.get("title", ""),
                        args.get("task_type", "web_watch"),
                        args.get("query", ""),
                        args.get("url", ""),
                        args.get("schedule_kind", "interval"),
                        int(args.get("interval_minutes", 180) or 180),
                        args.get("run_at", ""),
                        bool(args.get("baseline_now", True)),
                    ),
                )
                result = r or "Takip gorevi olusturuldu."

            elif name == "list_tasks":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_tasks(
                        args.get("status_filter", "active"),
                        int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Gorevler listelendi."

            elif name == "cancel_task":
                r = await loop.run_in_executor(
                    None,
                    lambda: cancel_task(args.get("task_id", 0)),
                )
                result = r or "Gorev iptal edildi."

            elif name == "run_task_now":
                r = await loop.run_in_executor(
                    None,
                    lambda: run_task_now(args.get("task_id", 0)),
                )
                result = r or "Gorev calistirildi."

            elif name == "startup_tracking_status":
                r = await loop.run_in_executor(None, startup_tracking_status)
                result = r or "Baslangic takip durumu alindi."

            elif name == "enable_startup_tracking":
                result = self._guarded_tool_action(
                    name,
                    args,
                    enable_startup_tracking,
                )

            elif name == "disable_startup_tracking":
                result = self._guarded_tool_action(
                    name,
                    args,
                    disable_startup_tracking,
                )

            elif name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(args.get("app_name", "")))
                result = r or f"{args.get('app_name')} açıldı."

            elif name == "sys_info":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: sys_info(args.get("query", "all")))
                result = r or "Bilgi alındı."

            elif name == "get_weather":
                self._focus_ui_section_for_tool(name, args)
                r = await loop.run_in_executor(
                    None, lambda: get_weather_summary(args.get("location") or None))
                result = r or "Hava durumu bilgisi alindi."

            elif name == "calendar_auth_status":
                r = await loop.run_in_executor(None, calendar_auth_status)
                result = r or "Takvim baglanti durumu alindi."

            elif name == "connect_calendar_provider":
                r = await loop.run_in_executor(
                    None,
                    lambda: connect_calendar_provider(
                        args.get("provider", ""),
                        args.get("mode", "start"),
                    ),
                )
                result = r or "Takvim saglayici baglantisi guncellendi."

            elif name == "disconnect_calendar_provider":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: disconnect_calendar_provider(args.get("provider", "")),
                )

            elif name == "list_calendars":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_calendars(args.get("provider", "")),
                )
                result = r or "Takvimler listelendi."

            elif name == "get_calendar_events":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_calendar_events(
                        args.get("query", "today"),
                        int(args.get("limit", 6) or 6),
                    ),
                )
                result = r or "Takvim bilgisi alindi."

            elif name == "add_calendar_event":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: add_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("end_iso", ""),
                        args.get("notes", ""),
                        args.get("location", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("all_day", False)),
                    ),
                )

            elif name == "delete_calendar_event":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: delete_calendar_event(
                        args.get("title", ""),
                        args.get("start_iso", ""),
                        args.get("calendar_name", ""),
                        bool(args.get("delete_all_matches", False)),
                    ),
                )

            elif name == "get_reminders":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_reminders(
                        args.get("query", "upcoming"),
                        int(args.get("limit", 8) or 8),
                        args.get("list_name", ""),
                    ),
                )
                result = r or "Animsatici bilgisi alindi."

            elif name == "add_reminder":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: add_reminder(
                        args.get("title", ""),
                        args.get("due_iso", ""),
                        args.get("notes", ""),
                        args.get("list_name", ""),
                        args.get("priority", ""),
                        bool(args.get("all_day", False)),
                    ),
                )

            elif name == "complete_reminder":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: complete_reminder(
                        args.get("reminder_id", ""),
                        args.get("title", ""),
                        args.get("list_name", ""),
                    ),
                )

            elif name == "delete_reminder":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: delete_reminder(
                        args.get("reminder_id", ""),
                        args.get("title", ""),
                        args.get("list_name", ""),
                    ),
                )

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(
                        args.get("action"),
                        args.get("url"),
                        args.get("query")
                    ))
                result = r or "Tamam."

            elif name == "browser_read_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: browser_read_url(
                        args.get("url", ""),
                        args.get("question", ""),
                        int(args.get("max_pages", 3) or 3),
                        bool(args.get("visible", False)),
                    ),
                )
                result = r or "Sayfa BrowserAgent ile okundu."

            elif name == "browser_research":
                r = await loop.run_in_executor(
                    None,
                    lambda: browser_research(
                        args.get("query", ""),
                        int(args.get("max_pages", 5) or 5),
                        bool(args.get("visible", False)),
                    ),
                )
                result = r or "BrowserAgent arastirmasi tamamlandi."

            elif name == "browser_click":
                target = args.get("selector_or_text", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: browser_click(target, bool(args.get("visible", True))),
                )

            elif name == "browser_fill":
                target = args.get("selector_or_label", "")
                value = args.get("value", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: browser_fill(target, value, bool(args.get("visible", True))),
                )

            elif name == "browser_submit":
                target = args.get("selector_or_text", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: browser_submit(target, bool(args.get("visible", True))),
                )

            elif name == "shell_run":
                command = args.get("command", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: shell_run(command),
                )

            elif name == "play_media":
                r = await loop.run_in_executor(
                    None,
                    lambda: play_media(
                        args.get("query", ""),
                        args.get("provider", "auto"),
                        bool(args.get("autoplay", True)),
                    ),
                )
                result = r or "Medya oynatma başlatıldı."

            elif name == "get_youtube_channel_report":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_youtube_channel_report(
                        args.get("query", "overview"),
                        args.get("handle", ""),
                        int(args.get("video_limit", 6) or 6),
                    ),
                )
                result = r or "YouTube kanal raporu alindi."

            elif name == "analyze_screen":
                r = await loop.run_in_executor(
                    None,
                    lambda: analyze_screen(
                        args.get("query", "Ekranda ne var?"),
                        args.get("target", "active_window"),
                    ),
                )
                result = r or "Ekran analizi tamamlandi."

            elif name == "list_folder":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_folder(
                        args.get("path", ""),
                        int(args.get("limit", 60) or 60),
                    ),
                )
                result = r or "Klasor listelendi."

            elif name == "find_files":
                r = await loop.run_in_executor(
                    None,
                    lambda: find_files(
                        args.get("query", ""),
                        args.get("path", ""),
                        int(args.get("limit", 40) or 40),
                    ),
                )
                result = r or "Dosya aramasi tamamlandi."

            elif name == "read_text_file":
                r = await loop.run_in_executor(
                    None,
                    lambda: read_text_file(
                        args.get("path", ""),
                        int(args.get("max_chars", 12000) or 12000),
                    ),
                )
                result = r or "Dosya okundu."

            elif name == "summarize_text_file":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_text_file(
                        args.get("path", ""),
                        int(args.get("max_chars", 16000) or 16000),
                    ),
                )
                result = r or "Dosya ozetlendi."

            elif name == "open_file":
                r = await loop.run_in_executor(
                    None, lambda: open_file(args.get("path", "")))
                result = r or "Dosya acildi."

            elif name == "get_clipboard":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_clipboard(int(args.get("max_chars", 12000) or 12000)),
                )
                result = r or "Pano okundu."

            elif name == "set_clipboard":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: set_clipboard(args.get("text", "")),
                )

            elif name == "summarize_clipboard":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_clipboard(int(args.get("max_chars", 4000) or 4000)),
                )
                result = r or "Pano ozetlendi."

            elif name == "get_selected_text":
                r = await loop.run_in_executor(
                    None,
                    lambda: get_selected_text(
                        int(args.get("max_chars", 12000) or 12000),
                        bool(args.get("restore_clipboard", True)),
                    ),
                )
                result = r or "Secili metin okundu."

            elif name == "summarize_selected_text":
                r = await loop.run_in_executor(
                    None,
                    lambda: summarize_selected_text(int(args.get("max_chars", 4000) or 4000)),
                )
                result = r or "Secili metin ozetlendi."

            elif name == "active_window_info":
                r = await loop.run_in_executor(None, active_window_info)
                result = r or "Aktif pencere bilgisi alindi."

            elif name == "list_windows":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_windows(
                        args.get("query", ""),
                        int(args.get("limit", 20) or 20),
                    ),
                )
                result = r or "Pencereler listelendi."

            elif name == "focus_window":
                r = await loop.run_in_executor(
                    None,
                    lambda: focus_window(
                        args.get("query", ""),
                        bool(args.get("exact", False)),
                    ),
                )
                result = r or "Pencere odaklandi."

            elif name == "send_hotkey_safe":
                hotkey = args.get("hotkey", "")
                delay = float(args.get("delay_seconds", 0.2) or 0.2)
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: send_hotkey_safe(hotkey, delay),
                )

            elif name == "web_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: web_search(
                        args.get("query", ""),
                        bool(args.get("open_results", True)),
                    ),
                )
                result = r or "Web aramasi acildi."

            elif name == "open_and_summarize_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: open_and_summarize_url(
                        args.get("url", ""),
                        int(args.get("max_chars", 2500) or 2500),
                    ),
                )
                result = r or "Sayfa acildi."

            elif name == "research_web":
                r = await loop.run_in_executor(
                    None,
                    lambda: research_web(
                        args.get("query", ""),
                        int(args.get("max_pages", 5) or 5),
                        bool(args.get("open_browser", False)),
                    ),
                )
                result = r or "Arastirma tamamlandi."

            elif name == "answer_research_question":
                r = await loop.run_in_executor(
                    None,
                    lambda: answer_research_question(
                        args.get("query", ""),
                        args.get("depth", "balanced"),
                        bool(args.get("speak", False)),
                    ),
                )
                result = r or "Arastirma tamamlandi."

            elif name == "tavily_search":
                r = await loop.run_in_executor(
                    None,
                    lambda: tavily_search(
                        args.get("query", ""),
                        int(args.get("max_results", 5) or 5),
                        args.get("search_depth", "advanced"),
                    ),
                )
                result = r or "Tavily arastirmasi tamamlandi."

            elif name == "browse_url":
                r = await loop.run_in_executor(
                    None,
                    lambda: browse_url(
                        args.get("url", ""),
                        args.get("question", ""),
                        int(args.get("max_pages", 2) or 2),
                        bool(args.get("open_browser", False)),
                    ),
                )
                result = r or "Sayfa gezildi."

            elif name == "create_folder":
                path = args.get("path", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: create_folder(path),
                )

            elif name == "create_text_file":
                path = args.get("path", "")
                content = args.get("content", "")
                overwrite = bool(args.get("overwrite", False))
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: create_text_file(path, content, overwrite),
                )

            elif name == "write_text_file":
                path = args.get("path", "")
                content = args.get("content", "")
                overwrite = bool(args.get("overwrite", True))
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: write_text_file(path, content, overwrite),
                )

            elif name == "append_text_file":
                path = args.get("path", "")
                content = args.get("content", "")
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: append_text_file(path, content),
                )

            elif name == "move_file":
                source_path = args.get("source_path", "")
                destination_path = args.get("destination_path", "")
                overwrite = bool(args.get("overwrite", False))
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: move_file(source_path, destination_path, overwrite),
                )

            elif name == "delete_file":
                path = args.get("path", "")
                recursive = bool(args.get("recursive", False))
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: delete_file(path, recursive),
                )

            elif name == "find_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: find_whatsapp_contact(
                        args.get("query", ""),
                        int(args.get("limit", 5) or 5),
                    ),
                )
                result = r or "WhatsApp kisi aramasi tamamlandi."

            elif name == "list_whatsapp_contacts":
                r = await loop.run_in_executor(
                    None,
                    lambda: list_whatsapp_contacts(
                        int(args.get("limit", 30) or 30),
                        args.get("source_filter", ""),
                    ),
                )
                result = r or "WhatsApp kisileri listelendi."

            elif name == "import_phone_book_from_vcf":
                result = self._guarded_tool_action(
                    name,
                    args,
                    lambda: import_phone_book_from_vcf(args.get("vcf_path", "")),
                )

            elif name == "send_whatsapp_message":
                message = args.get("message", "")
                phone_number = args.get("phone_number", "")
                recipient_name = args.get("recipient_name", "")
                send_now = bool(args.get("send_now", False))
                app_target = args.get("app_target", "auto")
                if send_now:
                    result = self._guarded_tool_action(
                        name,
                        args,
                        lambda: send_whatsapp_message(
                            message,
                            phone_number,
                            recipient_name,
                            True,
                            app_target,
                        ),
                    )
                else:
                    r = await loop.run_in_executor(
                        None,
                        lambda: send_whatsapp_message(
                            message,
                            phone_number,
                            recipient_name,
                            False,
                            app_target,
                        ),
                    )
                    result = r or "WhatsApp taslagi hazirlandi."

            elif name == "save_whatsapp_contact":
                r = await loop.run_in_executor(
                    None,
                    lambda: save_whatsapp_contact(
                        args.get("display_name", ""),
                        args.get("phone_number", ""),
                        args.get("aliases", ""),
                    ),
                )
                result = r or "WhatsApp kişisi kaydedildi."

            else:
                result = f"Bilinmeyen araç: {name}"

        except Exception as e:
            result = f"Hata: {e}"
            had_exception = True
            self.trace.log_error(
                self.agent_runtime.current_run_id or self.trace.current_run_id,
                f"tool:{name}",
                f"{type(e).__name__}: {e}",
                {"tool_name": name, "args_preview": safe_log_preview(args, limit=700, redact_content_keys=True)},
            )
            self.speak_error(name, e)

        tool_failed = self._result_looks_like_error(result)
        waiting_approval = str(result or "").startswith("Onay gerekiyor")
        if policy.audit_required and not (policy.requires_approval and str(result).startswith("Onay gerekiyor")):
            self.audit_logger.log(
                "failed" if (had_exception or tool_failed) else "executed",
                run_id=self.agent_runtime.current_run_id or self.trace.current_run_id,
                tool_name=name,
                risk_class=policy.risk_class,
                args=args,
                summary=policy.summary(args),
                result=str(result),
                status="failed" if (had_exception or tool_failed) else "executed",
            )
        if tool_failed:
            if not had_exception:
                self.ui.set_state("ERROR")
        elif waiting_approval:
            self.ui.set_state("WAITING_APPROVAL")
        elif self._should_play_success_sfx(name, args, result):
            self.ui.play_success_sfx()

        if not tool_failed and not waiting_approval and not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] result {name} -> {safe_log_preview(result, limit=300)}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    def _get_pyaudio(self):
        if pyaudio is None:
            raise RuntimeError("PyAudio yuklu degil veya baslatilamadi.")
        with self._pyaudio_lock:
            if self._pyaudio is None:
                self._pyaudio = pyaudio.PyAudio()
            return self._pyaudio

    def _open_input_stream(self):
        last_error = None
        candidates = [None]
        pya = self._get_pyaudio()
        try:
            for index in range(pya.get_device_count()):
                info = pya.get_device_info_by_index(index)
                if int(info.get("maxInputChannels", 0) or 0) > 0:
                    candidates.append(index)
        except Exception:
            pass

        for index in candidates:
            try:
                kwargs = {}
                if index is not None:
                    kwargs["input_device_index"] = index
                return pya.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=SEND_SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK_SIZE,
                    **kwargs,
                )
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("Mikrofon cihazi bulunamadi.")

    def _open_output_stream(self):
        last_error = None
        candidates = [None]
        pya = self._get_pyaudio()
        try:
            for index in range(pya.get_device_count()):
                info = pya.get_device_info_by_index(index)
                if int(info.get("maxOutputChannels", 0) or 0) > 0:
                    candidates.append(index)
        except Exception:
            pass

        for index in candidates:
            try:
                kwargs = {}
                if index is not None:
                    kwargs["output_device_index"] = index
                return pya.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RECV_SAMPLE_RATE,
                    output=True,
                    **kwargs,
                )
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("Ses cikis cihazi bulunamadi.")

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mikrofon başladı")
        try:
            stream = await asyncio.to_thread(self._open_input_stream)
            self._audio_input_available = True
            self._text_mode = False
            self._sync_voice_ui()
        except Exception as exc:
            self._audio_input_available = False
            self._text_mode = True
            self._sync_voice_ui()
            detail = f"{type(exc).__name__}: {exc}"
            print(f"[JARVIS] Mikrofon devre disi: {detail}")
            self._audio_notice(
                "input_unavailable",
                "Mikrofon acilamadi; yazili komut ve web arama modu aktif. Windows Ses Ayarlari > Giris cihazini kontrol et.",
            )
            return
        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False)
                if (
                    self._wake_detector
                    and self._wake_detector.config.enabled
                    and not self.voice_gate.ptt_active
                    and self._wake_detector.process_pcm(data)
                ):
                    self._arm_wake_capture()
                with self._speaking_lock:
                    jarvis_speaking = self._is_speaking
                self.voice_gate.muted = bool(self.ui.muted)
                self.voice_gate.paused = bool(self._paused)
                if jarvis_speaking and self.voice_gate.is_open():
                    await self._interrupt_audio()
                    jarvis_speaking = False
                if not jarvis_speaking and self.voice_gate.is_open():
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
        except Exception as e:
            print(f"[JARVIS] ❌ Mikrofon: {e}")
            self._audio_input_available = False
            self._audio_notice(
                "input_failed",
                f"Mikrofon akisi durdu; yazili komut modu aktif. Detay: {type(e).__name__}: {e}",
            )
            self._text_mode = True
            self._sync_voice_ui()
            return
        finally:
            stream.close()

    async def _receive_audio(self):
        print("[JARVIS] 👂 Alım başladı")
        out_buf, in_buf = [], []
        output_noise = False
        output_noise_samples = []
        try:
            while True:
                async for response in self.session.receive():
                    if response.data and self._audio_output_available:
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            self.set_speaking(True)
                            raw_txt = sc.output_transcription.text.strip()
                            if raw_txt:
                                txt, had_noise = self._clean_transcript_text(raw_txt)
                                if had_noise:
                                    output_noise = True
                                    if len(output_noise_samples) < 4:
                                        output_noise_samples.append(raw_txt)
                                if txt:
                                    out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                if not self._voice_run_id:
                                    self._voice_run_id = self._start_user_run("voice input", source="voice")
                                in_buf.append(txt)
                                self.ui.mark_user_activity(True)

                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            voice_control_handled = False
                            if full_in:
                                if not self._voice_run_id:
                                    self._voice_run_id = self._start_user_run(full_in, source="voice")
                                self.trace.log_event(self._voice_run_id, "voice_transcript", {"text": full_in})
                                self.ui.write_log(f"Siz: {full_in}")
                                voice_control_handled = self._handle_voice_control_command(full_in, source="voice")
                                if voice_control_handled:
                                    self.trace.log_event(self._voice_run_id, "voice_control_command", {"text": full_in})
                                else:
                                    self._auto_learn_from_user_text(full_in, self._voice_run_id)
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out and not voice_control_handled:
                                if self._voice_run_id:
                                    self.trace.log_event(self._voice_run_id, "voice_agent_result", {"text": full_out})
                                    saved_summary = save_conversation_summary(full_in, full_out, self._voice_run_id)
                                    if saved_summary and not saved_summary.get("blocked") and saved_summary.get("id"):
                                        self.trace.log_event(self._voice_run_id, "conversation_summary_saved", {"id": saved_summary.get("id")})
                                self.speech_memory.set(self._speech_excerpt(full_out) or full_out)
                                self.ui.write_log(f"JARVIS: {full_out}")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Kısmen filtrelenen ses transcripti: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                            elif output_noise:
                                self.ui.write_log("ERR: JARVIS sesli yanıtını çözümlerken bir hata oluştu.")
                                if output_noise_samples:
                                    self.ui.write_debug(
                                        "Filtrelenen ham transcript: " + " | ".join(output_noise_samples),
                                        level="WARN",
                                    )
                                self.ui.set_state("ERROR")
                            out_buf = []
                            output_noise = False
                            output_noise_samples = []
                            self._voice_run_id = ""

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses)

        except Exception as e:
            print(f"[JARVIS] ❌ Alım: {e}")
            self.trace.log_error(
                self._voice_run_id or self.trace.current_run_id,
                "receive_audio",
                f"{type(e).__name__}: {e}",
            )
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Ses çalma başladı")
        try:
            stream = await asyncio.to_thread(self._open_output_stream)
            self._audio_output_available = True
        except Exception as exc:
            self._audio_output_available = False
            detail = f"{type(exc).__name__}: {exc}"
            print(f"[JARVIS] Ses cikisi devre disi: {detail}")
            self._audio_notice(
                "output_unavailable",
                "Ses cikisi acilamadi; yanitlar metin olarak loglanacak. Windows Ses Ayarlari > Cikis cihazini kontrol et.",
            )
            return
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Ses: {e}")
            self._audio_output_available = False
            self._audio_notice(
                "output_failed",
                f"Ses cikisi durdu; yanitlar metin olarak loglanacak. Detay: {type(e).__name__}: {e}",
            )
            return
        finally:
            self.set_speaking(False)
            stream.close()

    async def run(self):
        self._loop = asyncio.get_event_loop()
        gemini_missing_notice_sent = False

        while True:
            # Duraklatılmışsa bağlanma, bekle
            if self._paused:
                await asyncio.sleep(1)
                continue

            api_key = get_api_key()
            if not api_key:
                if not gemini_missing_notice_sent:
                    self.ui.write_log("SYS: Gemini API anahtari yok; sesli Live devre disi, yazili Ninerouter ajan modu kullanilabilir.")
                    self.ui.set_state("LISTENING")
                    gemini_missing_notice_sent = True
                await asyncio.sleep(3)
                continue

            client = genai.Client(
                api_key=api_key,
                http_options={"api_version": "v1alpha"}
            )

            try:
                print("[JARVIS] 🔌 Bağlanıyor...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Bağlandı.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS hazır. Dinliyorum...")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                detail = self._format_exception_summary(e)
                print(f"[JARVIS] ⚠️ {detail}")
                self.trace.log_error(
                    self.trace.current_run_id,
                    "gemini_live",
                    detail,
                )
                self.set_speaking(False)
                self.session = None
                self.ui.write_log(f"ERR: JARVIS baglantisi kesildi veya internete ulasilamiyor - {detail}")
                self.ui.set_state("ERROR")
                print("[JARVIS] 🔄 3 saniyede yeniden bağlanıyor...")
                await asyncio.sleep(3)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JARVIS desktop assistant")
    parser.add_argument("--smoke", action="store_true", help="Windows UI smoke modunu calistir ve cik.")
    parser.add_argument("--smoke-timeout", type=int, default=90, help="Smoke modu zaman asimi saniyesi.")
    parser.add_argument("--smoke-app", default="explorer", help="Smoke modunda acilacak uygulama.")
    return parser


def _run_smoke_app(timeout_seconds: int = 90, smoke_app: str = "explorer") -> int:
    ui = JarvisUI()
    try:
        ui._api_key_ready = True
        if hasattr(ui, "_close_setup_ui"):
            ui._close_setup_ui()
        ui.set_text_mode(True)
        ui.set_state("LISTENING")
    except Exception:
        pass

    jarvis = JarvisLive(ui, start_task_scheduler=False)
    jarvis._text_mode = True
    jarvis._sync_voice_ui()

    holder = {"finished": False, "exit_code": 1}
    lock = threading.Lock()

    def close_ui(delay_ms: int = 1200) -> None:
        def close() -> None:
            try:
                jarvis.task_scheduler.stop()
            except Exception:
                pass
            try:
                ui.sound.stop_all()
            except Exception:
                pass
            try:
                ui.root.destroy()
            except Exception:
                pass

        try:
            ui.root.after(delay_ms, close)
        except Exception:
            close()

    def finish(report: dict) -> None:
        with lock:
            if holder["finished"]:
                return
            holder["finished"] = True
            holder["exit_code"] = 0 if report.get("status") in {"pass", "degraded"} else 1
        try:
            ui.write_log(f"SYS: Windows smoke tamamlandi: {report.get('status')} | {report.get('report_path', '')}")
        except Exception:
            pass
        close_ui()

    def timeout() -> None:
        with lock:
            if holder["finished"]:
                return
            holder["finished"] = True
            holder["exit_code"] = 1
        report = build_timeout_report(timeout_seconds)
        try:
            ui.write_log(f"SYS: SMOKE FAIL - timeout | {report.get('report_path', '')}")
        except Exception:
            pass
        close_ui(300)

    def worker() -> None:
        try:
            report = run_smoke_sequence(ui=ui, jarvis=jarvis, smoke_app=smoke_app)
        except Exception as exc:
            report = {
                "status": "fail",
                "report_path": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            ui.root.after(0, finish, report)
        except Exception:
            finish(report)

    threading.Thread(target=worker, name="JarvisSmoke", daemon=True).start()
    ui.root.after(max(1, int(timeout_seconds or 90)) * 1000, timeout)
    ui.root.mainloop()
    return int(holder["exit_code"])


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if os.environ.get("TERM_PROGRAM") == "vscode":
        print("[JARVIS] VS Code icinden baslatildi.")

    if args.smoke:
        return _run_smoke_app(args.smoke_timeout, args.smoke_app)

    ui = JarvisUI()

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Kapatılıyor...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
