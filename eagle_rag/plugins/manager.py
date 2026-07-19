"""Plugin manager: discover, validate, load, and expose plugin capabilities."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from eagle_rag.config import Settings, get_settings
from eagle_rag.plugins.collection_registry import CollectionStoreRegistry
from eagle_rag.plugins.context import PluginAudit, PluginContext
from eagle_rag.plugins.contract import Plugin, PluginManifest
from eagle_rag.plugins.encoder_registry import EncoderRegistry
from eagle_rag.plugins.errors import PluginLoadError
from eagle_rag.plugins.hookbus import HookBus
from eagle_rag.telemetry import get_logger

__all__ = ["LoadedPlugin", "PluginManager"]

logger = get_logger(__name__)

_CORE_DEFAULTS_MODULE = "eagle_rag.plugins.core_defaults"


@dataclass
class LoadedPlugin:
    """Runtime record for a loaded plugin."""

    module_path: str
    plugin: Plugin
    manifest: PluginManifest


class PluginManager:
    """Loads in-repo plugins from ``settings.plugins.enabled``."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.audit = PluginAudit.from_settings(self._settings)
        self.bus = HookBus(audit=self.audit)
        self.encoder_registry = EncoderRegistry()
        self.collection_registry = CollectionStoreRegistry()
        self._loaded: list[LoadedPlugin] = []
        self._pipeline_registry: dict[str, Any] = {}
        self._mcp_tools: list[dict[str, Any]] = []
        self._mcp_tools_registered = False
        self._celery_modules: list[str] = []
        self._bootstrapped = False

    @property
    def default_namespace(self) -> str:
        return self._settings.plugins.default_namespace

    def load_all(self) -> None:
        """Discover and load all enabled plugins (idempotent)."""
        if self._bootstrapped:
            return
        enabled = list(self._settings.plugins.enabled)
        if _CORE_DEFAULTS_MODULE not in enabled:
            enabled.insert(0, _CORE_DEFAULTS_MODULE)

        manifests: dict[str, PluginManifest] = {}
        plugins: dict[str, tuple[str, Plugin]] = {}

        for module_path in enabled:
            plugin = self._import_plugin(module_path)
            ns = plugin.manifest.namespace
            if ns in plugins:
                raise PluginLoadError(f"duplicate plugin namespace: {ns}")
            manifests[ns] = plugin.manifest
            plugins[ns] = (module_path, plugin)

        self._validate_namespace_g3(manifests)
        order = self._resolve_deps(manifests)

        for ns in order:
            module_path, plugin = plugins[ns]
            ctx = PluginContext(
                plugin_namespace=ns,
                default_namespace=self.default_namespace,
                settings=self._settings,
                bus=self.bus,
                encoder_registry=self.encoder_registry,
                collection_registry=self.collection_registry,
                audit=self.audit,
                register_pipeline=self.register_pipeline,
            )
            try:
                plugin.on_load(ctx)
                plugin.ensure_collections(ctx)
            except Exception as exc:
                raise PluginLoadError(f"plugin {module_path} on_load failed: {exc}") from exc
            try:
                plugin.register_hooks(self.bus)
            except Exception as exc:
                raise PluginLoadError(f"plugin {module_path} register_hooks failed: {exc}") from exc
            self._loaded.append(
                LoadedPlugin(module_path=module_path, plugin=plugin, manifest=plugin.manifest)
            )

        self._collect_celery_modules_from_hooks()
        self.register_mcp_tools()
        self._bootstrapped = True
        logger.info(
            "plugins loaded",
            extra={
                "namespaces": [p.manifest.namespace for p in self._loaded],
                "default_namespace": self.default_namespace,
            },
        )

    def _import_plugin(self, module_path: str) -> Plugin:
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise PluginLoadError(f"cannot import plugin module {module_path}: {exc}") from exc
        plugin = getattr(mod, "plugin", None)
        if plugin is None:
            raise PluginLoadError(f"module {module_path} must export `plugin`")
        if not hasattr(plugin, "manifest"):
            raise PluginLoadError(f"module {module_path} plugin missing manifest")
        return plugin  # type: ignore[return-value]

    def _validate_namespace_g3(self, manifests: dict[str, PluginManifest]) -> None:
        default_ns = self.default_namespace
        for ns, manifest in manifests.items():
            if ns == "core":
                continue
            if ns != default_ns:
                raise PluginLoadError(
                    f"enabled plugin namespace {ns!r} must match "
                    f"default_namespace {default_ns!r} (G3)"
                )

    def _resolve_deps(self, manifests: dict[str, PluginManifest]) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()

        def visit(ns: str) -> None:
            if ns in seen:
                return
            manifest = manifests.get(ns)
            if manifest is None:
                raise PluginLoadError(f"plugin depends on unknown namespace: {ns}")
            for dep in manifest.depends_on:
                visit(dep)
            seen.add(ns)
            order.append(ns)

        for ns in manifests:
            visit(ns)
        return order

    def _collect_celery_modules_from_hooks(self) -> None:
        base = [
            "eagle_rag.ingest.router",
            "eagle_rag.ingest.knowhere_adapter",
            "eagle_rag.ingest.pixelrag_adapter",
            "eagle_rag.kb.lifecycle",
        ]
        from eagle_rag.plugins.hookbus import HookContext
        from eagle_rag.plugins.hooks import Hook

        ctx = HookContext(plugin_namespace=self.default_namespace)
        modules = self.bus.invoke_all(Hook.CELERY_TASKS, ctx)
        extra: list[str] = []
        for m in modules:
            if isinstance(m, str) and m not in base and m not in extra:
                extra.append(m)
        self._celery_modules = base + extra

    def register_mcp_tools(self) -> None:
        """Register MCP tools from core and default-namespace plugins."""
        if self._mcp_tools_registered:
            return
        import eagle_rag.api.mcp_server  # noqa: F401 — ensure core tools are registered
        from eagle_rag.plugins.mcp_registry import TOOL_DEFINITIONS

        if not self._loaded:
            return

        default_ns = self.default_namespace
        before = len(TOOL_DEFINITIONS)
        for loaded in self._loaded:
            ns = loaded.manifest.namespace
            if ns != "core" and ns != default_ns:
                continue
            register_fn = getattr(loaded.plugin, "register_mcp_tools", None)
            if register_fn is None:
                continue
            try:
                register_fn()
            except Exception as exc:
                raise PluginLoadError(
                    f"plugin {loaded.module_path} register_mcp_tools failed: {exc}"
                ) from exc
        self._mcp_tools = list(TOOL_DEFINITIONS[before:])
        self._mcp_tools_registered = True

    def loaded_plugins(self) -> list[LoadedPlugin]:
        return list(self._loaded)

    def manifests(self) -> list[PluginManifest]:
        return [p.manifest for p in self._loaded]

    def get_specialized_collections(self, plugin_namespace: str | None = None) -> tuple[str, ...]:
        ns = plugin_namespace or self.default_namespace
        for loaded in self._loaded:
            if loaded.manifest.namespace == ns:
                return loaded.manifest.provides_specialized_collections
        return ()

    def collect_celery_modules(self) -> list[str]:
        if not self._bootstrapped:
            self.load_all()
        return list(self._celery_modules)

    def health_payload(self) -> dict[str, Any]:
        if not self._bootstrapped:
            self.load_all()
        recent = self.audit.recent()
        return {
            "default_namespace": self.default_namespace,
            "enabled_modules": [p.module_path for p in self._loaded],
            "manifests": [
                {
                    "namespace": p.manifest.namespace,
                    "version": p.manifest.version,
                    "milvus_db_name": p.manifest.milvus_db_name,
                    "provides_pipelines": list(p.manifest.provides_pipelines),
                    "provides_specialized_collections": list(
                        p.manifest.provides_specialized_collections
                    ),
                    "provides_mcp_tools": list(p.manifest.provides_mcp_tools),
                }
                for p in self._loaded
            ],
            "celery_modules": self.collect_celery_modules(),
            "recent_decisions": recent,
            "audit_stats": self.audit.audit_stats(),
        }

    def register_pipeline(self, name: str, pipeline: Any) -> None:
        self._pipeline_registry[name] = pipeline

    def get_pipeline(self, name: str) -> Any:
        if name not in self._pipeline_registry:
            raise KeyError(f"ingest pipeline not registered: {name}")
        return self._pipeline_registry[name]
