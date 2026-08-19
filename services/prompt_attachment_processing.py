"""Safe, deterministic processing for prompt-share image attachments.

The processing boundary deliberately produces transport-neutral byte variants.
The current local filesystem store writes those bytes to disk; a future object
storage implementation can upload the same variants without changing API code.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import threading
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


PROMPT_ATTACHMENT_MAX_PIXELS = 16_000_000
PROMPT_ATTACHMENT_MAX_DIMENSION = 2_048
PROMPT_ATTACHMENT_THUMBNAIL_DIMENSION = 720
PROMPT_ATTACHMENT_WEBP_QUALITY = 82
PROMPT_ATTACHMENT_THUMBNAIL_WEBP_QUALITY = 76
PROMPT_ATTACHMENT_DISPLAY_MAX_BYTES = 2 * 1024 * 1024
PROMPT_ATTACHMENT_THUMBNAIL_MAX_BYTES = 400 * 1024

# Decoding an image can allocate substantially more memory than its compressed
# upload size. Keep this bounded independently of the generic blocking-I/O pool.
_IMAGE_PROCESSING_SEMAPHORE = threading.BoundedSemaphore(value=2)


@dataclass(frozen=True)
class ProcessedPromptAttachment:
    """Normalized display and card variants ready for a storage backend."""

    display_bytes: bytes
    thumbnail_bytes: bytes
    width: int
    height: int


def process_prompt_attachment(source: bytes) -> ProcessedPromptAttachment:
    """Decode, validate, resize, strip metadata, and encode a safe WebP pair.

    Animated uploads are intentionally rejected. A prompt example is static
    content and accepting arbitrary frame counts would make decode cost and
    derivative generation unbounded.
    """
    try:
        with _IMAGE_PROCESSING_SEMAPHORE:
            return _process_prompt_attachment(source)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("画像の総ピクセル数が上限を超えています。") from exc
    except UnidentifiedImageError as exc:
        raise ValueError("画像データを読み取れませんでした。") from exc
    except OSError as exc:
        raise ValueError("画像データが壊れているか、対応していない形式です。") from exc


def _process_prompt_attachment(source: bytes) -> ProcessedPromptAttachment:
    # Pillow emits a warning (rather than always throwing) for oversized input.
    # Promote it to an exception so the size policy is deterministic.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(source)) as opened:
            if getattr(opened, "is_animated", False):
                raise ValueError("アニメーション画像はアップロードできません。")
            if opened.width * opened.height > PROMPT_ATTACHMENT_MAX_PIXELS:
                raise ValueError("画像の総ピクセル数が上限を超えています。")
            opened.load()  # Full decode catches truncated/corrupt image payloads.

            image = ImageOps.exif_transpose(opened)
            image = _convert_to_webp_compatible_mode(image)
            display, display_bytes = _encode_bounded_webp(
                image,
                PROMPT_ATTACHMENT_MAX_DIMENSION,
                PROMPT_ATTACHMENT_WEBP_QUALITY,
                PROMPT_ATTACHMENT_DISPLAY_MAX_BYTES,
            )
            thumbnail, thumbnail_bytes = _encode_bounded_webp(
                image,
                PROMPT_ATTACHMENT_THUMBNAIL_DIMENSION,
                PROMPT_ATTACHMENT_THUMBNAIL_WEBP_QUALITY,
                PROMPT_ATTACHMENT_THUMBNAIL_MAX_BYTES,
            )
            return ProcessedPromptAttachment(
                display_bytes=display_bytes,
                thumbnail_bytes=thumbnail_bytes,
                width=display.width,
                height=display.height,
            )


def _convert_to_webp_compatible_mode(image: Image.Image) -> Image.Image:
    """Remove palette/metadata-only modes while retaining transparency."""
    if image.mode in {"RGBA", "RGB"}:
        return image.copy()
    if "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def _resized_copy(image: Image.Image, maximum_dimension: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(
        (maximum_dimension, maximum_dimension),
        resample=Image.Resampling.LANCZOS,
    )
    return copy


def _encode_webp(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        format="WEBP",
        quality=quality,
        method=6,
        exact=False,
    )
    return buffer.getvalue()


def _encode_bounded_webp(
    image: Image.Image,
    maximum_dimension: int,
    initial_quality: int,
    maximum_bytes: int,
) -> tuple[Image.Image, bytes]:
    """Encode a derivative within a predictable delivery-byte budget."""
    dimensions = (
        maximum_dimension,
        int(maximum_dimension * 0.75),
        int(maximum_dimension * 0.5),
        max(512, int(maximum_dimension * 0.25)),
    )
    qualities = (initial_quality, initial_quality - 10, initial_quality - 20, initial_quality - 30)
    smallest: tuple[Image.Image, bytes] | None = None
    for dimension in dimensions:
        candidate = _resized_copy(image, dimension)
        for quality in qualities:
            encoded = _encode_webp(candidate, max(quality, 35))
            smallest = (candidate, encoded)
            if len(encoded) <= maximum_bytes:
                return candidate, encoded
    if smallest is None:  # pragma: no cover - dimensions is always non-empty
        raise ValueError("画像を変換できませんでした。")
    # Even difficult photographic/noise images retain a bounded low-resolution
    # derivative. Never fall back to serving the user-supplied original.
    return smallest
