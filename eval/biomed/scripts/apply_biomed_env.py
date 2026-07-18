#!/usr/bin/env python3
"""Overlay biomed profile keys onto an env file (idempotent)."""

from __future__ import annotations

import sys
from pathlib import Path

OVERRIDES = {
    "EAGLE_RAG_PROFILE": "biomed",
    "PLUGIN_NAMESPACE": "biomed",
    "KB_NAME": "hutchmed",
    "VISUAL_EMBEDDING_PROVIDER": "dashscope",
    "VISUAL_EMBEDDING_MODEL": "qwen3-vl-embedding",
    # Offline/e2e default: skip HF Hub pulls; set auto + ALLOW=1 for native+fallback.
    "EAGLE_BIOMED_ENCODER_MODE": "deterministic",
    "EAGLE_BIOMED_ALLOW_DETERMINISTIC": "1",
}


def apply(path: Path) -> None:
    lines_out: list[str] = []
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                lines_out.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in OVERRIDES:
                lines_out.append(f"{key}={OVERRIDES[key]}")
                seen.add(key)
            else:
                lines_out.append(line)
    for key, value in OVERRIDES.items():
        if key not in seen:
            lines_out.append(f"{key}={value}")
    path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.biomed")
    apply(target)
    print(f"updated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
