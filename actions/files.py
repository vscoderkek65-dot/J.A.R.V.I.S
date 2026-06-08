from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path

from actions.platform_utils import open_url


BASE_DIR = Path(__file__).resolve().parent.parent
HOME_DIR = Path.home()
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".csv", ".log", ".html", ".css", ".xml", ".sql",
}
MAX_READ_BYTES = 180_000
MAX_RESULTS = 40


def _named_location(name: str) -> Path | None:
    key = (name or "").strip().casefold()
    mapping = {
        "desktop": HOME_DIR / "Desktop",
        "masaustu": HOME_DIR / "Desktop",
        "masaüstü": HOME_DIR / "Desktop",
        "downloads": HOME_DIR / "Downloads",
        "indirilenler": HOME_DIR / "Downloads",
        "documents": HOME_DIR / "Documents",
        "belgeler": HOME_DIR / "Documents",
        "home": HOME_DIR,
        "ev": HOME_DIR,
        "workspace": BASE_DIR,
        "proje": BASE_DIR,
    }
    return mapping.get(key)


def _resolve_path(raw_path: str = "") -> Path:
    raw = (raw_path or "").strip().strip('"')
    if not raw:
        return HOME_DIR
    named = _named_location(raw)
    if named:
        return named
    expanded = os.path.expandvars(os.path.expanduser(raw))
    path = Path(expanded)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _is_probably_text(path: Path) -> bool:
    if path.suffix.casefold() in TEXT_EXTENSIONS:
        return True
    try:
        sample = path.read_bytes()[:4096]
    except Exception:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except Exception:
        return False


def _format_entry(path: Path) -> str:
    try:
        stat = path.stat()
        size = stat.st_size
    except Exception:
        size = 0
    kind = "DIR " if path.is_dir() else "FILE"
    return f"{kind} {path} ({size} bytes)"


def list_folder(path: str = "", limit: int = 60) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Klasor bulunamadi: {target}"
    if not target.is_dir():
        return f"Bu bir klasor degil: {target}"

    limit = max(1, min(200, int(limit or 60)))
    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))[:limit]
    if not entries:
        return f"Klasor bos: {target}"
    lines = [f"{target} icindeki ilk {len(entries)} oge:"]
    lines.extend(f"- {_format_entry(entry)}" for entry in entries)
    return "\n".join(lines)


def find_files(query: str, path: str = "", limit: int = MAX_RESULTS) -> str:
    needle = (query or "").strip()
    if not needle:
        return "Aranacak dosya adi veya kalip gerekli."
    root = _resolve_path(path)
    if not root.exists() or not root.is_dir():
        return f"Arama klasoru bulunamadi: {root}"

    limit = max(1, min(100, int(limit or MAX_RESULTS)))
    folded = needle.casefold()
    pattern = folded if any(ch in folded for ch in "*?") else f"*{folded}*"
    matches: list[Path] = []
    skipped = 0

    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"venv", ".venv", "__pycache__", ".git", "node_modules"}]
        for name in [*dirnames, *filenames]:
            if fnmatch.fnmatch(name.casefold(), pattern):
                matches.append(Path(current) / name)
                if len(matches) >= limit:
                    break
        if len(matches) >= limit:
            break
        skipped += 1
        if skipped > 5000:
            break

    if not matches:
        return f"'{needle}' icin {root} altinda sonuc bulunamadi."
    lines = [f"'{needle}' icin {len(matches)} sonuc:"]
    lines.extend(f"- {_format_entry(match)}" for match in matches)
    return "\n".join(lines)


def read_text_file(path: str, max_chars: int = 12000) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Dosya bulunamadi: {target}"
    if not target.is_file():
        return f"Bu bir dosya degil: {target}"
    if target.stat().st_size > MAX_READ_BYTES:
        return f"Dosya cok buyuk ({target.stat().st_size} bytes). Once daha dar bir dosya sec."
    if not _is_probably_text(target):
        return f"Dosya metin gibi gorunmuyor, guvenli okumayi atladim: {target}"

    max_chars = max(500, min(40000, int(max_chars or 12000)))
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_text(encoding="cp1254", errors="replace")
    if len(content) > max_chars:
        content = content[:max_chars] + "\n... (dosya kirpildi)"
    return f"{target} icerigi:\n{content}"


def summarize_text_file(path: str, max_chars: int = 16000) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Dosya bulunamadi: {target}"
    if not target.is_file():
        return f"Bu bir dosya degil: {target}"
    if target.stat().st_size > MAX_READ_BYTES:
        return f"Dosya cok buyuk ({target.stat().st_size} bytes). Once daha dar bir dosya sec."
    if not _is_probably_text(target):
        return f"Dosya metin gibi gorunmuyor, ozetlemeyi atladim: {target}"

    max_chars = max(1000, min(50000, int(max_chars or 16000)))
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_text(encoding="cp1254", errors="replace")

    clipped = content[:max_chars]
    words = clipped.split()
    lines = [line.rstrip() for line in clipped.splitlines()]
    non_empty = [line.strip() for line in lines if line.strip()]
    headings = [
        line.strip()
        for line in non_empty
        if line.lstrip().startswith(("#", "class ", "def ", "function ", "async def "))
    ][:8]
    preview = " ".join(words[:120])
    if len(words) > 120:
        preview += " ..."

    result = [
        f"Dosya ozeti: {target}",
        f"- Boyut: {target.stat().st_size} bytes",
        f"- Okunan: {len(clipped)} karakter, {len(non_empty)} dolu satir, {len(words)} kelime",
    ]
    if len(content) > len(clipped):
        result.append("- Not: Dosya kirpildi; daha fazla detay icin max_chars artirilabilir.")
    if headings:
        result.append("- Baslik/yapi ipuclari:")
        result.extend(f"  - {heading[:180]}" for heading in headings)
    result.append(f"- Onizleme: {preview}")
    return "\n".join(result)


def open_file(path: str) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Dosya veya klasor bulunamadi: {target}"
    open_url(str(target))
    return f"Acildi: {target}"


def create_folder(path: str) -> str:
    target = _resolve_path(path)
    if target.exists():
        if target.is_dir():
            return f"Klasor zaten var: {target}"
        return f"Ayni yolda dosya var, klasor olusturulamadi: {target}"
    target.mkdir(parents=True, exist_ok=False)
    return f"Klasor olusturuldu: {target}"


def create_text_file(path: str, content: str = "", overwrite: bool = False) -> str:
    target = _resolve_path(path)
    if target.exists() and not overwrite:
        return f"Dosya zaten var, uzerine yazmak icin overwrite=true gerekli: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content or ""), encoding="utf-8")
    return f"Dosya olusturuldu: {target}"


def write_text_file(path: str, content: str, overwrite: bool = True) -> str:
    target = _resolve_path(path)
    if target.exists() and target.is_dir():
        return f"Bu bir klasor, dosya olarak yazilamaz: {target}"
    if target.exists() and not overwrite:
        return f"Dosya zaten var, uzerine yazmak icin overwrite=true gerekli: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content or ""), encoding="utf-8")
    return f"Dosyaya yazildi: {target}"


def append_text_file(path: str, content: str) -> str:
    target = _resolve_path(path)
    if target.exists() and target.is_dir():
        return f"Bu bir klasor, dosya olarak yazilamaz: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(str(content or ""))
    return f"Dosyaya eklendi: {target}"


def move_file(source_path: str, destination_path: str, overwrite: bool = False) -> str:
    source = _resolve_path(source_path)
    destination = _resolve_path(destination_path)
    if not source.exists():
        return f"Kaynak bulunamadi: {source}"
    if destination.exists() and not overwrite:
        return f"Hedef zaten var, tasimak icin overwrite=true gerekli: {destination}"
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return f"Tasindi: {source} -> {destination}"


def delete_file(path: str, recursive: bool = False) -> str:
    target = _resolve_path(path)
    if not target.exists():
        return f"Silinecek dosya veya klasor bulunamadi: {target}"
    if target.is_dir():
        if recursive:
            shutil.rmtree(target)
            return f"Klasor ve icerigi silindi: {target}"
        try:
            target.rmdir()
            return f"Bos klasor silindi: {target}"
        except OSError:
            return f"Klasor bos degil, silmek icin recursive=true gerekli: {target}"
    target.unlink()
    return f"Dosya silindi: {target}"
