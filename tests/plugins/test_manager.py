"""PluginManager discovery, G3 validation, and health payload."""

from __future__ import annotations

import pytest

from eagle_rag.config import Settings, get_settings
from eagle_rag.plugins import reset_plugin_manager
from eagle_rag.plugins.errors import PluginLoadError
from eagle_rag.plugins.manager import PluginManager


@pytest.fixture(autouse=True)
def _reset_plugins() -> None:
    reset_plugin_manager()
    yield
    reset_plugin_manager()


def test_load_core_defaults() -> None:
    manager = PluginManager()
    manager.load_all()
    namespaces = [p.manifest.namespace for p in manager.loaded_plugins()]
    assert "core" in namespaces
    payload = manager.health_payload()
    assert payload["default_namespace"] == "core"
    assert "eagle_rag.plugins.core_defaults" in payload["enabled_modules"]


def test_g3_mismatched_namespace_fails() -> None:
    base = get_settings().model_dump()
    base["plugins"] = {
        "enabled": [
            "eagle_rag.plugins.core_defaults",
            "tests.plugins.stub_biomed_plugin",
        ],
        "default_namespace": "core",
        "allow_namespace_override": False,
        "options": {
            "biomed": {
                "default_dual_text_search": False,
                "exploratory_search_collections": [],
            },
        },
    }
    settings = Settings.model_validate(base)
    manager = PluginManager(settings=settings)
    try:
        with pytest.raises(PluginLoadError, match="G3"):
            manager.load_all()
    finally:
        reset_plugin_manager()
