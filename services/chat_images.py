"""Images attached to chat messages: validation, history metadata and model input.

画像は本文へ埋め込めないため、テキスト添付（``services/attached_files.py``）とは別に
扱う。履歴には画像IDと寸法だけを持ち回し、画像を読めるモデルへ送るときにだけ
プロバイダのアダプタが保存済みの画像を読み出して入力へ変換する。

Images cannot be inlined into the message text, so they are handled apart from the
text attachments in ``services/attached_files.py``. History carries only the image id
and dimensions; the provider adapter loads the stored image and converts it only when
the request goes to a model that reads images.
"""

from __future__ import annotations

import base64
import binascii
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from services.attached_files import MAX_ATTACHED_FILES, AttachedFileValidationError
from services.chat_image_storage import (
    is_valid_chat_image_id,
    read_chat_image_bytes,
    save_chat_image,
)
from services.prompt_attachment_processing import process_prompt_attachment
from services.prompt_attachment_upload import infer_prompt_attachment_mime_type

# 画像入力を受け付けるモデル。GPT-6 Luna 以外は画像を読めない。
# Models that accept image input; everything other than GPT-6 Luna is text-only.
IMAGE_INPUT_MODELS = frozenset({"gpt-6-luna"})

IMAGE_ATTACHMENT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
# ブラウザが長辺 2048px に縮めてから送るので、この上限は縮小済みの画像に対する余裕分。
# The browser downsizes to a 2048px long side first, so this bounds an already-reduced image.
MAX_ATTACHED_IMAGE_BYTES = 3 * 1024 * 1024
MAX_ATTACHED_IMAGE_BASE64_LENGTH = ((MAX_ATTACHED_IMAGE_BYTES + 2) // 3) * 4

# 保存時に WebP へ変換するため、モデルへ送る形式は常にこれになる。
# Stored images are re-encoded to WebP, so this is always the format sent to the model.
CHAT_IMAGE_MEDIA_TYPE = "image/webp"

# GPT-6 系の画像は 32px 四方のパッチ単位で数えられる。Luna の倍率は公開されていないため、
# 公開されている GPT-6 系の最大値（1.2）と、high 相当の上限（2,500 パッチ）で多めに見積もる。
# GPT-6 images are counted in 32px patches. Luna's multiplier is not published, so estimate
# high with the largest published GPT-6 multiplier (1.2) and the high-detail cap (2,500).
_IMAGE_PATCH_PIXELS = 32
_IMAGE_MAX_PATCHES = 2_500
_IMAGE_TOKEN_MULTIPLIER = 1.2

IMAGE_INPUTS_KEY = "image_inputs"
ATTACHED_IMAGES_KEY = "attached_images"


@dataclass(frozen=True)
class ChatImage:
    """One stored image as referenced from a chat message."""

    id: str
    name: str
    width: int
    height: int

    def to_storage(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "width": self.width, "height": self.height}


def model_accepts_image_input(model_name: str | None) -> bool:
    return str(model_name or "").strip() in IMAGE_INPUT_MODELS


def is_image_attachment_name(name: object) -> bool:
    return PurePosixPath(str(name or "").lower()).suffix in IMAGE_ATTACHMENT_EXTENSIONS


def _item_value(item: Any, key: str) -> str:
    value = item.get(key, "") if isinstance(item, Mapping) else getattr(item, key, "")
    return "" if value is None else str(value)


def split_image_attachments(attached_files: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    """Split request attachments into (text/document files, images) by file extension."""
    documents: list[Any] = []
    images: list[Any] = []
    for item in attached_files:
        (images if is_image_attachment_name(_item_value(item, "name")) else documents).append(item)
    return documents, images


def _decode_image(filename: str, data_base64: str) -> bytes:
    encoded = "".join(data_base64.split())
    if encoded.lower().startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    if not encoded:
        raise AttachedFileValidationError(f"「{filename}」の画像データが空です。")
    limit_mb = MAX_ATTACHED_IMAGE_BYTES // (1024 * 1024)
    if len(encoded) > MAX_ATTACHED_IMAGE_BASE64_LENGTH:
        raise AttachedFileValidationError(f"「{filename}」は{limit_mb}MBを超えるため添付できません。")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachedFileValidationError(f"「{filename}」の画像データを読み取れません。") from exc
    if not decoded:
        raise AttachedFileValidationError(f"「{filename}」の画像データが空です。")
    if len(decoded) > MAX_ATTACHED_IMAGE_BYTES:
        raise AttachedFileValidationError(f"「{filename}」は{limit_mb}MBを超えるため添付できません。")
    return decoded


def prepare_chat_images(image_items: Sequence[Any], owner_key: str | None) -> list[ChatImage]:
    """Validate, normalize (EXIF orientation, metadata removal, WebP) and store each image."""
    if not image_items:
        return []
    if not owner_key:
        raise AttachedFileValidationError("画像を保存できませんでした。ページを再読み込みしてください。")
    images: list[ChatImage] = []
    for item in list(image_items)[:MAX_ATTACHED_FILES]:
        filename = PurePosixPath(_item_value(item, "name").strip().replace("\\", "/")).name
        if not filename:
            raise AttachedFileValidationError("添付ファイル名が不正です。")
        source = _decode_image(filename, _item_value(item, "data_base64"))
        if infer_prompt_attachment_mime_type(source) is None:
            raise AttachedFileValidationError(f"「{filename}」は PNG / JPEG / WEBP / GIF の画像ではありません。")
        try:
            processed = process_prompt_attachment(source)
        except ValueError as exc:
            raise AttachedFileValidationError(f"「{filename}」: {exc}") from exc
        image_id = save_chat_image(owner_key, processed.display_bytes, processed.thumbnail_bytes)
        images.append(ChatImage(id=image_id, name=filename, width=processed.width, height=processed.height))
    return images


def encode_chat_images_for_storage(images: Sequence[ChatImage] | None) -> list[dict[str, Any]] | None:
    if not images:
        return None
    return [image.to_storage() for image in images[:MAX_ATTACHED_FILES]]


def decode_chat_images_from_storage(raw_payload: Any) -> list[ChatImage]:
    """Restore image references, skipping entries that do not carry a valid id."""
    if not isinstance(raw_payload, list):
        return []
    images: list[ChatImage] = []
    for item in raw_payload[:MAX_ATTACHED_FILES]:
        if isinstance(item, ChatImage):
            images.append(item)
            continue
        if not isinstance(item, Mapping) or not is_valid_chat_image_id(item.get("id")):
            continue
        try:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            continue
        images.append(
            ChatImage(id=str(item["id"]), name=str(item.get("name") or "image"), width=width, height=height)
        )
    return images


def estimate_image_input_tokens(image_inputs: Any) -> int:
    """Estimate the input tokens of the images carried by one message."""
    total = 0
    for image in decode_chat_images_from_storage(image_inputs):
        width = max(1, image.width)
        height = max(1, image.height)
        patches = math.ceil(width / _IMAGE_PATCH_PIXELS) * math.ceil(height / _IMAGE_PATCH_PIXELS)
        total += math.ceil(min(patches, _IMAGE_MAX_PATCHES) * _IMAGE_TOKEN_MULTIPLIER)
    return total


# 以前の回答は画像を読めるモデルが書いていることがあるため、それを疑わせない言い方にする。
# Earlier answers may come from a model that did read the image, so the note must not cast doubt on them.
def _unreadable_images_note(images: Sequence[ChatImage]) -> str:
    names = "、".join(image.name for image in images)
    return f"[添付画像: {names}（現在のモデルは画像を読めません。画像の内容は、この会話の中の説明を手がかりにしてください）]"


def apply_attached_images_for_model(
    messages: Sequence[Mapping[str, Any]],
    model_name: str | None,
) -> list[dict[str, Any]]:
    """Turn stored image references into model input, or a text note for text-only models.

    画像を読めるモデルには ``image_inputs`` として参照を渡し、アダプタが送信直前に実データへ
    変換する。読めないモデルには画像名の注記だけを本文へ足し、画像を黙って捨てない。
    Image-capable models receive ``image_inputs`` references that the adapter resolves just
    before sending; text-only models get a note naming the images instead of silently losing them.
    """
    accepts_images = model_accepts_image_input(model_name)
    updated: list[dict[str, Any]] = []
    for message in messages:
        new_message = dict(message)
        images = decode_chat_images_from_storage(new_message.pop(ATTACHED_IMAGES_KEY, None))
        if images and new_message.get("role") == "user":
            if accepts_images:
                new_message[IMAGE_INPUTS_KEY] = [image.to_storage() for image in images]
            else:
                new_message["content"] = f"{_unreadable_images_note(images)}\n\n{new_message.get('content', '')}"
        updated.append(new_message)
    return updated


def build_openai_image_parts(image_inputs: Any, *, responses_api: bool) -> list[dict[str, Any]]:
    """Load stored images and return OpenAI content parts for the chosen endpoint.

    Chat Completions は ``image_url`` を入れ子の object で、Responses API は ``input_image`` に
    data URL の文字列で受け取る。保存先から消えた画像（掃除済みなど）は送らない。
    Chat Completions nests the URL in an ``image_url`` object; the Responses API takes an
    ``input_image`` with a data URL string. Images missing from storage are skipped.
    """
    parts: list[dict[str, Any]] = []
    for image in decode_chat_images_from_storage(image_inputs):
        data = read_chat_image_bytes(image.id)
        if not data:
            continue
        data_url = f"data:{CHAT_IMAGE_MEDIA_TYPE};base64,{base64.b64encode(data).decode('ascii')}"
        if responses_api:
            parts.append({"type": "input_image", "image_url": data_url, "detail": "auto"})
        else:
            parts.append({"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}})
    return parts
