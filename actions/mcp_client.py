from __future__ import annotations

import asyncio
import datetime as dt
import threading
from dataclasses import dataclass
from typing import Any


class MCPClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPServerConfig:
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    url: str = ""
    headers: dict[str, str] | None = None
    timeout_seconds: float = 30.0


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump())
    if hasattr(value, "dict"):
        return _serialize(value.dict())
    attrs = {}
    for key in ("name", "description", "inputSchema", "input_schema", "annotations"):
        if hasattr(value, key):
            attrs[key] = _serialize(getattr(value, key))
    return attrs or str(value)


def _timeout_seconds(value: float | int | None) -> float:
    try:
        seconds = float(value or 30.0)
    except Exception:
        seconds = 30.0
    return max(0.001, seconds)


async def _with_timeout(coro, timeout_seconds: float):
    return await asyncio.wait_for(coro, timeout=timeout_seconds)


def _run_async(coro, timeout_seconds: float = 30.0):
    timeout = _timeout_seconds(timeout_seconds)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_with_timeout(coro, timeout))
        except asyncio.TimeoutError as exc:
            raise MCPClientError(f"MCP islemi zaman asimina ugradi ({timeout:.1f}s).") from exc

    holder: dict[str, Any] = {}

    def worker():
        try:
            holder["result"] = asyncio.run(_with_timeout(coro, timeout))
        except BaseException as exc:
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout + 0.25)
    if thread.is_alive():
        raise MCPClientError(f"MCP islemi zaman asimina ugradi ({timeout:.1f}s).")
    if "error" in holder:
        if isinstance(holder["error"], asyncio.TimeoutError):
            raise MCPClientError(f"MCP islemi zaman asimina ugradi ({timeout:.1f}s).") from holder["error"]
        raise holder["error"]
    return holder.get("result")


def _load_sdk():
    try:
        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore
    except Exception as exc:
        raise MCPClientError(
            "MCP Python SDK bulunamadi. setup_windows.ps1 calistir veya `pip install \"mcp[cli]\"` kur."
        ) from exc
    return ClientSession, StdioServerParameters, stdio_client


def _load_streamable_http_client():
    try:
        from mcp.client.streamable_http import streamablehttp_client  # type: ignore

        return streamablehttp_client
    except Exception:
        try:
            from mcp.client.streamable_http import streamable_http_client  # type: ignore

            return streamable_http_client
        except Exception as exc:
            raise MCPClientError("MCP Streamable HTTP client bu SDK kurulumunda bulunamadi.") from exc


def _timeout(config: MCPServerConfig) -> dt.timedelta:
    seconds = max(1.0, float(config.timeout_seconds or 30.0))
    return dt.timedelta(seconds=seconds)


async def _list_tools_async(config: MCPServerConfig) -> list[dict]:
    ClientSession, StdioServerParameters, stdio_client = _load_sdk()
    transport = (config.transport or "").strip().casefold()

    if transport == "stdio":
        if not config.command:
            raise MCPClientError("stdio MCP icin command zorunlu.")
        server_params = StdioServerParameters(
            command=config.command,
            args=list(config.args or ()),
            env=dict(config.env or {}),
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(session.list_tools(), timeout=_timeout(config).total_seconds())
                return [_normalize_tool(tool) for tool in getattr(result, "tools", [])]

    if transport in {"streamable_http", "streamable-http"}:
        if not config.url:
            raise MCPClientError("Streamable HTTP MCP icin url zorunlu.")
        http_client = _load_streamable_http_client()
        async with http_client(config.url, headers=dict(config.headers or {})) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(session.list_tools(), timeout=_timeout(config).total_seconds())
                return [_normalize_tool(tool) for tool in getattr(result, "tools", [])]

    if transport == "sse":
        try:
            from mcp.client.sse import sse_client  # type: ignore
        except Exception as exc:
            raise MCPClientError("Legacy SSE bu MCP SDK kurulumunda desteklenmiyor.") from exc
        if not config.url:
            raise MCPClientError("SSE MCP icin url zorunlu.")
        async with sse_client(config.url, headers=dict(config.headers or {})) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(session.list_tools(), timeout=_timeout(config).total_seconds())
                return [_normalize_tool(tool) for tool in getattr(result, "tools", [])]

    raise MCPClientError(f"Desteklenmeyen MCP transport: {config.transport}")


async def _call_tool_async(config: MCPServerConfig, tool_name: str, arguments: dict) -> dict:
    ClientSession, StdioServerParameters, stdio_client = _load_sdk()
    transport = (config.transport or "").strip().casefold()

    if transport == "stdio":
        if not config.command:
            raise MCPClientError("stdio MCP icin command zorunlu.")
        server_params = StdioServerParameters(
            command=config.command,
            args=list(config.args or ()),
            env=dict(config.env or {}),
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments or {}),
                    timeout=_timeout(config).total_seconds(),
                )
                return _normalize_call_result(result)

    if transport in {"streamable_http", "streamable-http"}:
        if not config.url:
            raise MCPClientError("Streamable HTTP MCP icin url zorunlu.")
        http_client = _load_streamable_http_client()
        async with http_client(config.url, headers=dict(config.headers or {})) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments or {}),
                    timeout=_timeout(config).total_seconds(),
                )
                return _normalize_call_result(result)

    if transport == "sse":
        try:
            from mcp.client.sse import sse_client  # type: ignore
        except Exception as exc:
            raise MCPClientError("Legacy SSE bu MCP SDK kurulumunda desteklenmiyor.") from exc
        if not config.url:
            raise MCPClientError("SSE MCP icin url zorunlu.")
        async with sse_client(config.url, headers=dict(config.headers or {})) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments or {}),
                    timeout=_timeout(config).total_seconds(),
                )
                return _normalize_call_result(result)

    raise MCPClientError(f"Desteklenmeyen MCP transport: {config.transport}")


def _normalize_tool(tool: Any) -> dict:
    data = _serialize(tool)
    if not isinstance(data, dict):
        return {"name": str(tool), "description": "", "input_schema": {}}
    input_schema = data.get("inputSchema") or data.get("input_schema") or {}
    return {
        "name": str(data.get("name", "") or ""),
        "description": str(data.get("description", "") or ""),
        "input_schema": _serialize(input_schema) if isinstance(input_schema, dict) else {},
    }


def _normalize_call_result(result: Any) -> dict:
    data = _serialize(result)
    content = data.get("content") if isinstance(data, dict) else None
    text_parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item.get("text")))
                elif item.get("text"):
                    text_parts.append(str(item.get("text")))
            elif item:
                text_parts.append(str(item))
    return {
        "is_error": bool(data.get("isError") or data.get("is_error")) if isinstance(data, dict) else False,
        "text": "\n".join(text_parts).strip(),
        "raw": data,
    }


def list_tools(config: MCPServerConfig) -> list[dict]:
    return _run_async(_list_tools_async(config), timeout_seconds=_timeout(config).total_seconds())


def call_tool(config: MCPServerConfig, tool_name: str, arguments: dict | None = None) -> dict:
    clean_name = str(tool_name or "").strip()
    if not clean_name:
        raise MCPClientError("MCP tool adi bos olamaz.")
    return _run_async(_call_tool_async(config, clean_name, dict(arguments or {})), timeout_seconds=_timeout(config).total_seconds())
