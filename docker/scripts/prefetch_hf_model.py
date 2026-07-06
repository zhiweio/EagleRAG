"""Pre-download the visual embedding model into a local directory during Docker build.

Supports HuggingFace Hub (with mirror endpoint) and ModelScope (recommended for Qwen
models in China when hf-mirror SSL is unstable). Output is always written to
``MODEL_LOCAL_PATH`` so runtime loads via a local path — no Hub access needed.
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


def _prefetch_huggingface(repo_id: str, dest: Path) -> None:
    from huggingface_hub import snapshot_download

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

    cache_dir = dest.parent / "_modelscope_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"ModelScope prefetch {repo_id} -> {dest} (cache_dir={cache_dir})", flush=True)
    src = Path(ms_snapshot_download(repo_id, cache_dir=str(cache_dir)))
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def main() -> None:
    repo_id = _repo_id()
    dest = _dest()
    source = os.environ.get("MODEL_DOWNLOAD_SOURCE", "auto").strip().lower()
    used_source = source

    print(
        f"MODEL_DOWNLOAD_SOURCE={source} MODEL_REPO_ID={repo_id} MODEL_LOCAL_PATH={dest}",
        flush=True,
    )

    if source == "huggingface":
        _prefetch_huggingface(repo_id, dest)
    elif source == "modelscope":
        _prefetch_modelscope(repo_id, dest)
    elif source == "auto":
        try:
            _prefetch_huggingface(repo_id, dest)
            used_source = "huggingface"
        except Exception as exc:  # noqa: BLE001
            print(f"HuggingFace prefetch failed ({exc}); falling back to ModelScope", flush=True)
            _prefetch_modelscope(repo_id, dest)
            used_source = "modelscope"
    else:
        raise ValueError(f"unsupported MODEL_DOWNLOAD_SOURCE={source!r}")

    (dest / ".prefetch_source").write_text(f"{used_source}\n", encoding="utf-8")
    print(f"Prefetch complete: {dest}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Prefetch failed: {exc}", file=sys.stderr, flush=True)
        raise
