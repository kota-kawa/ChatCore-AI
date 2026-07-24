"""Persistence boundary for resources bundled with shared SKILL posts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from services.db import get_db_connection
from services.prompt_resources import (
    resource_sha256,
    resource_size_bytes,
    validate_resource_path,
)


class PromptResourceRepository:
    """Store and retrieve prompt resources without owning the caller's transaction."""

    @staticmethod
    def _field(resource: object, name: str, default: str = "") -> str:
        if isinstance(resource, Mapping):
            value = resource.get(name, default)
        else:
            value = getattr(resource, name, default)
        return str(value if value is not None else default)

    def insert_many(
        self,
        cursor: Any,
        prompt_id: int,
        resources: Iterable[object],
    ) -> None:
        """Insert resources with the transaction-bound cursor supplied by the caller."""
        for sort_order, resource in enumerate(resources):
            content = self._field(resource, "content")
            cursor.execute(
                """
                INSERT INTO prompt_resources (
                    prompt_id, path, role, language, media_type, text_content,
                    storage_key, size_bytes, sha256, sort_order, created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    NULL, %s, %s, %s, NOW(), NOW()
                )
                """,
                (
                    int(prompt_id),
                    self._field(resource, "path"),
                    self._field(resource, "role", "other"),
                    self._field(resource, "language", "text"),
                    self._field(resource, "media_type", "text/plain"),
                    content,
                    resource_size_bytes(content),
                    resource_sha256(content),
                    sort_order,
                ),
            )

    def replace_for_prompt(
        self,
        cursor: Any,
        prompt_id: int,
        resources: Iterable[object],
    ) -> None:
        """Atomically replace all resources using the caller's transaction."""
        cursor.execute("DELETE FROM prompt_resources WHERE prompt_id = %s", (int(prompt_id),))
        self.insert_many(cursor, prompt_id, resources)

    def list_for_prompt(
        self,
        prompt_id: int,
        *,
        connection: Any | None = None,
    ) -> list[dict[str, Any]]:
        """List resources in stable package order."""
        conn = connection or get_db_connection()
        close_connection = connection is None
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id, prompt_id, path, role, language, media_type,
                    text_content AS content, storage_key, size_bytes, sha256,
                    sort_order, created_at, updated_at
                FROM prompt_resources
                WHERE prompt_id = %s
                ORDER BY sort_order ASC, id ASC
                """,
                (int(prompt_id),),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor is not None:
                cursor.close()
            if close_connection:
                conn.close()

    def get_for_prompt(
        self,
        prompt_id: int,
        path: str,
        *,
        connection: Any | None = None,
    ) -> dict[str, Any] | None:
        """Get one resource by its canonical path."""
        normalized_path = validate_resource_path(path)
        conn = connection or get_db_connection()
        close_connection = connection is None
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    id, prompt_id, path, role, language, media_type,
                    text_content AS content, storage_key, size_bytes, sha256,
                    sort_order, created_at, updated_at
                FROM prompt_resources
                WHERE prompt_id = %s
                  AND lower(path) = lower(%s)
                LIMIT 1
                """,
                (int(prompt_id), normalized_path),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if cursor is not None:
                cursor.close()
            if close_connection:
                conn.close()
