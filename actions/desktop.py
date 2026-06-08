from __future__ import annotations

from dataclasses import dataclass
import time

from actions.platform_utils import IS_WINDOWS


ALLOWED_HOTKEYS = {
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+f", "ctrl+l", "ctrl+t",
    "ctrl+w", "ctrl+s", "ctrl+z", "ctrl+y", "ctrl+shift+z", "alt+tab", "win+d",
    "esc", "enter", "tab",
}


HOTKEY_ALIASES = {
    "control": "ctrl",
    "cmd": "win",
    "command": "win",
    "windows": "win",
    "escape": "esc",
    "return": "enter",
}


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    pid: int
    left: int
    top: int
    right: int
    bottom: int
    minimized: bool = False

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def matches(self, query: str, exact: bool = False) -> bool:
        folded = (query or "").casefold().strip()
        if not folded:
            return True
        haystack = f"{self.title} {self.process_name}".casefold()
        if exact:
            return folded == self.title.casefold() or folded == self.process_name.casefold()
        return folded in haystack


def _normalize_hotkey(hotkey: str) -> str:
    parts = []
    for part in (hotkey or "").replace(" ", "").split("+"):
        clean = HOTKEY_ALIASES.get(part.strip().casefold(), part.strip().casefold())
        if clean:
            parts.append(clean)
    return "+".join(parts)


def _iter_windows() -> list[WindowInfo]:
    if not IS_WINDOWS:
        return []
    import psutil  # type: ignore
    import win32gui  # type: ignore
    import win32process  # type: ignore

    windows: list[WindowInfo] = []

    def callback(hwnd, _extra):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = str(win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return True
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return True
        if max(0, right - left) < 20 or max(0, bottom - top) < 20:
            return True
        pid = 0
        process_name = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process_name = psutil.Process(pid).name()
        except Exception:
            pass
        minimized = False
        try:
            minimized = bool(win32gui.IsIconic(hwnd))
        except Exception:
            pass
        windows.append(WindowInfo(hwnd, title, process_name, pid, left, top, right, bottom, minimized))
        return True

    win32gui.EnumWindows(callback, None)
    return windows


def active_window_info() -> str:
    if not IS_WINDOWS:
        return "Aktif pencere bilgisi bu platformda sinirli destekleniyor."
    try:
        import psutil  # type: ignore
        import win32gui  # type: ignore
        import win32process  # type: ignore

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "Aktif pencere bulunamadi."
        title = str(win32gui.GetWindowText(hwnd) or "").strip()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        try:
            process_name = psutil.Process(pid).name()
        except Exception:
            pass
        return (
            "Aktif pencere:\n"
            f"- HWND: {hwnd}\n"
            f"- Baslik: {title or '(baslik yok)'}\n"
            f"- Uygulama: {process_name or 'bilinmiyor'}\n"
            f"- PID: {pid}\n"
            f"- Konum: x={left}, y={top}, w={right-left}, h={bottom-top}"
        )
    except Exception as exc:
        return f"Aktif pencere bilgisi alinamadi: {type(exc).__name__}: {exc}"


def list_windows(query: str = "", limit: int = 20) -> str:
    if not IS_WINDOWS:
        return "Pencere listeleme bu platformda sinirli destekleniyor."
    try:
        limit = max(1, min(80, int(limit or 20)))
        windows = [window for window in _iter_windows() if window.matches(query)]
        if not windows:
            label = f"'{query}' icin " if query else ""
            return f"{label}Gorunur pencere bulunamadi."
        lines = [f"Gorunur pencere sayisi: {len(windows[:limit])}"]
        for index, window in enumerate(windows[:limit], start=1):
            state = "minimized" if window.minimized else "visible"
            lines.append(
                f"- [{index}] {window.title} | {window.process_name or 'bilinmiyor'} "
                f"| hwnd={window.hwnd} pid={window.pid} | {window.width}x{window.height} | {state}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Pencere listesi alinamadi: {type(exc).__name__}: {exc}"


def focus_window(query: str, exact: bool = False) -> str:
    target = (query or "").strip()
    if not target:
        return "Odaklanacak pencere basligi veya uygulama adi belirtilmedi."
    if not IS_WINDOWS:
        return "Pencere odaklama bu platformda sinirli destekleniyor."
    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore

        matches = [window for window in _iter_windows() if window.matches(target, exact=bool(exact))]
        if not matches:
            return f"'{target}' ile eslesen pencere bulunamadi."
        window = matches[0]
        try:
            if window.minimized:
                win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(window.hwnd, win32con.SW_SHOW)
            win32gui.BringWindowToTop(window.hwnd)
            win32gui.SetForegroundWindow(window.hwnd)
            time.sleep(0.12)
        except Exception as exc:
            return (
                f"Pencere bulundu ama odaklanamadi: {window.title} "
                f"({window.process_name or 'bilinmiyor'}). Detay: {type(exc).__name__}: {exc}"
            )
        return (
            "Pencere odaklandi:\n"
            f"- Baslik: {window.title}\n"
            f"- Uygulama: {window.process_name or 'bilinmiyor'}\n"
            f"- HWND: {window.hwnd}\n"
            f"- Konum: x={window.left}, y={window.top}, w={window.width}, h={window.height}"
        )
    except Exception as exc:
        return f"Pencere odaklanamadi: {type(exc).__name__}: {exc}"


def send_hotkey_safe(hotkey: str, delay_seconds: float = 0.2) -> str:
    normalized = _normalize_hotkey(hotkey)
    if not normalized:
        return "Gonderilecek kisayol belirtilmedi."
    if normalized not in ALLOWED_HOTKEYS:
        return f"Bu kisayol guvenli listede degil: {hotkey}"
    try:
        import pyautogui  # type: ignore

        time.sleep(max(0.0, min(3.0, float(delay_seconds or 0.2))))
        parts = normalized.split("+")
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
        return f"Kisayol gonderildi: {normalized}"
    except Exception as exc:
        return f"Kisayol gonderilemedi: {type(exc).__name__}: {exc}"
