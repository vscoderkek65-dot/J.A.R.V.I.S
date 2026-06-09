$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================"
Write-Host "        J.A.R.V.I.S Windows Setup"
Write-Host "========================================"
Write-Host ""

function Find-Python {
    $candidates = @("py -3", "python", "python3")
    foreach ($candidate in $candidates) {
        $parts = $candidate -split " "
        $exe = $parts[0]
        $baseArgs = @()
        if ($parts.Length -gt 1) {
            $baseArgs = $parts[1..($parts.Length - 1)]
        }

        try {
            $probe = & $exe @baseArgs -c "import sys; print(f'{sys.version_info.major}|{sys.version_info.minor}|{sys.executable}')" 2>$null
            if (-not $probe) {
                continue
            }
            $fields = $probe.Trim() -split "\|", 3
            $major = [int]$fields[0]
            $minor = [int]$fields[1]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                return @{
                    Exe = $exe
                    Args = $baseArgs
                    Version = "$major.$minor"
                    Path = $fields[2]
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11+ bulunamadi." -ForegroundColor Red
    Write-Host "Kurulum icin python.org uzerinden Python 3.11 veya daha yeni bir surum kurun."
    Write-Host "Kurulumda 'Add python.exe to PATH' secenegini isaretlemek isi kolaylastirir."
    exit 1
}

Write-Host "Python $($python.Version) bulundu: $($python.Path)" -ForegroundColor Green
$pythonExe = $python.Exe
$pythonArgs = @($python.Args)

if (-not (Test-Path "venv")) {
    Write-Host "Virtual environment olusturuluyor..."
    & $pythonExe @pythonArgs -m venv venv
}

$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "venv Python bulunamadi: $venvPython" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "config\api_keys.json")) {
    Copy-Item "config\api_keys.example.json" "config\api_keys.json"
    Write-Host "config\api_keys.json olusturuldu. Gemini API anahtarini buraya veya uygulama icindeki ayarlara girin."
}

Write-Host "pip guncelleniyor..."
& $venvPython -m pip install --upgrade pip

Write-Host "Paketler yukleniyor..."
try {
    & $venvPython -m pip install -r requirements.txt
} catch {
    Write-Host ""
    Write-Host "Paket kurulumu tamamlanamadi." -ForegroundColor Red
    Write-Host "Core paketler kurulmadan JARVIS baslatilamaz. Python surumunu ve ag baglantisini kontrol edin."
    Write-Host "Ardindan su komutu tekrar calistirin:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1"
    throw
}

Write-Host "Opsiyonel mikrofon/PyAudio kurulumu deneniyor..."
try {
    & $venvPython -m pip install -r requirements-voice.txt
    Write-Host "PyAudio kuruldu; mikrofon modu denenebilir." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "PyAudio kurulamadı; bu bloklayici degil." -ForegroundColor Yellow
    Write-Host "JARVIS text-mode ve yazili komutlarla calisir. Mikrofon icin:"
    Write-Host "  - Windows Ses Ayarlari > Giris cihazi dogru mu kontrol et"
    Write-Host "  - Python surumune uygun PyAudio wheel veya Microsoft C++ Build Tools kur"
    Write-Host "  - Sonra: .\venv\Scripts\python.exe -m pip install -r requirements-voice.txt"
}

Write-Host ""
Write-Host "Kurulum tamamlandi." -ForegroundColor Green
Write-Host ""
Write-Host "Opsiyonel ozellik notlari:"
Write-Host "- Gorunur tarayici otomasyonu icin Playwright Chromium kurulumu gerekebilir:"
Write-Host "  .\venv\Scripts\python.exe -m playwright install chromium"
Write-Host "- Yerel AI icin Microsoft Foundry Local ilk testte model ve execution provider indirebilir."
Write-Host "  JARVIS > API Ayarlari > Model Mode: Local/Hybrid > Local test et"
Write-Host "  Manuel OpenAI-compatible local endpoint kullanacaksan local URL ve modeli ayarlardan gir."
Write-Host "- Ses deneyimi: PTT Ctrl+Space ile calisir. Wake word icin ayarlardan Porcupine AccessKey veya Vosk model yolu girin."
Write-Host "  Mikrofon/PyAudio sorununda JARVIS text mode'a duser; uygulama kapanmaz."
Write-Host "- OCR icin istege bagli Tesseract kurulumu gerekir. Kurulu degilse ekran analizi vision ile devam eder, OCR notu uyarir."
Write-Host "  winget install UB-Mannheim.TesseractOCR"
Write-Host "Baslatmak icin:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\run_windows.ps1"
