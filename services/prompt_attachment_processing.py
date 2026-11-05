# 添付画像を安全なバイト列へ正規化し、保存先の実装と画像処理を分離する。
"""Safe, deterministic processing for prompt-share image attachments.

The processing boundary deliberately produces transport-neutral byte variants.
The current local filesystem store writes those bytes to disk; a future object
storage implementation can upload the same variants without changing API code.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

PROMPT_ATTACHMENT_MAX_PIXELS = 16_000_000
PROMPT_ATTACHMENT_MAX_DIMENSION = 2_048
PROMPT_ATTACHMENT_THUMBNAIL_DIMENSION = 720
PROMPT_ATTACHMENT_WEBP_QUALITY = 82
PROMPT_ATTACHMENT_THUMBNAIL_WEBP_QUALITY = 76
PROMPT_ATTACHMENT_DISPLAY_MAX_BYTES = 2 * 1024 * 1024
PROMPT_ATTACHMENT_THUMBNAIL_MAX_BYTES = 400 * 1024

# 展開後の画像は圧縮サイズより大きいため、一般I/Oプールとは別にメモリ負荷を制限する。
# Decoding an image can allocate substantially more memory than its compressed
# upload size. Keep this bounded independently of the generic blocking-I/O pool.
_IMAGE_PROCESSING_SEMAPHORE = threading.BoundedSemaphore(value=2)


@dataclass(frozen=True)
class ProcessedPromptAttachment:
    # 保存先へ渡す、表示用とカード用の正規化済み画像。
    """Normalized display and card variants ready for a storage backend."""

    display_bytes: bytes
    thumbnail_bytes: bytes
    width: int
    height: int


def process_prompt_attachment(source: bytes) -> ProcessedPromptAttachment:
    # 画像を検証・縮小してメタデータを除去しWebPにする。処理量が無制限になる動画画像は拒否する。
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
    # 巨大画像に対するPillowの警告を例外にし、サイズ制限を確実に適用する。
    # Pillow emits a warning (rather than always throwing) for oversized input.
    # Promote it to an exception so the size policy is deterministic.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(source)) as opened:
            if getattr(opened, "is_animated", False):
                raise ValueError("アニメーション画像はアップロードできません。")
            if opened.width * opened.height > PROMPT_ATTACHMENT_MAX_PIXELS:
                raise ValueError("画像の総ピクセル数が上限を超えています。")
            # 最後までデコードし、切れたデータや破損を検出する。
            opened.load()  # Full decode catches truncated/corrupt image payloads.

            image = ImageOps.exif_transpose(opened)
            image = _convert_to_webp_compatible_mode(image)
            display, display_bytes = _encode_bounded_webp(
                image,
                PROMPT_ATTACHMENT_MAX_DIMENSION,
                PROMPT_ATTACHMENT_WEBP_QUALITY,
                PROMPT_ATTACHMENT_DISPLAY_MAX_BYTES,
            )
            _thumbnail, thumbnail_bytes = _encode_bounded_webp(
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
    # 透明度を保ちつつ、パレットやメタデータ専用のモードを除く。
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
    # 配信サイズの予算内で派生画像をエンコードする。
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
    # 難しい画像でも低解像度の派生画像に収め、利用者が渡した原本の直接配信には戻さない。
    # Even difficult photographic/noise images retain a bounded low-resolution
    # derivative. Never fall back to serving the user-supplied original.
    return smallest
