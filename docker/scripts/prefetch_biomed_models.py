"""Pre-download biomed domain encoder models during Docker build.

Downloads PubMedBERT / ChemBERTa / BiomedCLIP / UNI2 weights into local
directories so runtime never depends on HuggingFace Hub connectivity. Each
model uses the best available source:

- PubMedBERT / ChemBERTa: HF mirror (``hf-mirror.com``) - no faithful
  ModelScope mirror exists.
- BiomedCLIP: ModelScope (same repo ID as HF) with HF mirror fallback.
- UNI2-h: ModelScope (``czxxkj/UNI2-h``) - the HF original is gated.

Activated via ``PREFETCH_BIOMED_MODELS=1`` build arg (off by default so core
builds are unaffected). Output dirs:

    /opt/huggingface/biomed/pubmedbert/
    /opt/huggingface/biomed/molformer/
    /opt/huggingface/biomed/medimageinsight/
    /opt/huggingface/biomed/uni2/
    /opt/huggingface/biomed/medcpt-rerank/

Runtime env vars (``EAGLE_BIOMED_*_MODEL``) point at these dirs; see
``docker-compose.biomed.yml``.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Per-model download config:
# (encoder_name, hf_repo_id, modelscope_repo_id, preferred_source, required)
# ``preferred_source`` is tried first; the other source is the fallback.
# - "hf": HuggingFace mirror (HF_ENDPOINT=https://hf-mirror.com)
# - "ms": ModelScope
# ``required=False`` models are skipped (with a warning) if all sources fail,
# so a missing non-critical encoder does not block the image build.
#
# ModelScope is preferred for all biomed models because hf-mirror.com now 308-redirects
# to huggingface.co (which is often unreachable from China networks). PubMedBERT was
# renamed to BiomedBERT on both HF and ModelScope; the ModelScope mirror uses the new
# name with a general BERT vocab (30522) but is still bio-domain pretrained and suitable
# for embedding-based retrieval. ChemBERTa has no faithful ModelScope mirror; it falls
# back to HF and is marked non-required (eagle_chemical is typically empty).
_BIOMED_MODELS: tuple[tuple[str, str, str | None, str, bool], ...] = (
    # PubMedBERT / BiomedBERT: ModelScope mirror under the renamed repo.
    (
        "pubmedbert",
        "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
        "microsoft/BiomedNLP-BiomedBERT-base-uncased-abstract-fulltext",
        "ms",
        True,
    ),
    # ChemBERTa (MolFormer): no ModelScope mirror; HF mirror only.
    # Non-required: eagle_chemical is typically empty; skip if unavailable.
    (
        "molformer",
        "seyonec/ChemBERTa-zinc-base-v1",
        None,
        "hf",
        False,
    ),
    # BiomedCLIP (MedImageInsight): same ID on both; prefer ModelScope for CN network.
    (
        "medimageinsight",
        "microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224",
        "microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224",
        "ms",
        True,
    ),
    # UNI2-h: HF original is gated; ModelScope mirror (czxxkj/UNI2-h) is open.
    (
        "uni2",
        "MahmoodLab/UNI2-h",
        "czxxkj/UNI2-h",
        "ms",
        True,
    ),
    # MedCPT Cross-Encoder (Tier-2 biomed rerank; NOT Query/Article encoders).
    # HF only — large single pytorch_model.bin; download with max_workers=1 in Docker.
    (
        "medcpt-rerank",
        "ncbi/MedCPT-Cross-Encoder",
        None,
        "hf",
        True,
    ),
)

_BIOMED_ROOT = Path(os.environ.get("BIOMED_MODEL_ROOT", "/opt/huggingface/biomed"))
_HF_HUB_CACHE = Path(
    os.environ.get("BIOMED_HF_HUB_CACHE", str(_BIOMED_ROOT.parent / "_hf_hub_cache"))
)


def _scrub_incomplete_files(root: Path) -> None:
    if not root.is_dir():
        return
    for path in root.rglob("*.incomplete"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _has_weights(path: Path) -> bool:
    if not path.is_dir():
        return False
    for pattern in ("*.safetensors", "**/*.safetensors", "*.bin", "**/*.bin"):
        if any(path.glob(pattern)):
            return True
    return False


def _has_config(path: Path) -> bool:
    """Check for a config file (standard HF or open_clip layout)."""
    return any((path / name).is_file() for name in ("config.json", "open_clip_config.json"))


def _is_complete(path: Path) -> bool:
    if not path.is_dir():
        return False
    if any(path.rglob("*.incomplete")):
        return False
    return _has_config(path) and _has_weights(path)


def _promote_staging(staging: Path, dest: Path) -> None:
    """Move a finished HF staging tree into the final model directory."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(dest))
    nested_cache = dest / ".cache"
    if nested_cache.exists():
        shutil.rmtree(nested_cache, ignore_errors=True)


def _apply_proxy_env() -> None:
    """Propagate ``BIOMED_HTTP_PROXY`` to standard proxy env vars if set.

    ``huggingface_hub`` and ``modelscope`` both honor ``HTTP_PROXY`` /
    ``HTTPS_PROXY``. ``BIOMED_HTTP_PROXY`` is the project-specific knob
    documented in ``.env.biomed.example`` for mainland China -> overseas access.
    """
    proxy = os.environ.get("BIOMED_HTTP_PROXY", "").strip()
    if not proxy:
        return
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[var] = proxy
    print(f"Using proxy for biomed model downloads: {proxy}", flush=True)


def _prefetch_modelscope(repo_id: str, dest: Path) -> None:
    from modelscope import snapshot_download as ms_snapshot_download

    cache_dir = dest.parent / "_modelscope_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"ModelScope prefetch {repo_id} -> {dest}", flush=True)
    src = Path(ms_snapshot_download(repo_id, cache_dir=str(cache_dir)))
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _prefetch_huggingface(
    repo_id: str,
    dest: Path,
    *,
    endpoint: str | None = None,
    max_workers: int | None = None,
) -> None:
    from huggingface_hub import snapshot_download

    ep = (endpoint or os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")).rstrip("/")
    workers = max_workers
    if workers is None:
        workers = int(os.environ.get("HF_HUB_DOWNLOAD_MAX_WORKERS", "1"))
    _HF_HUB_CACHE.mkdir(parents=True, exist_ok=True)
    _scrub_incomplete_files(_HF_HUB_CACHE)
    print(
        f"HuggingFace prefetch {repo_id} -> {dest} via endpoint={ep} "
        f"(cache={_HF_HUB_CACHE}, workers={workers})",
        flush=True,
    )
    if dest.exists():
        shutil.rmtree(dest)
    with tempfile.TemporaryDirectory(prefix="biomed-hf-", dir=str(_BIOMED_ROOT.parent)) as tmp:
        staging = Path(tmp) / dest.name
        snapshot_download(
            repo_id,
            endpoint=ep,
            cache_dir=str(_HF_HUB_CACHE),
            local_dir=str(staging),
            max_workers=workers,
        )
        _promote_staging(staging, dest)


def _prefetch_huggingface_with_fallback(repo_id: str, dest: Path) -> None:
    """Try configured HF mirror first, then huggingface.co for mirror gaps."""
    primary = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    endpoints = [primary]
    if primary != "https://huggingface.co":
        endpoints.append("https://huggingface.co")
    last_exc: Exception | None = None
    for ep in endpoints:
        try:
            if dest.exists():
                shutil.rmtree(dest)
            _prefetch_huggingface(repo_id, dest, endpoint=ep, max_workers=1)
            if _is_complete(dest):
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"HF endpoint {ep} failed for {repo_id}: {exc}", flush=True)
            _scrub_incomplete_files(_HF_HUB_CACHE)
            if dest.exists() and not _is_complete(dest):
                shutil.rmtree(dest, ignore_errors=True)
    msg = f"HF download failed for {repo_id}"
    if last_exc:
        msg += f": {last_exc}"
    raise RuntimeError(msg)


def _download_model(
    encoder_name: str,
    hf_repo_id: str,
    modelscope_repo_id: str | None,
    preferred: str,
    dest: Path,
) -> None:
    """Download a single model, trying the preferred source first then fallback."""
    sources = [preferred]
    if preferred == "ms" and modelscope_repo_id:
        sources.append("hf")
    elif preferred == "hf":
        if modelscope_repo_id:
            sources.append("ms")
    else:
        # Unknown preferred; try both in HF-first order.
        sources = ["hf", "ms"]

    last_exc: Exception | None = None
    for source in sources:
        try:
            if source == "ms":
                if not modelscope_repo_id:
                    continue
                _prefetch_modelscope(modelscope_repo_id, dest)
            else:
                _prefetch_huggingface_with_fallback(hf_repo_id, dest)
            if _is_complete(dest):
                print(f"Prefetched {encoder_name} via {source} -> {dest}", flush=True)
                return
            print(
                f"{encoder_name}: {source} download completed but dest incomplete",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"{encoder_name}: {source} download failed: {exc}", flush=True)
    msg = f"all download sources failed for {encoder_name}"
    if last_exc:
        msg += f": {last_exc}"
    raise RuntimeError(msg)


def main() -> None:
    if os.environ.get("PREFETCH_BIOMED_MODELS", "0").strip() not in {"1", "true", "TRUE"}:
        print("PREFETCH_BIOMED_MODELS not enabled; skipping biomed model prefetch", flush=True)
        return

    _BIOMED_ROOT.mkdir(parents=True, exist_ok=True)
    _apply_proxy_env()
    print(f"Biomed model prefetch: root={_BIOMED_ROOT}", flush=True)

    failures: list[str] = []
    for encoder_name, hf_repo_id, ms_repo_id, preferred, required in _BIOMED_MODELS:
        dest = _BIOMED_ROOT / encoder_name
        if _is_complete(dest):
            print(f"{encoder_name} already complete at {dest}, skipping", flush=True)
            continue
        try:
            _download_model(encoder_name, hf_repo_id, ms_repo_id, preferred, dest)
        except Exception as exc:  # noqa: BLE001
            if required:
                print(f"ERROR: required encoder {encoder_name} failed: {exc}", flush=True)
                failures.append(encoder_name)
            else:
                print(
                    f"WARNING: non-required encoder {encoder_name} skipped "
                    f"(download failed): {exc}",
                    flush=True,
                )

    if failures:
        msg = f"required biomed encoders failed to download: {', '.join(failures)}"
        raise RuntimeError(msg)
    print(f"Biomed model prefetch complete: {_BIOMED_ROOT}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Biomed prefetch failed: {exc}", file=sys.stderr, flush=True)
        raise
