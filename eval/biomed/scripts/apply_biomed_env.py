#!/usr/bin/env python3
"""Overlay biomed profile keys onto an env file (idempotent).

Defaults to ``auto`` encoder mode + fail-fast (no deterministic fallback) so
missing native weights raise instead of silently producing hash embeddings.
For offline CI/e2e without HF connectivity, pass ``--offline`` to restore the
deterministic fallback behavior.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Pre-downloaded biomed encoder paths (populated by Docker build with
# PREFETCH_BIOMED_MODELS=1). Pointed at via EAGLE_BIOMED_*_MODEL env vars so
# plugins/biomed/encoders._model_id_for picks up local paths.
_BIOMED_MODEL_PATHS = {
    "EAGLE_BIOMED_PUBMEDBERT_MODEL": "/opt/huggingface/biomed/pubmedbert",
    "EAGLE_BIOMED_MOLFORMER_MODEL": "/opt/huggingface/biomed/molformer",
    "EAGLE_BIOMED_MEDIMAGE_MODEL": "/opt/huggingface/biomed/medimageinsight",
    "EAGLE_BIOMED_UNI2_MODEL": "/opt/huggingface/biomed/uni2",
}


def _build_overrides(offline: bool) -> dict[str, str]:
    overrides: dict[str, str] = {
        "EAGLE_RAG_PROFILE": "biomed",
        "PLUGIN_NAMESPACE": "biomed",
        "KB_NAME": "hutchmed",
        "VISUAL_EMBEDDING_PROVIDER": "dashscope",
        "VISUAL_EMBEDDING_MODEL": "qwen3-vl-embedding",
    }
    if offline:
        # CI/e2e without HF connectivity: deterministic hash embeddings, no prefetch.
        overrides["EAGLE_BIOMED_ENCODER_MODE"] = "deterministic"
        overrides["EAGLE_BIOMED_ALLOW_DETERMINISTIC"] = "1"
        overrides["PREFETCH_BIOMED_MODELS"] = "0"
    else:
        # Production: native weights (auto) + fail-fast on missing weights.
        overrides["EAGLE_BIOMED_ENCODER_MODE"] = "auto"
        overrides["PREFETCH_BIOMED_MODELS"] = "1"
        overrides.update(_BIOMED_MODEL_PATHS)
    return overrides


def apply(path: Path, overrides: dict[str, str]) -> None:
    lines_out: list[str] = []
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                lines_out.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in overrides:
                lines_out.append(f"{key}={overrides[key]}")
                seen.add(key)
            else:
                lines_out.append(line)
    for key, value in overrides.items():
        if key not in seen:
            lines_out.append(f"{key}={value}")
    path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".env.biomed", type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use deterministic hash embeddings for CI/e2e without HF connectivity.",
    )
    args = parser.parse_args()
    overrides = _build_overrides(offline=args.offline)
    apply(args.target, overrides)
    mode = "offline (deterministic)" if args.offline else "production (auto + fail-fast)"
    print(f"updated {args.target} [{mode}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
