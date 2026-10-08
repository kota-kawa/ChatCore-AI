"""生成UIの中で Web 検索画像を使うための参照と、その解決。

References that let a generated UI use web-search images, and their resolution.

モデルは画像URLを書かず、`web-image:1` のような番号だけを書く。番号はそのターンでサーバーが
選んだ検索画像の並び順で、モデルにはツール結果の `generated_ui_images` として渡す。保存する
Artifact には、使われた番号に対応する署名付きの中継パスを `images` として添え、ブラウザは
iframe を組み立てるときに番号を中継URLへ置き換える。

The model never writes an image URL, only a numbered reference such as `web-image:1`. The number
is the position of a search image the server selected for this turn, handed to the model as
`generated_ui_images` in the tool result. The stored Artifact carries the signed relay path for
each number it uses as `images`, and the browser swaps the number for the relay URL when it
builds the iframe.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from services.message_parts_display import GENERATIVE_UI_PART_TYPES, MAX_WEB_SEARCH_IMAGES_PER_REPLY
from services.web_search_image_proxy import (
    build_web_search_image_proxy_path,
    is_signed_web_search_image_proxy_path,
)
from services.web_search_images import build_web_search_image_parts

WEB_IMAGE_REFERENCE_SCHEME = "web-image:"
GENERATED_UI_IMAGES_TOOL_KEY = "generated_ui_images"

_WEB_IMAGE_REFERENCE_RE = re.compile(rf"{WEB_IMAGE_REFERENCE_SCHEME}(\d{{1,2}})(?!\d)")
_ARTIFACT_SOURCE_FIELDS = ("html", "css", "js")


class GenerativeUiImageV1(BaseModel):
    """One web-search image a generated UI is allowed to load."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ref: int = Field(ge=1, le=MAX_WEB_SEARCH_IMAGES_PER_REPLY)
    url: str
    source_url: str = Field(max_length=1000)
    source_title: str = Field(default="", max_length=160)

    # 署名はサーバーが選んだ画像にしか付かない。モデルが `images` を書いてもここで落ちる。
    # Only server-selected images carry a signature, so a model-written `images` fails here.
    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        if not is_signed_web_search_image_proxy_path(value):
            raise ValueError("Image URL is not a signed relay path.")
        return value

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("Image source URL is invalid.") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Image source URL is invalid.")
        return value


def is_web_image_reference(value: str) -> bool:
    """Whether *value* is exactly one numbered image reference."""
    return _WEB_IMAGE_REFERENCE_RE.fullmatch(value) is not None


def valid_generated_ui_images(raw_images: Any) -> list[dict[str, Any]]:
    """Keep the stored image entries that still validate, one per reference number."""
    if not isinstance(raw_images, list):
        return []
    images: list[dict[str, Any]] = []
    seen_refs: set[int] = set()
    for raw_image in raw_images:
        try:
            image = GenerativeUiImageV1.model_validate(raw_image)
        except ValidationError:
            continue
        if image.ref in seen_refs:
            continue
        seen_refs.add(image.ref)
        images.append(image.model_dump())
    return images


def _numbered_selected_images(selections: Any) -> dict[int, dict[str, Any]]:
    return {
        index: image_part["image"]
        for index, image_part in enumerate(build_web_search_image_parts(selections), start=1)
    }


def build_generated_ui_image_catalog(selections: Any) -> list[dict[str, str]]:
    """List the selected images for the model, by reference number and without URLs."""
    return [
        {
            "ref": f"{WEB_IMAGE_REFERENCE_SCHEME}{ref}",
            "alt": image["alt"],
            "source_title": image["source_title"],
        }
        for ref, image in _numbered_selected_images(selections).items()
    ]


def _referenced_image_numbers(artifact: dict[str, Any]) -> list[int]:
    numbers: set[int] = set()
    for field_name in _ARTIFACT_SOURCE_FIELDS:
        source = artifact.get(field_name)
        if isinstance(source, str):
            numbers.update(int(number) for number in _WEB_IMAGE_REFERENCE_RE.findall(source))
    return sorted(numbers)


def attach_web_search_images_to_artifacts(
    parts: list[dict[str, Any]] | None,
    selections: Any,
) -> list[dict[str, Any]] | None:
    """Give each generated UI the signed relay paths of the selected images it references."""
    if not parts or not selections:
        return parts
    numbered_images = _numbered_selected_images(selections)
    if not numbered_images:
        return parts

    attached_parts: list[dict[str, Any]] = []
    for part in parts:
        artifact = part.get("artifact")
        if part.get("type") not in GENERATIVE_UI_PART_TYPES or not isinstance(artifact, dict):
            attached_parts.append(part)
            continue
        # 検証を通らない画像（中継パスに収まらない長さのURLなど）は、保存する前にここで外す。
        # Images that would fail validation, such as a URL too long for a relay path, are left
        # out here rather than stored.
        images = valid_generated_ui_images(
            [
                {
                    "ref": number,
                    "url": build_web_search_image_proxy_path(numbered_images[number]["url"]),
                    "source_url": numbered_images[number]["source_url"],
                    "source_title": numbered_images[number]["source_title"],
                }
                for number in _referenced_image_numbers(artifact)
                if number in numbered_images
            ]
        )
        attached_parts.append({**part, "artifact": {**artifact, "images": images}} if images else part)
    return attached_parts
