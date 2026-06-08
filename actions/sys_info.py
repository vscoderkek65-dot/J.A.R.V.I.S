"""
Cross-platform system information helpers.
"""

from __future__ import annotations

import datetime
import os
import platform
import socket
import subprocess
from pathlib import Path

from actions.platform_utils import IS_MACOS, IS_WINDOWS

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def sys_info(query: str) -> str:
    query = (query or "all").lower().strip()
    results: list[str] = []

    if query in ("battery", "pil", "all"):
        results.append(_battery())
    if query in ("cpu", "islemci", "işlemci", "all"):
        results.append(_cpu())
    if query in ("ram", "bellek", "memory", "all"):
        results.append(_ram())
    if query in ("disk", "depolama", "all"):
        results.append(_disk())
    if query in ("time", "saat", "zaman", "all"):
        now = datetime.datetime.now()
        results.append(f"Saat: {now.strftime('%H:%M:%S')}")
    if query in ("date", "tarih", "all"):
        now = datetime.datetime.now()
        results.append(f"Tarih: {now.strftime('%d %B %Y, %A')}")
    if query in ("network", "ag", "ağ", "wifi", "all"):
        results.append(_network())
    if query in ("os", "sistem", "platform", "all"):
        results.append(_os_info())

    if not results:
        results.append(f"Bilinmeyen sorgu: {query}. battery/cpu/ram/disk/time/date/network/os/all kullanin.")

    return "\n".join(item for item in results if item)


def _battery() -> str:
    if HAS_PSUTIL:
        bat = psutil.sensors_battery()
        if bat:
            status = "Sarj oluyor" if bat.power_plugged else "Pilde"
            return f"Pil: %{bat.percent:.0f} - {status}"

    if IS_MACOS:
        try:
            out = subprocess.check_output(["pmset", "-g", "batt"], text=True, timeout=5)
            for line in out.splitlines():
                if "%" in line:
                    return f"Pil: {line.strip()}"
        except Exception:
            pass

    return "Pil bilgisi alinamadi."


def _cpu() -> str:
    if HAS_PSUTIL:
        usage = psutil.cpu_percent(interval=0.5)
        count = psutil.cpu_count(logical=True)
        freq = psutil.cpu_freq()
        freq_str = f", {freq.current:.0f} MHz" if freq else ""
        return f"CPU: %{usage:.1f} kullanim - {count} cekirdek{freq_str}"

    if IS_MACOS:
        try:
            out = subprocess.check_output(["top", "-l", "1", "-n", "0", "-s", "0"], text=True, timeout=5)
            for line in out.splitlines():
                if "CPU usage" in line:
                    return f"CPU: {line.strip()}"
        except Exception:
            pass

    return "CPU bilgisi alinamadi."


def _ram() -> str:
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        total = vm.total / (1024**3)
        used = vm.used / (1024**3)
        return f"RAM: {used:.1f}GB / {total:.1f}GB kullanimda (%{vm.percent:.0f})"
    return "RAM bilgisi alinamadi."


def _disk() -> str:
    target = os.environ.get("SystemDrive", "C:") + "\\" if IS_WINDOWS else "/"
    if HAS_PSUTIL:
        du = psutil.disk_usage(target)
        total = du.total / (1024**3)
        used = du.used / (1024**3)
        free = du.free / (1024**3)
        return f"Disk ({target}): {used:.1f}GB kullanildi, {free:.1f}GB bos (toplam {total:.1f}GB)"

    try:
        out = subprocess.check_output(["df", "-h", target], text=True, timeout=5)
        lines = out.strip().splitlines()
        if len(lines) >= 2:
            return f"Disk: {lines[1]}"
    except Exception:
        pass
    return "Disk bilgisi alinamadi."


def _network() -> str:
    ssid = _wifi_ssid()
    ip = _primary_ip()
    if ssid and ip:
        return f"WiFi: {ssid} - IP {ip}"
    if ssid:
        return f"WiFi: {ssid} bagli"
    if ip:
        return f"Ag: IP {ip}"
    return "Ag baglantisi bulunamadi."


def _wifi_ssid() -> str:
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if key.strip().lower() == "ssid" and value.strip():
                    return value.strip()
        except Exception:
            return ""

    if IS_MACOS:
        try:
            out = subprocess.check_output(
                ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if " SSID:" in line:
                    return line.split("SSID:")[-1].strip()
        except Exception:
            return ""

    return ""


def _primary_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        pass

    if HAS_PSUTIL:
        for addresses in psutil.net_if_addrs().values():
            for address in addresses:
                if getattr(address, "family", None) == socket.AF_INET and not address.address.startswith("127."):
                    return address.address
    return ""


def _os_info() -> str:
    release = platform.release()
    version = platform.version()
    machine = platform.machine()
    host = platform.node() or socket.gethostname()
    home = str(Path.home())
    return f"Sistem: {platform.system()} {release} ({machine}) - {host} - Home: {home} - Build: {version}"
