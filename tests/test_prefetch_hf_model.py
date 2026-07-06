"""Tests for Docker visual-model prefetch helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _prefetch_module():
    script = Path(__file__).resolve().parents[1] / "docker" / "scripts" / "prefetch_hf_model.py"
    spec = importlib.util.spec_from_file_location("prefetch_hf_model", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_model_complete_requires_config_and_weights(tmp_path: Path) -> None:
    mod = _prefetch_module()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    assert mod._is_model_complete(model_dir) is False
    (model_dir / "model.safetensors").write_bytes(b"x")
    assert mod._is_model_complete(model_dir) is True


def test_maybe_restore_from_cache(tmp_path: Path) -> None:
    mod = _prefetch_module()
    cache_dir = tmp_path / "cache"
    cached = cache_dir / "model"
    cached.mkdir(parents=True)
    (cached / "config.json").write_text("{}", encoding="utf-8")
    (cached / "model.safetensors").write_bytes(b"x")
    (cached / ".prefetch_source").write_text("modelscope\n", encoding="utf-8")

    dest = tmp_path / "dest"
    assert mod._maybe_restore_from_cache(cache_dir, dest) is True
    assert (dest / "model.safetensors").is_file()
    assert (dest / ".prefetch_source").read_text(encoding="utf-8") == "modelscope\n"
