"""Image preprocessing utilities (format normalization via Pillow).

Normalizes common image formats to a target format (default PNG). Excel/CSV
files are handled directly by the Knowhere table_parser (no LibreOffice
dependency). This module does not depend on MinIO/Redis/PostgreSQL and can be
imported in any environment.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "PreprocessError",
    "normalize_image",
]


class PreprocessError(Exception):
    """Raised when image preprocessing fails."""


# ---------------------------------------------------------------------------
# Image format normalization
# ---------------------------------------------------------------------------


def normalize_image(
    img_path: str | Path,
    *,
    target_format: str = "PNG",
    output_dir: str | Path | None = None,
) -> Path:
    """Normalize an image to ``target_format`` (default PNG) via Pillow.

    Args:
        img_path: Source image path.
        target_format: Target format (e.g. ``PNG``, ``JPEG``).
        output_dir: Output directory; defaults to the source file's parent.

    Returns:
        Path to the normalized image.
    """
    from PIL import Image  # lazy import to avoid hard Pillow dependency at module import

    src = Path(img_path)
    if not src.exists():
        raise PreprocessError(f"source image not found: {src}")

    fmt = target_format.upper().lstrip(".")
    out_dir = Path(output_dir) if output_dir is not None else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{src.stem}.{fmt.lower()}"

    try:
        with Image.open(src) as img:
            # Convert palette/alpha modes for target format compatibility
            img.load()
            save_kwargs: dict = {}
            if fmt in ("JPEG", "JPG") and img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            img.save(dest, format=fmt, **save_kwargs)
    except Exception as exc:  # noqa: BLE001
        raise PreprocessError(f"image normalization failed: {src.name} -> {fmt}: {exc}") from exc

    return dest
