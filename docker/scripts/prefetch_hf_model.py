"""Pre-download the visual embedding model into a local directory during Docker build.

Supports HuggingFace Hub (with mirror endpoint) and ModelScope (recommended for Qwen
models in China when hf-mirror SSL is unstable). Output is always written to
``MODEL_LOCAL_PATH`` so runtime loads via a local path — no Hub access needed.

When ``MODEL_CACHE_DIR`` is set (BuildKit cache mount), a complete copy is kept there
so rebuilds can restore from cache instead of re-downloading multi-GB weights.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _dest() -> Path:
    return Path(os.environ.get("MODEL_LOCAL_PATH", "/opt/huggingface/model"))


def _repo_id() -> str:
    return os.environ.get("MODEL_REPO_ID", "Qwen/Qwen3-VL-Embedding-2B")


def _cache_model_dir(cache_dir: Path) -> Path:
    return cache_dir / "model"


def _has_weights(path: Path) -> bool:
    if not path.is_dir():
        return False
    for pattern in ("*.safetensors", "**/*.safetensors", "*.bin", "**/*.bin"):
        if any(path.glob(pattern)):
            return True
    return False


def _is_model_complete(path: Path) -> bool:
    return path.is_dir() and (path / "config.json").is_file() and _has_weights(path)


def _replace_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _maybe_restore_from_cache(cache_dir: Path, dest: Path) -> bool:
    cached = _cache_model_dir(cache_dir)
    if not _is_model_complete(cached):
        return False
    print(f"Restoring model from build cache {cached} -> {dest}", flush=True)
    _replace_tree(cached, dest)
    marker = cached / ".prefetch_source"
    if marker.is_file():
        shutil.copy2(marker, dest / ".prefetch_source")
    return True


def _save_to_cache(dest: Path, cache_dir: Path) -> None:
    if not _is_model_complete(dest):
        return
    cached = _cache_model_dir(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Updating build cache {cached}", flush=True)
    _replace_tree(dest, cached)


def _prefetch_huggingface(repo_id: str, dest: Path) -> None:
    from huggingface_hub import snapshot_download

    if _is_model_complete(dest):
        return

    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    max_workers = int(os.environ.get("HF_HUB_DOWNLOAD_MAX_WORKERS", "8"))
    print(
        f"HuggingFace prefetch {repo_id} -> {dest} via endpoint={endpoint} "
        f"(max_workers={max_workers})",
        flush=True,
    )
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id,
        endpoint=endpoint,
        local_dir=str(dest),
        max_workers=max_workers,
    )


def _prefetch_modelscope(repo_id: str, dest: Path) -> None:
    from modelscope import snapshot_download as ms_snapshot_download

    if _is_model_complete(dest):
        return

    cache_dir = dest.parent / "_modelscope_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"ModelScope prefetch {repo_id} -> {dest} (cache_dir={cache_dir})", flush=True)
    src = Path(ms_snapshot_download(repo_id, cache_dir=str(cache_dir)))
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _download(repo_id: str, dest: Path, source: str) -> str:
    if source == "huggingface":
        _prefetch_huggingface(repo_id, dest)
        return "huggingface"
    if source == "modelscope":
        _prefetch_modelscope(repo_id, dest)
        return "modelscope"
    if source == "auto":
        try:
            _prefetch_huggingface(repo_id, dest)
            return "huggingface"
        except Exception as exc:  # noqa: BLE001
            print(f"HuggingFace prefetch failed ({exc}); falling back to ModelScope", flush=True)
            _prefetch_modelscope(repo_id, dest)
            return "modelscope"
    raise ValueError(f"unsupported MODEL_DOWNLOAD_SOURCE={source!r}")


def main() -> None:
    repo_id = _repo_id()
    dest = _dest()
    source = os.environ.get("MODEL_DOWNLOAD_SOURCE", "auto").strip().lower()
    cache_dir_str = os.environ.get("MODEL_CACHE_DIR", "").strip()
    cache_dir = Path(cache_dir_str) if cache_dir_str else None

    print(
        f"MODEL_DOWNLOAD_SOURCE={source} MODEL_REPO_ID={repo_id} MODEL_LOCAL_PATH={dest}",
        flush=True,
    )

    if _is_model_complete(dest):
        print(f"Model already complete at {dest}, skipping prefetch", flush=True)
        if cache_dir is not None:
            _save_to_cache(dest, cache_dir)
        return

    if cache_dir is not None and _maybe_restore_from_cache(cache_dir, dest):
        return

    work_dest = _cache_model_dir(cache_dir) if cache_dir is not None else dest
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    used_source = _download(repo_id, work_dest, source)
    (work_dest / ".prefetch_source").write_text(f"{used_source}\n", encoding="utf-8")

    if cache_dir is not None and work_dest != dest:
        _replace_tree(work_dest, dest)

    if cache_dir is not None:
        _save_to_cache(dest, cache_dir)

    print(f"Prefetch complete: {dest}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Prefetch failed: {exc}", file=sys.stderr, flush=True)
        raise
