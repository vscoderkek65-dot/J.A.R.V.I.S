# J.A.R.V.I.S

Windows odakli Python/Tkinter masaustu asistani. JARVIS; yazili komut, Gemini Live ses cekirdegi, OpenAI-compatible text agent, web arastirma, BrowserAgent, dosya/masaustu araclari, hafiza, takip gorevleri, plugin/MCP kapisi ve onayli guvenlik modeliyle calisir.

## Durum

- Hedef platform: Windows 10/11
- Ana giris noktasi: `main.py`
- Windows baslatma: `run_windows.ps1`
- Windows kurulum: `setup_windows.ps1`
- Varsayilan model modu: `hybrid`
- Riskli islemler: onay bekler
- Runtime veri ve secret dosyalari: repoya commit edilmez

## Hizli Kurulum

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1
```

Kurulum script'i `venv` olusturur, `config/api_keys.example.json` dosyasini `config/api_keys.json` olarak kopyalar ve core paketleri kurar.

PyAudio/mikrofon kurulumu opsiyoneldir. PyAudio kurulamazsa JARVIS kapanmaz; text-mode ve yazili komutlar calismaya devam eder.

## API ve Model Ayarlari

Ayarlari uygulama icinden veya `config/api_keys.json` dosyasindan yapabilirsin.

Desteklenen modlar:

- `cloud`: OpenAI API veya 9Router/OpenAI-compatible endpoint
- `local`: Foundry Local veya manuel OpenAI-compatible local endpoint
- `hybrid`: local hizli/yerel isler, cloud guncel web ve karmasik planlama

OpenAI direct kullanim icin:

```json
{
  "agent_mode": "cloud",
  "cloud_base_url": "https://api.openai.com/v1",
  "cloud_model": "MODEL_ADI",
  "cloud_api_key": "<key>"
}
```

ChatGPT Plus/Business hesabini OAuth ile API yerine kullanmak resmi bir model erisim yontemi degildir. Model API kullanimi icin API key veya OpenAI-compatible endpoint gerekir.

## Opsiyonel Ozellikler

Playwright Chromium:

```powershell
.\venv\Scripts\python.exe -m playwright install chromium
```

PyAudio mikrofon backend:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-voice.txt
```

Tesseract OCR:

```powershell
winget install UB-Mannheim.TesseractOCR
```

## Smoke ve Test

Statik parse, unit/regression ve secret scan:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1
```

Canli Windows smoke:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

Smoke raporlari `memory/smoke/` altina yazilir ve `.gitignore` ile repodan dislanir.

## Guvenlik Modeli

JARVIS araclari merkezi risk siniflarindan gecer:

- `read`: onaysiz
- `external`: salt-okuma dis erisim, onaysiz
- `write`, `send`, `execute`, `delete`: riskli durumda onayli

Dosya yazma/silme/tasima, shell, hotkey, browser form/click/submit ve WhatsApp `send_now=true` gibi islemler kullanici onayi olmadan uygulanmaz. Web, dosya, pano ve OCR icerigi guvensiz kaynak kabul edilir; sistem talimati gibi islenmez.

## Public Repo Hijyeni

Repoya commit edilmeyen dosyalar:

- `config/api_keys.json`
- `memory/*.sqlite3`
- `memory/audit/`
- `memory/oauth/`
- `memory/smoke/`
- `memory/traces/`
- `memory/plugins/plugin_state.json`
- `venv/`

## Yol Haritasi

Fazli gelisim plani `docs/ROADMAP.md` dosyasinda tutulur.
