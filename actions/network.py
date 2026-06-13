"""
Network diagnostic tools for JARVIS.

Provides ping, DNS lookup, and connectivity checks.
"""

from __future__ import annotations

import platform
import subprocess
import socket
from typing import Any


def _run_command(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    """Run a system command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {"success": False, "error": f"Command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ping_host(host: str, count: int = 4) -> dict[str, Any]:
    """
    Ping a host to check connectivity.

    Args:
        host: Hostname or IP address to ping.
        count: Number of ping packets to send.

    Returns:
        Dict with success, output, and stats.
    """
    param = "-n" if platform.system().lower() == "windows" else "-c"
    cmd = ["ping", param, str(count), host]
    return _run_command(cmd, timeout=30)


def dns_lookup(host: str) -> dict[str, Any]:
    """
    Perform a DNS lookup for a hostname.

    Args:
        host: Hostname to resolve.

    Returns:
        Dict with success, ip_addresses, and hostname.
    """
    try:
        result = socket.getaddrinfo(host, 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ips = sorted(set(
            addr[4][0] for addr in result
        ))
        return {
            "success": True,
            "hostname": host,
            "ip_addresses": ips,
            "count": len(ips),
        }
    except socket.gaierror as e:
        return {"success": False, "error": f"DNS resolution failed: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def http_check(url: str, timeout: int = 10) -> dict[str, Any]:
    """
    Check if an HTTP endpoint is reachable.

    Args:
        url: Full URL to check (e.g., https://example.com).
        timeout: Request timeout in seconds.

    Returns:
        Dict with success, status_code, and response_time.
    """
    try:
        import requests
        start = __import__("time").time()
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        elapsed = round(__import__("time").time() - start, 3)
        return {
            "success": True,
            "url": url,
            "status_code": resp.status_code,
            "response_time_s": elapsed,
            "content_length": len(resp.content),
        }
    except ImportError:
        return {"success": False, "error": "requests library not available"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": f"Request timed out after {timeout}s"}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection failed: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def whois_lookup(domain: str) -> dict[str, Any]:
    """
    Perform a WHOIS lookup for a domain.

    Args:
        domain: Domain name to look up.

    Returns:
        Dict with success and output.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["whois", domain],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = (result.stdout or result.stderr).strip()
        # Truncate long output
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return {
            "success": result.returncode == 0,
            "output": output,
        }
    except FileNotFoundError:
        return {"success": False, "error": "whois command not found on this system"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "WHOIS lookup timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def network_status() -> dict[str, Any]:
    """Check network diagnostic tool availability."""
    return {
        "available": True,
        "platform": platform.system(),
        "tools": {
            "ping": True,
            "dns": True,
            "http": True,
            "whois": True,  # whois command may not be installed
        },
    }
