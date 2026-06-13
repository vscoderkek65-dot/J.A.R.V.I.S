"""
Gemini tool declarations for JARVIS.

All tool schemas that JARVIS exposes to Gemini/OpenAI-compatible LLMs.
Extracted from core/jarvis_live.py for modularity.
"""

from __future__ import annotations

from typing import Any

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    # --- Agent Mode ---
    {
        "name": "set_agent_mode",
        "description": "Sohbet ajan modunu degistirir. hybrid = sesli/yazili AI; local = sadece yerel; cloud = sadece OpenAI/9Router.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "hybrid | local | cloud"}
            },
            "required": ["mode"],
        },
    },
    # --- Voice ---
    {
        "name": "voice_experience_status",
        "description": "Mevcut ses deneyimi durumunu raporlar: mikrofon, hoparlor, wake word, PTT durumu ve text mode.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "set_voice_mode",
        "description": "Ses giris modunu degistirir. open = surekli acik, ptt = bas-konus, ptt_wake = wake word ile PTT.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "description": "open | ptt | ptt_wake"}
            },
            "required": ["mode"],
        },
    },
    # --- Pending Actions ---
    {
        "name": "pending_action_status",
        "description": "Onay bekleyen islem varsa aciklamasini dondurur.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "approve_pending_action",
        "description": "Onay bekleyen islemi onaylar. Kullanici 'tamam', 'onayliyorum', 'evet' dediginde LLM tarafindan cagrilir.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "cancel_pending_action",
        "description": "Onay bekleyen islemi iptal eder.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    # --- Safety ---
    {
        "name": "audit_status",
        "description": "Son audit log kayitlarini listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {"type": "NUMBER", "description": "Maksimum kayit sayisi"}
            },
        },
    },
    {
        "name": "tool_risk_status",
        "description": "Bir aracin risk sinifini, gerektirdigi onay/denetim duzeyini gosterir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tool_name": {"type": "STRING", "description": "Sorgulanacak tool adi (ornek: shell_run)"}
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "local_ai_status",
        "description": "Yerel AI modelinin kurulu olup olmadigini, saglayiciyi ve hazir olma durumunu raporlar.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "test_local_ai",
        "description": "Yerel AI modeline kucuk bir test mesaji gonderir ve yaniti raporlar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING", "description": "Test mesaji metni"}
            },
        },
    },
    # --- Tasks ---
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
                "baseline_now": {"type": "BOOLEAN", "description": "true ise ilk calisma baseline kaydeder"},
            },
        },
    },
    {
        "name": "list_tasks",
        "description": "Kalici takip/gorev listesini verir. Aktif takipleri sorunca kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "status_filter": {"type": "STRING", "description": "active | pending | running | done | failed | cancelled"},
                "limit": {"type": "NUMBER", "description": "Maksimum gorev sayisi"},
            },
        },
    },
    {
        "name": "cancel_task",
        "description": "Kalici takip veya gorevi iptal eder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"task_id": {"type": "NUMBER", "description": "Iptal edilecek gorev ID'si"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "run_task_now",
        "description": "Secili takip/gorevi hemen calistirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"task_id": {"type": "NUMBER", "description": "Calistirilacak gorev ID'si"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "startup_tracking_status",
        "description": "Windows baslangicinda JARVIS takip sisteminin acik/kapali durumunu soyler.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "enable_startup_tracking",
        "description": "Windows baslangicinda JARVIS takip sistemini acmak icin onay bekleyen islem olusturur.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "disable_startup_tracking",
        "description": "Windows baslangicinda JARVIS takip sistemini kapatmak icin onay bekleyen islem olusturur.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    # --- Memory ---
    {
        "name": "save_memory",
        "description": "Kullanıcı hakkında önemli bilgiyi kalıcı belleğe kaydeder. İsim, tercihler, projeler vb. duyunca sessizce çağır.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "identity | preferences | projects | notes"},
                "key": {"type": "STRING", "description": "Kısa anahtar (örn. 'name')"},
                "value": {"type": "STRING", "description": "Değer (İngilizce)"},
            },
            "required": ["category", "key", "value"],
        },
    },
    {
        "name": "delete_memory",
        "description": "Kalici hafizadaki bir kaydi siler. Kullanici 'bunu hafizandan kaldir', 'unut', 'sil' derse kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "identity | preferences | projects | notes"},
                "key": {"type": "STRING", "description": "Silinecek anahtar."},
                "match_text": {"type": "STRING", "description": "Kaydi bulmak icin dogal dil parcasi."},
            },
        },
    },
    {
        "name": "search_memory",
        "description": "SQLite hafiza katmaninda gecmis konusma, karar, tercih, proje/dosya notu veya gorev ozetlerini arar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Aranacak konu, tercih, karar veya gecmis konusma parcasi"},
                "kind": {"type": "STRING", "description": "profile | preference | conversation_summary | decision | project_note | file_note | task_summary"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_memory",
        "description": "SQLite hafiza kayitlarini tur/son guncelleme sirasiyla listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "description": "Opsiyonel hafiza turu filtresi"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
            },
        },
    },
    {
        "name": "memory_status",
        "description": "JSON profil hafizasi ve SQLite hafiza indeksinin durumunu ozetler.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "remember_file_note",
        "description": "Kullanici acikca isterse bir dosya/proje hakkinda ozet notu hafizaya kaydeder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Not alinacak dosya veya klasor yolu"},
                "summary": {"type": "STRING", "description": "Kaydedilecek kisa ozet veya not"},
                "tags": {"type": "STRING", "description": "Virgulle ayrilmis etiketler"},
            },
            "required": ["path"],
        },
    },
    # --- WhatsApp ---
    {
        "name": "send_whatsapp_message",
        "description": "WhatsApp uzerinden mesaj taslagi acar veya mesaji gonderir. send_now=true ile dogrudan gonderir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "recipient_name": {"type": "STRING", "description": "Kisi adi."},
                "phone_number": {"type": "STRING", "description": "Uluslararasi telefon numarasi."},
                "message": {"type": "STRING", "description": "Mesaj icerigi"},
                "app_target": {"type": "STRING", "description": "desktop | web | auto"},
                "send_now": {"type": "BOOLEAN", "description": "true ise mesaji otomatik gonderir"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "find_whatsapp_contact",
        "description": "Kayitli WhatsApp kisileri ve ice aktarilan telefon rehberinde kisi arar.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Aranacak kisi adi veya telefon"},
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_whatsapp_contacts",
        "description": "Kayitli WhatsApp kisilerini listeler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limit": {"type": "NUMBER", "description": "Maksimum sonuc sayisi"},
                "source_filter": {"type": "STRING", "description": "whatsapp veya phone_book"},
            },
        },
    },
    {
        "name": "import_phone_book_from_vcf",
        "description": "Bir .vcf rehber dosyasini ice aktarir; onay bekler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"vcf_path": {"type": "STRING", "description": ".vcf dosya yolu"}},
            "required": ["vcf_path"],
        },
    },
    {
        "name": "save_whatsapp_contact",
        "description": "Sik kullanilan bir WhatsApp kisisini kalici bellege kaydeder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "display_name": {"type": "STRING", "description": "Kisi adi"},
                "phone_number": {"type": "STRING", "description": "Telefon numarasi"},
                "aliases": {"type": "STRING", "description": "Virgulle ayrilmis alternatif hitaplar"},
            },
            "required": ["display_name", "phone_number"],
        },
    },
    # --- Plugins ---
    {
        "name": "list_plugins",
        "description": "Kurulu JARVIS plugin manifestlerini listeler.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "plugin_status",
        "description": "Belirli bir plugin veya tum plugin registry durumunu verir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"plugin_id": {"type": "STRING", "description": "Opsiyonel plugin id"}},
        },
    },
    {
        "name": "enable_plugin",
        "description": "Kapali bir plugin'i acmak icin onay bekleyen islem olusturur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"plugin_id": {"type": "STRING", "description": "Acilacak plugin id"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "disable_plugin",
        "description": "Bir plugin'i kapatir ve MCP tool cagrilarini engeller.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"plugin_id": {"type": "STRING", "description": "Kapatilacak plugin id"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "set_plugin_config",
        "description": "Plugin MCP/config alanlarini kaydeder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Plugin id"},
                "config_json": {"type": "STRING", "description": "JSON config"},
                "merge": {"type": "BOOLEAN", "description": "true ise mevcut config ile birlestirir"},
            },
            "required": ["plugin_id", "config_json"],
        },
    },
    {
        "name": "discover_plugin_tools",
        "description": "Acik plugin icin MCP list_tools calistirir veya manifest tool'larini okur.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"plugin_id": {"type": "STRING", "description": "Plugin id"}},
            "required": ["plugin_id"],
        },
    },
    {
        "name": "call_plugin_tool",
        "description": "Acik ve kesfedilmis bir plugin/MCP tool'unu generic gateway uzerinden cagirir.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plugin_id": {"type": "STRING", "description": "Plugin id"},
                "tool_name": {"type": "STRING", "description": "Kesfedilmis MCP tool adi"},
                "arguments_json": {"type": "STRING", "description": "Tool argumanlari JSON"},
            },
            "required": ["plugin_id", "tool_name"],
        },
    },
    # --- Document Generation ---
    {
        "name": "create_pdf",
        "description": "JSON deskriptorden PDF belgesi olusturur. Rapor, fatura, dokuman gibi ciktilarda kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "descriptor_json": {"type": "STRING", "description": "PDF deskriptoru JSON (title, pages, elements)"},
                "output_path": {"type": "STRING", "description": "Kaydedilecek dosya yolu (.pdf)"},
            },
            "required": ["descriptor_json", "output_path"],
        },
    },
    {
        "name": "create_docx",
        "description": "JSON deskriptorden Word belgesi (.docx) olusturur. Rapor, teklif, mektup, CV gibi dokumanlarda kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "descriptor_json": {"type": "STRING", "description": "DOCX deskriptoru JSON (sections, children, styles)"},
                "output_path": {"type": "STRING", "description": "Kaydedilecek dosya yolu (.docx)"},
            },
            "required": ["descriptor_json", "output_path"],
        },
    },
    {
        "name": "create_xlsx",
        "description": "JSON deskriptorden Excel tablosu (.xlsx) olusturur. Veri, rapor, butce gibi tablosal ciktilarda kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "descriptor_json": {"type": "STRING", "description": "XLSX deskriptoru JSON (sheets, columns, rows)"},
                "output_path": {"type": "STRING", "description": "Kaydedilecek dosya yolu (.xlsx)"},
            },
            "required": ["descriptor_json", "output_path"],
        },
    },
    {
        "name": "create_pptx",
        "description": "JSON deskriptorden PowerPoint sunusu (.pptx) olusturur. Sunum, pitch deck, slaytlarda kullan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "descriptor_json": {"type": "STRING", "description": "PPTX deskriptoru JSON (layout, slides, elements)"},
                "output_path": {"type": "STRING", "description": "Kaydedilecek dosya yolu (.pptx)"},
            },
            "required": ["descriptor_json", "output_path"],
        },
    },
    {
        "name": "document_status",
        "description": "zenskill CLI'nin kurulu olup olmadigini ve versiyonunu kontrol eder.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]
