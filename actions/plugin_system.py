from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actions.audit import get_audit_logger, sanitize
from actions.mcp_client import MCPClientError, MCPServerConfig, call_tool as mcp_call_tool, list_tools as mcp_list_tools


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PLUGINS_DIR = BASE_DIR / "plugins"
DEFAULT_BUILTIN_DIR = DEFAULT_PLUGINS_DIR / "builtin"
DEFAULT_STATE_PATH = BASE_DIR / "memory" / "plugins" / "plugin_state.json"
RISK_CLASSES = {"read", "write", "send", "execute", "delete", "external"}
TRANSPORTS = {"stdio", "streamable_http", "streamable-http", "sse"}
SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|bearer|client_secret|parola|sifre)", re.IGNORECASE)
TEMPLATE_RE = re.compile(r"\$\{config\.([A-Za-z0-9_.-]+)\}")


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    description: str
    version: str
    permissions: list[str]
    risk_level: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    mcp: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _deep_merge(base: dict, updates: dict) -> dict:
    result = deepcopy(base)
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _render_templates(value: Any, config: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            key = match.group(1)
            current: Any = config
            for part in key.split("."):
                if isinstance(current, dict):
                    current = current.get(part, "")
                else:
                    current = ""
                    break
            return str(current or "")

        return TEMPLATE_RE.sub(replace, value)
    if isinstance(value, list):
        return [_render_templates(item, config) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_templates(item, config) for key, item in value.items()}
    return value


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (config or {}).items():
        if SECRET_KEY_RE.search(str(key)):
            clean[str(key)] = "***REDACTED***" if value else ""
        elif isinstance(value, dict):
            clean[str(key)] = _public_config(value)
        elif isinstance(value, list):
            clean[str(key)] = [
                _public_config(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            clean[str(key)] = value
    return clean


def validate_manifest(data: dict[str, Any], source_path: str = "") -> PluginManifest:
    if not isinstance(data, dict):
        raise ValueError("manifest JSON object olmali")
    plugin_id = str(data.get("id", "") or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]{2,80}$", plugin_id):
        raise ValueError("plugin id gecersiz")
    for key in ("name", "description", "version"):
        if not str(data.get(key, "") or "").strip():
            raise ValueError(f"manifest alani eksik: {key}")
    permissions = [str(item).strip().casefold() for item in _as_list(data.get("permissions"))]
    invalid_permissions = [item for item in permissions if item not in RISK_CLASSES]
    if invalid_permissions:
        raise ValueError(f"gecersiz permission: {', '.join(invalid_permissions)}")
    risk_level = str(data.get("risk_level", "execute") or "execute").strip().casefold()
    if risk_level not in RISK_CLASSES:
        raise ValueError(f"gecersiz risk_level: {risk_level}")
    mcp = _as_dict(data.get("mcp"))
    transport = str(mcp.get("transport", "") or "").strip().casefold()
    if transport and transport not in TRANSPORTS:
        raise ValueError(f"desteklenmeyen MCP transport: {transport}")
    tools = []
    for item in _as_list(data.get("tools")):
        if not isinstance(item, dict):
            raise ValueError("tools listesi object icermeli")
        name = str(item.get("name", "") or "").strip()
        if not re.match(r"^[A-Za-z0-9_.-]{1,120}$", name):
            raise ValueError("tool name gecersiz")
        risk = str(item.get("risk_class", risk_level) or risk_level).strip().casefold()
        if risk not in RISK_CLASSES:
            raise ValueError(f"tool risk_class gecersiz: {risk}")
        clean = dict(item)
        clean["risk_class"] = risk
        tools.append(clean)
    return PluginManifest(
        id=plugin_id,
        name=str(data.get("name", "") or "").strip(),
        description=str(data.get("description", "") or "").strip(),
        version=str(data.get("version", "") or "").strip(),
        permissions=permissions,
        risk_level=risk_level,
        config_schema=_as_dict(data.get("config_schema")),
        mcp=mcp,
        tools=tools,
        source_path=str(source_path or ""),
    )


class PluginRegistry:
    def __init__(
        self,
        plugin_dirs: list[str | Path] | None = None,
        builtin_dir: str | Path | None = None,
        state_path: str | Path | None = None,
        *,
        default_enabled: bool = False,
    ):
        self.plugin_dirs = [Path(path) for path in (plugin_dirs or [DEFAULT_PLUGINS_DIR])]
        self.builtin_dir = Path(builtin_dir) if builtin_dir else DEFAULT_BUILTIN_DIR
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.default_enabled = bool(default_enabled)

    def _manifest_paths(self) -> list[Path]:
        paths: list[Path] = []
        if self.builtin_dir.exists():
            paths.extend(sorted(self.builtin_dir.glob("*/plugin.json")))
        for directory in self.plugin_dirs:
            if not directory.exists():
                continue
            paths.extend(sorted(directory.glob("*/plugin.json")))
            paths.extend(sorted(directory.glob("builtin/*/plugin.json")))
        unique: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = str(path.resolve()).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    def load_manifests(self) -> dict[str, PluginManifest]:
        manifests: dict[str, PluginManifest] = {}
        for path in self._manifest_paths():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                manifest = validate_manifest(data, str(path))
                manifests[manifest.id] = manifest
            except Exception:
                continue
        return manifests

    def _empty_state(self) -> dict[str, Any]:
        return {"version": 1, "plugins": {}}

    def load_state(self) -> dict[str, Any]:
        state = self._empty_state()
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass
        plugins = state.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            state["plugins"] = plugins = {}
        changed = False
        for plugin_id in self.load_manifests():
            if plugin_id not in plugins or not isinstance(plugins.get(plugin_id), dict):
                plugins[plugin_id] = {
                    "enabled": self.default_enabled,
                    "config": {},
                    "discovered_tools": [],
                    "last_error": "",
                    "updated_at": _now_iso(),
                }
                changed = True
        if changed:
            self.save_state(state)
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _plugin_state(self, plugin_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self.load_state()
        plugin_state = state.setdefault("plugins", {}).setdefault(str(plugin_id), {})
        if not isinstance(plugin_state, dict):
            plugin_state = {}
            state["plugins"][str(plugin_id)] = plugin_state
        plugin_state.setdefault("enabled", self.default_enabled)
        plugin_state.setdefault("config", {})
        plugin_state.setdefault("discovered_tools", [])
        plugin_state.setdefault("last_error", "")
        plugin_state.setdefault("updated_at", _now_iso())
        return plugin_state

    def list_plugins(self) -> str:
        manifests = self.load_manifests()
        state = self.load_state()
        if not manifests:
            return "Plugin manifesti bulunamadi. plugins/*/plugin.json ekleyebilirsin."
        lines = ["Pluginler:"]
        for plugin_id in sorted(manifests):
            manifest = manifests[plugin_id]
            plugin_state = self._plugin_state(plugin_id, state)
            enabled = "acik" if plugin_state.get("enabled") else "kapali"
            tool_count = len(plugin_state.get("discovered_tools") or manifest.tools or [])
            perms = ", ".join(manifest.permissions) or "-"
            lines.append(
                f"- {manifest.id}: {enabled} | risk={manifest.risk_level} | izinler={perms} | tool={tool_count} | {manifest.description}"
            )
        return "\n".join(lines)

    def plugin_status(self, plugin_id: str = "") -> str:
        manifests = self.load_manifests()
        state = self.load_state()
        clean_id = str(plugin_id or "").strip()
        if not clean_id:
            return self.list_plugins()
        manifest = manifests.get(clean_id)
        if not manifest:
            return f"Plugin bulunamadi: {clean_id}"
        plugin_state = self._plugin_state(clean_id, state)
        public = {
            "enabled": bool(plugin_state.get("enabled")),
            "permissions": manifest.permissions,
            "risk_level": manifest.risk_level,
            "config": _public_config(_as_dict(plugin_state.get("config"))),
            "discovered_tools": plugin_state.get("discovered_tools") or [],
            "last_error": plugin_state.get("last_error", ""),
            "source_path": manifest.source_path,
        }
        return json.dumps(public, ensure_ascii=False, indent=2)

    def enable_plugin(self, plugin_id: str) -> str:
        manifests = self.load_manifests()
        clean_id = str(plugin_id or "").strip()
        manifest = manifests.get(clean_id)
        if not manifest:
            self._audit_block("enable_plugin", clean_id, "Plugin registry disi")
            return f"Plugin bulunamadi veya registry disi: {clean_id or '-'}"
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        plugin_state["enabled"] = True
        plugin_state["updated_at"] = _now_iso()
        plugin_state["last_error"] = ""
        self.save_state(state)
        return (
            f"Plugin acildi: {manifest.id} ({manifest.name})\n"
            f"Izinler: {', '.join(manifest.permissions) or '-'} | risk={manifest.risk_level}"
        )

    def disable_plugin(self, plugin_id: str) -> str:
        clean_id = str(plugin_id or "").strip()
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        plugin_state["enabled"] = False
        plugin_state["updated_at"] = _now_iso()
        self.save_state(state)
        return f"Plugin kapatildi: {clean_id or '-'}"

    def set_config(self, plugin_id: str, config: dict | str | None = None, merge: bool = True) -> str:
        manifests = self.load_manifests()
        clean_id = str(plugin_id or "").strip()
        manifest = manifests.get(clean_id)
        if not manifest:
            self._audit_block("set_plugin_config", clean_id, "Plugin registry disi")
            return f"Plugin bulunamadi veya registry disi: {clean_id or '-'}"
        updates = _as_dict(config)
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        current = _as_dict(plugin_state.get("config"))
        plugin_state["config"] = _deep_merge(current, updates) if merge else updates
        plugin_state["updated_at"] = _now_iso()
        missing = self._missing_required_config(manifest, _as_dict(plugin_state.get("config")))
        plugin_state["last_error"] = f"Eksik config: {', '.join(missing)}" if missing else ""
        self.save_state(state)
        public = _public_config(_as_dict(plugin_state.get("config")))
        suffix = f"\nEksik config: {', '.join(missing)}" if missing else ""
        return f"Plugin config kaydedildi: {clean_id}\n{json.dumps(public, ensure_ascii=False, indent=2)}{suffix}"

    def discover_tools(self, plugin_id: str) -> str:
        clean_id = str(plugin_id or "").strip()
        manifests = self.load_manifests()
        manifest = manifests.get(clean_id)
        if not manifest:
            self._audit_block("discover_plugin_tools", clean_id, "Plugin registry disi")
            return f"Plugin bulunamadi veya registry disi: {clean_id or '-'}"
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        if not plugin_state.get("enabled"):
            return f"Plugin kapali: {clean_id}. Once enable_plugin kullan."
        try:
            tools = self._discover_tools_for(manifest, _as_dict(plugin_state.get("config")))
            plugin_state["discovered_tools"] = tools
            plugin_state["last_error"] = ""
            plugin_state["updated_at"] = _now_iso()
            self.save_state(state)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            plugin_state["last_error"] = error
            self.save_state(state)
            return f"Plugin tool kesfi basarisiz: {clean_id} - {error}"
        if not tools:
            return f"Plugin aktif ama tool bulunamadi: {clean_id}"
        lines = [f"{clean_id} MCP/tool kesfi:"]
        for tool in tools:
            risk = tool.get("risk_class") or manifest.risk_level
            lines.append(f"- {tool.get('name', '-')}: risk={risk} | {tool.get('description', '')}")
        return "\n".join(lines)

    def call_plugin_tool(self, plugin_id: str, tool_name: str, arguments: dict | str | None = None) -> str:
        clean_id = str(plugin_id or "").strip()
        clean_tool = str(tool_name or "").strip()
        manifests = self.load_manifests()
        manifest = manifests.get(clean_id)
        if not manifest:
            self._audit_block("call_plugin_tool", clean_id, f"Plugin registry disi: {clean_tool}")
            return f"Plugin bulunamadi veya registry disi: {clean_id or '-'}"
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        if not plugin_state.get("enabled"):
            return f"Plugin kapali: {clean_id}. Once enable_plugin kullan."
        tool = self.find_tool(manifest, plugin_state, clean_tool)
        if not tool:
            self._audit_block("call_plugin_tool", clean_id, f"Registry disi plugin tool: {clean_tool}")
            return f"Plugin tool registry disi veya kesfedilmedi: {clean_id}/{clean_tool or '-'}"
        config = _as_dict(plugin_state.get("config"))
        server_config = self._server_config(manifest, config)
        if not server_config:
            return f"{clean_id} icin MCP server config eksik. set_plugin_config ile command/url gir."
        try:
            result = mcp_call_tool(server_config, clean_tool, _as_dict(arguments))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            plugin_state["last_error"] = error
            self.save_state(state)
            return f"Plugin tool cagrisi basarisiz: {clean_id}/{clean_tool} - {error}"
        plugin_state["last_error"] = ""
        plugin_state["updated_at"] = _now_iso()
        self.save_state(state)
        text = str(result.get("text") or "").strip()
        if text:
            return f"[Untrusted MCP content: {clean_id}/{clean_tool}]\n{text}"
        return f"[Untrusted MCP content: {clean_id}/{clean_tool}]\n" + json.dumps(
            result.get("raw", result),
            ensure_ascii=False,
            indent=2,
        )

    def plugin_tool_policy(self, plugin_id: str, tool_name: str) -> dict[str, Any]:
        clean_id = str(plugin_id or "").strip()
        clean_tool = str(tool_name or "").strip()
        manifests = self.load_manifests()
        manifest = manifests.get(clean_id)
        if not manifest:
            return {
                "blocked": True,
                "risk_class": "execute",
                "requires_approval": True,
                "summary": f"Registry disi plugin/tool cagrisi engellendi: {clean_id or '-'}/{clean_tool or '-'}",
            }
        state = self.load_state()
        plugin_state = self._plugin_state(clean_id, state)
        if not plugin_state.get("enabled"):
            return {
                "blocked": True,
                "risk_class": "execute",
                "requires_approval": True,
                "summary": f"Kapali plugin tool cagrisi engellendi: {clean_id}/{clean_tool or '-'}",
            }
        tool = self.find_tool(manifest, plugin_state, clean_tool)
        if not tool:
            return {
                "blocked": True,
                "risk_class": "execute",
                "requires_approval": True,
                "summary": f"Registry disi plugin tool cagrisi engellendi: {clean_id}/{clean_tool or '-'}",
            }
        risk = str(tool.get("risk_class") or manifest.risk_level or "execute").casefold()
        if risk not in RISK_CLASSES:
            risk = "execute"
        explicit = tool.get("requires_approval")
        requires_approval = risk in {"write", "send", "execute", "delete"} or bool(explicit)
        return {
            "blocked": False,
            "risk_class": risk,
            "requires_approval": requires_approval,
            "summary": f"Plugin tool calistir: {clean_id}/{clean_tool}",
        }

    def find_tool(self, manifest: PluginManifest, plugin_state: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
        clean_tool = str(tool_name or "").strip()
        for source in (manifest.tools, _as_list(plugin_state.get("discovered_tools"))):
            for item in source:
                if isinstance(item, dict) and str(item.get("name", "") or "").strip() == clean_tool:
                    merged = dict(item)
                    merged.setdefault("risk_class", manifest.risk_level)
                    return merged
        return None

    def _discover_tools_for(self, manifest: PluginManifest, config: dict[str, Any]) -> list[dict[str, Any]]:
        server_config = self._server_config(manifest, config)
        if not server_config:
            return [self._normalize_static_tool(manifest, item) for item in manifest.tools]
        discovered = mcp_list_tools(server_config)
        tools = []
        for item in discovered:
            if not item.get("name"):
                continue
            clean = dict(item)
            clean.setdefault("risk_class", manifest.risk_level or "execute")
            clean.setdefault("requires_approval", clean["risk_class"] in {"write", "send", "execute", "delete"})
            tools.append(clean)
        return tools

    def _normalize_static_tool(self, manifest: PluginManifest, item: dict[str, Any]) -> dict[str, Any]:
        clean = dict(item)
        clean.setdefault("description", "")
        clean.setdefault("input_schema", clean.get("inputSchema") or {})
        clean.setdefault("risk_class", manifest.risk_level)
        clean.setdefault("requires_approval", clean["risk_class"] in {"write", "send", "execute", "delete"})
        return clean

    def _server_config(self, manifest: PluginManifest, config: dict[str, Any]) -> MCPServerConfig | None:
        mcp = _deep_merge(manifest.mcp, _as_dict(config.get("mcp")))
        for key in ("transport", "command", "args", "env", "url", "headers", "timeout_seconds"):
            if key in config:
                mcp[key] = config[key]
        mcp = _render_templates(mcp, config)
        transport = str(mcp.get("transport", "") or "").strip().casefold()
        if not transport:
            return None
        if transport not in TRANSPORTS:
            raise MCPClientError(f"Desteklenmeyen MCP transport: {transport}")
        args = tuple(str(item) for item in _as_list(mcp.get("args")))
        env = {str(k): str(v) for k, v in _as_dict(mcp.get("env")).items()}
        headers = {str(k): str(v) for k, v in _as_dict(mcp.get("headers")).items()}
        return MCPServerConfig(
            transport=transport,
            command=str(mcp.get("command", "") or "").strip(),
            args=args,
            env=env,
            url=str(mcp.get("url", "") or "").strip(),
            headers=headers,
            timeout_seconds=float(mcp.get("timeout_seconds", 30) or 30),
        )

    def _missing_required_config(self, manifest: PluginManifest, config: dict[str, Any]) -> list[str]:
        schema = manifest.config_schema or {}
        required = _as_list(schema.get("required"))
        missing = []
        for key in required:
            key_str = str(key)
            if not str(config.get(key_str, "") or "").strip():
                missing.append(key_str)
        return missing

    def _audit_block(self, tool_name: str, plugin_id: str, summary: str) -> None:
        try:
            get_audit_logger().log(
                "blocked",
                tool_name=tool_name,
                risk_class="execute",
                args=sanitize({"plugin_id": plugin_id}),
                summary=summary,
                status="blocked",
            )
        except Exception:
            pass


_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        try:
            from app_config import load_app_config

            config = load_app_config()
            raw_dirs = config.get("plugin_dirs") or ["plugins"]
            dirs = []
            for item in _as_list(raw_dirs):
                path = Path(str(item))
                dirs.append(path if path.is_absolute() else BASE_DIR / path)
            _registry = PluginRegistry(
                plugin_dirs=dirs or [DEFAULT_PLUGINS_DIR],
                default_enabled=bool(config.get("plugins_enabled_default", False)),
            )
        except Exception:
            _registry = PluginRegistry()
    return _registry


def set_plugin_registry(registry: PluginRegistry | None) -> None:
    global _registry
    _registry = registry


def list_plugins() -> str:
    return get_plugin_registry().list_plugins()


def plugin_status(plugin_id: str = "") -> str:
    return get_plugin_registry().plugin_status(plugin_id)


def enable_plugin(plugin_id: str) -> str:
    return get_plugin_registry().enable_plugin(plugin_id)


def disable_plugin(plugin_id: str) -> str:
    return get_plugin_registry().disable_plugin(plugin_id)


def set_plugin_config(plugin_id: str, config: dict | str | None = None, merge: bool = True) -> str:
    return get_plugin_registry().set_config(plugin_id, config, merge)


def discover_plugin_tools(plugin_id: str) -> str:
    return get_plugin_registry().discover_tools(plugin_id)


def call_plugin_tool(plugin_id: str, tool_name: str, arguments: dict | str | None = None) -> str:
    return get_plugin_registry().call_plugin_tool(plugin_id, tool_name, arguments)


def plugin_tool_policy(plugin_id: str, tool_name: str) -> dict[str, Any]:
    return get_plugin_registry().plugin_tool_policy(plugin_id, tool_name)
