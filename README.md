<div align="center">

# J.A.R.V.I.S

**Just A Rather Very Intelligent System**

Windows 10/11 icin guvenli, sesli ve genisletilebilir masaustu AI asistani.

[![CI](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/ci.yml/badge.svg)](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/ci.yml)
[![CodeQL](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/codeql.yml/badge.svg)](https://github.com/vscoderkek65-dot/J.A.R.V.I.S/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-2ea44f)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows)](README.md)

</div>

## Genel Bakis

J.A.R.V.I.S; metin ve ses komutlarini, masaustu otomasyonunu, web
arastirmasini, kalici sohbet hafizasini ve MCP tabanli eklentileri tek bir
Tkinter uygulamasinda birlestirir.

Proje varsayilan olarak guvenli calisir. Dosya yazma/silme, mesaj gonderme,
uygulama kontrolu ve benzeri yan etkili islemler acik kullanici onayi olmadan
uygulanmaz.

## Temel Yetenekler

- Gemini Live ile gercek zamanli sesli etkilesim
- OpenAI-compatible cloud ve yerel model destegi
- `cloud`, `local` ve `hybrid` calisma modlari
- Playwright tabanli Browser Agent ve cok kaynakli web arastirmasi
- Dosya, pano, pencere, uygulama ve ekran araclari
- SQLite tabanli sohbet gecmisi, gorevler ve uzun sureli hafiza
- Eski sohbeti secme, yeni sohbet acma ve baglamsal takip komutlari
- Outlook/Google takvim ve hatirlatma entegrasyonlari
- MCP tabanli izin kontrollu plugin mimarisi
- Merkezi risk siniflandirmasi, onay kapisi, audit ve trace loglari

## Hizli Baslangic

Gereksinimler:

- Windows 10 veya Windows 11
- Python 3.11 veya daha yeni
- PowerShell 5.1 veya PowerShell 7

```powershell
git clone https://github.com/vscoderkek65-dot/J.A.R.V.I.S.git
cd J.A.R.V.I.S
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1
```

Ilk kurulum `config/api_keys.example.json` dosyasindan yerel
`config/api_keys.json` olusturur. Gercek anahtar dosyasi Git tarafindan
izlenmez.

## Model Yapilandirmasi

Arayuzdeki API ayarlari ekranindan bir mod secilebilir:

| Mod | Davranis |
| --- | --- |
| `cloud` | OpenAI-compatible uzak endpoint kullanir |
| `local` | Foundry Local veya yerel OpenAI-compatible endpoint kullanir |
| `hybrid` | Yerel isleri local, web ve karmasik planlamayi cloud modele yonlendirir |

ChatGPT Plus veya Business aboneligi model API anahtari yerine gecmez.
Uygulama icin saglayicinin verdigi API anahtari ya da OpenAI-compatible
endpoint gerekir.

9Router kullanan mevcut kurulumlar icin tipik base URL:
`https://api.9router.com/v1`. Saglayiciniz farkli bir URL veriyorsa panelde
onu kullanin.

## Opsiyonel Bilesenler

```powershell
# Mikrofon / PyAudio
.\venv\Scripts\python.exe -m pip install -r requirements-voice.txt

# Playwright Chromium
.\venv\Scripts\python.exe -m playwright install chromium

# Tesseract OCR
winget install UB-Mannheim.TesseractOCR
```

Mikrofon veya ses paketi kullanilamazsa uygulama kapanmaz; kalici yazili moda
gecer.

## Guvenlik Modeli

| Risk sinifi | Varsayilan onay | Ornek |
| --- | --- | --- |
| `read` | Gerekmez | Dosya okuma, sistem bilgisi |
| `external` | Gerekmez | Salt okunur web arastirmasi |
| `write` | Gerekir | Dosya veya pano yazma |
| `send` | Gerekir | Mesaj veya form gonderme |
| `execute` | Gerekir | Uygulama, hotkey, browser kontrolu |
| `delete` | Gerekir | Dosya veya kayit silme |

Web, dosya, pano, OCR ve plugin ciktilari guvenilmeyen icerik olarak
isaretlenir. Bilinmeyen tool ve plugin cagrilari varsayilan olarak engellenir.

Guvenlik aciklarini public issue olarak paylasmayin. Ayrintilar icin
[SECURITY.md](SECURITY.md) dosyasina bakin.

## Test ve Kalite Kapisi

```powershell
# Static parse, Ruff, unit test, secret scan ve surum kontrolu
powershell -ExecutionPolicy Bypass -File .\test_acceptance.ps1

# Gercek Windows UI smoke
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Smoke -SmokeTimeoutSeconds 90 -SmokeApp explorer
```

Smoke, trace, audit ve SQLite runtime ciktilari `memory/` altinda tutulur ve
Git'e eklenmez.

## Proje Yapisi

```text
actions/       Tool ve entegrasyon implementasyonlari
config/        Ornek yapilandirma
core/          Ajan, model, ses ve dispatch cekirdegi
docs/          Mimari ve yol haritasi
memory/        Kalici store kodu ve gitignored runtime verisi
plugins/       MCP plugin manifestleri
tests/         Unit ve regression testleri
ui/            Tkinter pencere ve bilesenleri
main.py        Composition root / CLI giris noktasi
```

## Katki

Katki sureci, commit standardi ve test kurallari icin
[CONTRIBUTING.md](CONTRIBUTING.md) dosyasini okuyun. Her yeni tool merkezi
guvenlik registry'sinde acik bir risk sinifina sahip olmalidir.

## Lisans

MIT License. Ayrintilar icin [LICENSE](LICENSE).
