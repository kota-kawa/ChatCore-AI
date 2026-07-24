from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from pydantic import AnyHttpUrl, BaseModel, Field

from services.prompt_categories import category_keys_matching, normalize_category
from services.prompt_types import CONTENT_FORMATS, MEDIA_TYPES, serialize_axes
from services.repositories.prompt_resource_repository import PromptResourceRepository
from services.repositories.shared_content_repository import SharedContentRepository
from services.web_urls import build_frontend_url


SHARED_CONTENT_DEFAULT_LIMIT = 20
SHARED_CONTENT_MAX_LIMIT = 50
SHARED_CONTENT_SNIPPET_LENGTH = 280
SHARED_CONTENT_MAX_QUERY_LENGTH = 500


class InvalidSharedContentCursor(ValueError):
    """一覧カーソルが不正、または別の検索条件向けの場合に送出する。"""


class PublicSharedContentSummary(BaseModel):
    prompt_id: int
    title: str
    category: str = ""
    author: str
    content_format: str
    media_type: str
    snippet: str = ""
    created_at: datetime
    public_url: AnyHttpUrl


class PublicSharedContentPage(BaseModel):
    items: list[PublicSharedContentSummary] = Field(default_factory=list)
    limit: int
    has_next: bool
    next_cursor: str | None = None


class PublicSkillResourceMetadata(BaseModel):
    path: str
    role: str
    language: str = ""
    media_type: str = "text/plain"
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = ""


class PublicSkillResourceDetail(PublicSkillResourceMetadata):
    content: str = ""


class PublicSharedContentDetail(BaseModel):
    prompt_id: int
    title: str
    category: str = ""
    content: str = ""
    author: str
    content_format: str
    media_type: str
    attachments: list[dict[str, str]] = Field(default_factory=list)
    skill_markdown: str = ""
    resources: list[PublicSkillResourceMetadata] = Field(default_factory=list)
    # 旧クライアント向け。scripts/main.py の本文から派生し、新規保存には使用しない。
    skill_python_script: str = ""
    input_examples: str = ""
    output_examples: str = ""
    ai_model: str = ""
    created_at: datetime
    updated_at: datetime | None = None
    public_url: AnyHttpUrl


class SharedContentService:
    """MCP等のtransportから再利用できる公開投稿の読み取りサービス。"""

    def __init__(
        self,
        *,
        public_base_url: str,
        repository: SharedContentRepository | None = None,
        resource_repository: PromptResourceRepository | None = None,
    ) -> None:
        self._public_base_url = public_base_url
        self._repository = repository or SharedContentRepository()
        self._resource_repository = resource_repository or PromptResourceRepository()

    def list_public_content(
        self,
        *,
        query: str | None = None,
        limit: int = SHARED_CONTENT_DEFAULT_LIMIT,
        cursor: str | None = None,
        category: str | None = None,
        content_format: str | None = None,
        media_type: str | None = None,
    ) -> PublicSharedContentPage:
        normalized_query = self._normalize_query(query)
        normalized_category = self._normalize_category_filter(category)
        normalized_content_format = self._normalize_axis_filter(
            content_format,
            allowed=CONTENT_FORMATS,
            field_name="content_format",
        )
        normalized_media_type = self._normalize_axis_filter(
            media_type,
            allowed=MEDIA_TYPES,
            field_name="media_type",
        )
        normalized_limit = self._normalize_limit(limit)
        fingerprint = self._filter_fingerprint(
            query=normalized_query,
            category=normalized_category,
            content_format=normalized_content_format,
            media_type=normalized_media_type,
        )
        decoded_cursor = self._decode_cursor(cursor, expected_fingerprint=fingerprint)

        rows, has_next = self._repository.list_public_content(
            limit=normalized_limit,
            cursor=decoded_cursor,
            query=normalized_query or None,
            category=normalized_category,
            content_format=normalized_content_format,
            media_type=normalized_media_type,
            matching_category_keys=(
                category_keys_matching(normalized_query) if normalized_query else []
            ),
        )
        items = [self._summary_from_row(row) for row in rows]
        next_cursor = None
        if has_next and items:
            last = items[-1]
            next_cursor = self._encode_cursor(
                created_at=last.created_at,
                prompt_id=last.prompt_id,
                fingerprint=fingerprint,
            )
        return PublicSharedContentPage(
            items=items,
            limit=normalized_limit,
            has_next=has_next,
            next_cursor=next_cursor,
        )

    def get_public_content(self, prompt_id: int) -> PublicSharedContentDetail | None:
        if isinstance(prompt_id, bool) or int(prompt_id) <= 0:
            raise ValueError("prompt_id must be a positive integer.")
        row = self._repository.get_public_content(int(prompt_id))
        if row is None:
            return None

        axes = serialize_axes(row)
        resources = self._resource_metadata_for_prompt(int(row["id"]))
        skill_python_script = str(axes["skill_python_script"])
        if axes["content_format"] == "skill":
            legacy_resource = self._resource_repository.get_for_prompt(
                int(row["id"]),
                "scripts/main.py",
            )
            if legacy_resource is not None:
                skill_python_script = self._resource_content(legacy_resource)
        return PublicSharedContentDetail(
            prompt_id=int(row["id"]),
            title=str(row.get("title") or ""),
            category=str(row.get("category") or ""),
            content=str(row.get("content") or ""),
            author=str(row.get("author") or "ユーザー"),
            content_format=str(axes["content_format"]),
            media_type=str(axes["media_type"]),
            attachments=list(axes["attachments"]),
            skill_markdown=str(axes["skill_markdown"]),
            resources=resources,
            skill_python_script=skill_python_script,
            input_examples=str(row.get("input_examples") or ""),
            output_examples=str(row.get("output_examples") or ""),
            ai_model=str(row.get("ai_model") or ""),
            created_at=row["created_at"],
            updated_at=row.get("updated_at"),
            public_url=self._public_url(int(row["id"])),
        )

    def list_public_skill_resources(
        self,
        prompt_id: int,
    ) -> list[PublicSkillResourceMetadata] | None:
        row = self._get_public_skill_row(prompt_id)
        if row is None:
            return None
        return self._resource_metadata_for_prompt(int(row["id"]))

    def get_public_skill_resource(
        self,
        prompt_id: int,
        path: str,
    ) -> PublicSkillResourceDetail | None:
        row = self._get_public_skill_row(prompt_id)
        if row is None:
            return None
        normalized_path = str(path or "").strip()
        if not normalized_path:
            raise ValueError("path must not be blank.")
        resource = self._resource_repository.get_for_prompt(int(row["id"]), normalized_path)
        if resource is None:
            return None
        metadata = self._resource_metadata(resource)
        return PublicSkillResourceDetail(
            **metadata.model_dump(),
            content=self._resource_content(resource),
        )

    def _get_public_skill_row(self, prompt_id: int) -> dict[str, Any] | None:
        if isinstance(prompt_id, bool) or int(prompt_id) <= 0:
            raise ValueError("prompt_id must be a positive integer.")
        row = self._repository.get_public_content(int(prompt_id))
        if row is None:
            return None
        axes = serialize_axes(row)
        if axes["content_format"] != "skill":
            raise ValueError("指定された投稿はSKILLではありません。")
        return row

    def _resource_metadata_for_prompt(
        self,
        prompt_id: int,
    ) -> list[PublicSkillResourceMetadata]:
        return [
            self._resource_metadata(resource)
            for resource in self._resource_repository.list_for_prompt(prompt_id)
        ]

    @classmethod
    def _resource_metadata(cls, resource: object) -> PublicSkillResourceMetadata:
        data = cls._resource_mapping(resource)
        content = str(data.get("text_content") or data.get("content") or "")
        return PublicSkillResourceMetadata(
            path=str(data.get("path") or ""),
            role=str(data.get("role") or "other"),
            language=str(data.get("language") or ""),
            media_type=str(data.get("media_type") or "text/plain"),
            size_bytes=int(data.get("size_bytes") or len(content.encode("utf-8"))),
            sha256=str(data.get("sha256") or ""),
        )

    @classmethod
    def _resource_content(cls, resource: object) -> str:
        data = cls._resource_mapping(resource)
        return str(data.get("text_content") or data.get("content") or "")

    @staticmethod
    def _resource_mapping(resource: object) -> Mapping[str, Any]:
        if isinstance(resource, Mapping):
            return resource
        model_dump = getattr(resource, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        raise TypeError("resource must be a mapping or Pydantic model.")

    @staticmethod
    def _normalize_limit(value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer.") from exc
        if parsed <= 0:
            raise ValueError("limit must be a positive integer.")
        return min(parsed, SHARED_CONTENT_MAX_LIMIT)

    @staticmethod
    def _normalize_query(value: str | None) -> str:
        if value is None:
            return ""
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("query must not be blank.")
        if len(normalized) > SHARED_CONTENT_MAX_QUERY_LENGTH:
            raise ValueError(
                f"query must be {SHARED_CONTENT_MAX_QUERY_LENGTH} characters or fewer."
            )
        return normalized

    @staticmethod
    def _normalize_category_filter(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw or raw.lower() == "all":
            return None
        normalized = normalize_category(raw)
        if normalized is None:
            raise ValueError("category is invalid.")
        return normalized

    @staticmethod
    def _normalize_axis_filter(
        value: str | None,
        *,
        allowed: dict[str, Any],
        field_name: str,
    ) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized == "all":
            return None
        if normalized not in allowed:
            raise ValueError(f"{field_name} is invalid.")
        return normalized

    @staticmethod
    def _filter_fingerprint(
        *,
        query: str,
        category: str | None,
        content_format: str | None,
        media_type: str | None,
    ) -> str:
        serialized = json.dumps(
            {
                "query": query.casefold(),
                "category": category,
                "content_format": content_format,
                "media_type": media_type,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _encode_cursor(
        *,
        created_at: datetime,
        prompt_id: int,
        fingerprint: str,
    ) -> str:
        payload = json.dumps(
            {
                "created_at": created_at.isoformat(),
                "id": prompt_id,
                "filter": fingerprint,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(
        value: str | None,
        *,
        expected_fingerprint: str,
    ) -> tuple[datetime, int] | None:
        if not value:
            return None
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            payload = json.loads(decoded)
            if not isinstance(payload, dict) or payload.get("filter") != expected_fingerprint:
                raise ValueError
            created_at = payload.get("created_at")
            prompt_id = payload.get("id")
            if not isinstance(created_at, str) or isinstance(prompt_id, bool):
                raise ValueError
            parsed_id = int(prompt_id)
            if parsed_id <= 0:
                raise ValueError
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")), parsed_id
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            raise InvalidSharedContentCursor("The shared-content cursor is invalid.") from exc

    def _summary_from_row(self, row: dict[str, Any]) -> PublicSharedContentSummary:
        axes = serialize_axes(row)
        return PublicSharedContentSummary(
            prompt_id=int(row["id"]),
            title=str(row.get("title") or ""),
            category=str(row.get("category") or ""),
            author=str(row.get("author") or "ユーザー"),
            content_format=str(axes["content_format"]),
            media_type=str(axes["media_type"]),
            snippet=self._make_snippet(str(row.get("snippet_source") or "")),
            created_at=row["created_at"],
            public_url=self._public_url(int(row["id"])),
        )

    @staticmethod
    def _make_snippet(value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) <= SHARED_CONTENT_SNIPPET_LENGTH:
            return normalized
        return normalized[: SHARED_CONTENT_SNIPPET_LENGTH - 1].rstrip() + "…"

    def _public_url(self, prompt_id: int) -> str:
        return build_frontend_url(
            self._public_base_url,
            f"/shared/prompt/{prompt_id}",
        )
