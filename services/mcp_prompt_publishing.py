"""MCP-specific decoding and persistence for prompt-share images."""

from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import urlsplit

import requests
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from services.error_messages import (
    ERROR_MCP_PROMPT_IMAGE_BASE64_INVALID,
    ERROR_MCP_PROMPT_IMAGE_DATA_URL_INVALID,
    ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED,
    ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_URL_INVALID,
    ERROR_MCP_PROMPT_IMAGE_FORMAT_UNKNOWN,
    ERROR_MCP_PROMPT_IMAGE_METADATA_MISMATCH,
    ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED,
    ERROR_MCP_PROMPT_IMAGE_TOO_LARGE,
    ERROR_PROMPT_ATTACHMENT_EMPTY,
    ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH,
)
from services.prompt_attachment_storage import PROMPT_ATTACHMENT_MAX_BYTES
from services.prompt_attachment_upload import (
    infer_prompt_attachment_mime_type,
    save_prompt_attachment,
)

MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH = ((PROMPT_ATTACHMENT_MAX_BYTES + 2) // 3) * 4 + 64
MCP_PROMPT_IMAGE_FILENAME_MAX_LENGTH = 255
MCP_PROMPT_IMAGE_MIME_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)
_DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)
_MIME_TO_EXTENSION = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_OPENAI_FILE_DOWNLOAD_HOST = "files.oaiusercontent.com"
_OPENAI_FILE_DOWNLOAD_TIMEOUT_SECONDS = (5, 20)
_DOWNLOAD_CHUNK_BYTES = 64 * 1024


class OpenAIFileInput(BaseModel):
    """ChatGPT file parameter payload documented for ``openai/fileParams``."""

    model_config = ConfigDict(extra="forbid")

    download_url: AnyHttpUrl
    file_id: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=127)
    file_name: str = Field(default="", max_length=MCP_PROMPT_IMAGE_FILENAME_MAX_LENGTH)


def _decode_mcp_image_base64(image_base64: str) -> tuple[bytes, str | None]:
    """Decode a strict Base64 image value, accepting an optional data URL prefix."""
    encoded = "".join(str(image_base64 or "").split())
    if not encoded:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)

    data_url_match = _DATA_URL_PATTERN.fullmatch(encoded)
    data_url_mime: str | None = None
    if data_url_match is not None:
        data_url_mime = data_url_match.group("mime").strip().lower()
        if data_url_mime not in MCP_PROMPT_IMAGE_MIME_TYPES:
            raise ValueError(ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED)
        encoded = data_url_match.group("data")
    elif encoded.lower().startswith("data:"):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_DATA_URL_INVALID)

    if len(encoded) > MCP_PROMPT_IMAGE_BASE64_MAX_LENGTH:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_BASE64_INVALID) from exc
    if not decoded:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_EMPTY)
    if len(decoded) > PROMPT_ATTACHMENT_MAX_BYTES:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
    return decoded, data_url_mime


def save_mcp_prompt_image(
    image_base64: str,
    user_id: int,
    *,
    filename: str = "",
    mime_type: str = "",
) -> dict[str, str]:
    """Decode and save one MCP prompt reference image through the shared upload boundary."""
    source, data_url_mime = _decode_mcp_image_base64(image_base64)
    return _save_mcp_prompt_image_source(
        source,
        user_id,
        filename=filename,
        mime_type=mime_type,
        source_mime_type=data_url_mime,
    )


def _save_mcp_prompt_image_source(
    source: bytes,
    user_id: int,
    *,
    filename: str = "",
    mime_type: str = "",
    source_mime_type: str | None = None,
) -> dict[str, str]:
    """Validate declared metadata and persist already-loaded MCP image bytes."""
    declared_mime = str(mime_type or "").strip().lower()
    if declared_mime and declared_mime not in MCP_PROMPT_IMAGE_MIME_TYPES:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_MIME_UNSUPPORTED)
    if source_mime_type and declared_mime and source_mime_type != declared_mime:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_METADATA_MISMATCH)
    detected_mime = infer_prompt_attachment_mime_type(source)
    if detected_mime is None:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_FORMAT_UNKNOWN)
    resolved_mime = declared_mime or source_mime_type or detected_mime
    if resolved_mime != detected_mime:
        raise ValueError(ERROR_PROMPT_ATTACHMENT_FORMAT_MISMATCH)

    resolved_filename = str(filename or "").strip()
    if not resolved_filename:
        resolved_filename = f"reference{_MIME_TO_EXTENSION[resolved_mime]}"
    return save_prompt_attachment(
        source,
        user_id,
        "image",
        filename=resolved_filename,
        content_type=resolved_mime,
    )


def _validate_openai_file_download_url(download_url: str) -> str:
    """Allow only HTTPS URLs issued from ChatGPT's documented file host."""
    parsed = urlsplit(str(download_url))
    hostname = (parsed.hostname or "").rstrip(".").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_URL_INVALID) from exc
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not (
            hostname == _OPENAI_FILE_DOWNLOAD_HOST
            or hostname.endswith(f".{_OPENAI_FILE_DOWNLOAD_HOST}")
        )
    ):
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_URL_INVALID)
    return parsed.geturl()


def _download_openai_file(download_url: str) -> tuple[bytes, str]:
    """Fetch one bounded ChatGPT file without following redirects."""
    validated_url = _validate_openai_file_download_url(download_url)
    try:
        with requests.get(
            validated_url,
            headers={"Accept": "image/*", "Accept-Encoding": "identity"},
            stream=True,
            allow_redirects=False,
            timeout=_OPENAI_FILE_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            if response.status_code != 200:
                raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED)
            content_length = response.headers.get("Content-Length", "").strip()
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED) from exc
                if declared_length < 0:
                    raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED)
                if declared_length > PROMPT_ATTACHMENT_MAX_BYTES:
                    raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)

            source = bytearray()
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                source.extend(chunk)
                if len(source) > PROMPT_ATTACHMENT_MAX_BYTES:
                    raise ValueError(ERROR_MCP_PROMPT_IMAGE_TOO_LARGE)
            response_mime = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
    except ValueError:
        raise
    except requests.RequestException as exc:
        raise ValueError(ERROR_MCP_PROMPT_IMAGE_DOWNLOAD_FAILED) from exc
    return bytes(source), response_mime


def save_mcp_prompt_file(image_file: OpenAIFileInput, user_id: int) -> dict[str, str]:
    """Download and save one ChatGPT ``openai/fileParams`` image."""
    source, response_mime = _download_openai_file(str(image_file.download_url))
    declared_mime = image_file.mime_type.strip().lower()
    if not declared_mime and response_mime in MCP_PROMPT_IMAGE_MIME_TYPES:
        declared_mime = response_mime
    return _save_mcp_prompt_image_source(
        source,
        user_id,
        filename=image_file.file_name,
        mime_type=declared_mime,
    )
