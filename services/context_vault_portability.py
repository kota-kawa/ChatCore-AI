"""Versioned, owner-scoped export/import for the personal context vault."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import ValidationError

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.error_messages import (
    ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID,
    ERROR_CONTEXT_VAULT_EXPORT_TOO_LARGE,
    ERROR_CONTEXT_VAULT_EXPORT_TOO_MANY,
    ERROR_CONTEXT_VAULT_IMPORT_EMPTY,
    ERROR_CONTEXT_VAULT_IMPORT_FORMAT_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_JSON_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_BLOCK_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_FACT_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_VERSION_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_EXPIRED,
    ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_INVALID,
    ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_MISMATCH,
    ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_UNAVAILABLE,
    ERROR_CONTEXT_VAULT_IMPORT_TOO_LARGE,
    ERROR_CONTEXT_VAULT_IMPORT_TOO_MANY,
    WARNING_CONTEXT_VAULT_IMPORT_ACTIVE_LIMIT,
)
from services.repositories.context_fact_repository import (
    MAX_ACTIVE_CONTEXT_FACTS,
    ContextFactRepository,
)
from services.response_models import (
    ContextVaultExportDocument,
    ContextVaultImportPreviewResponse,
    ContextVaultImportResponse,
    ContextVaultPortableFact,
)
from services.runtime_config import get_session_secret_key

CONTEXT_VAULT_FORMAT = "chat-core-personal-context"
CONTEXT_VAULT_FORMAT_VERSION = 1
MAX_CONTEXT_VAULT_IMPORT_BYTES = 10 * 1024 * 1024
MAX_CONTEXT_VAULT_IMPORT_FACTS = 1000
IMPORT_PREVIEW_TOKEN_TTL_SECONDS = 15 * 60
IMPORT_PREVIEW_SAMPLE_SIZE = 20

_MARKDOWN_VERSION_MARKER = "<!-- chat-core-context-vault-version: 1 -->"
_MARKDOWN_VERSION_MARKER_RE = re.compile(
    r"^<!-- chat-core-context-vault-version: 1 -->[ \t]*\r?$",
    re.MULTILINE,
)
_MARKDOWN_BLOCK_RE = re.compile(
    r"^```context-fact[ \t]*\r?\n(?P<payload>[^\r\n]+)\r?\n```[ \t]*\r?$",
    re.MULTILINE,
)
_MARKDOWN_BLOCK_OPEN_RE = re.compile(r"^```context-fact[ \t]*\r?$", re.MULTILINE)
_TOKEN_SALT = "chat-core.context-vault-import-preview.v1"

ImportFormat = Literal["json", "markdown"]


def _repository() -> ContextFactRepository:
    return ContextFactRepository()


def _portable_fact(row: dict[str, Any]) -> ContextVaultPortableFact:
    return ContextVaultPortableFact(
        fact_type=row["fact_type"],
        title=row["title"],
        content=row["content"],
        status=row["status"],
        importance=row.get("importance", 50),
    )


def _portable_signature(fact: ContextVaultPortableFact) -> tuple[str, str, str, str, int]:
    return (
        fact.fact_type,
        fact.title,
        fact.content,
        fact.status,
        fact.importance,
    )


def _escape_markdown_heading(value: str) -> str:
    escaped = html.escape(" ".join(value.splitlines()).strip(), quote=True)
    return re.sub(r"([\\`*_[\]{}()#+.!|>-])", r"\\\1", escaped)


def _validate_content_size(content: str) -> None:
    try:
        content_bytes = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_JSON_INVALID,
            400,
            status="fail",
        ) from exc
    if len(content_bytes) > MAX_CONTEXT_VAULT_IMPORT_BYTES:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_TOO_LARGE,
            413,
            status="fail",
        )


def _validate_import_facts(facts: list[ContextVaultPortableFact]) -> None:
    if not facts:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_EMPTY,
            400,
            status="fail",
        )
    if len(facts) > MAX_CONTEXT_VAULT_IMPORT_FACTS:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_TOO_MANY,
            413,
            status="fail",
        )


def _parse_json_document(content: str) -> list[ContextVaultPortableFact]:
    try:
        raw = json.loads(content)
        document = ContextVaultExportDocument.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError, RecursionError) as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_JSON_INVALID,
            400,
            status="fail",
        ) from exc
    facts = list(document.facts)
    _validate_import_facts(facts)
    return facts


def _parse_markdown_document(content: str) -> list[ContextVaultPortableFact]:
    if len(_MARKDOWN_VERSION_MARKER_RE.findall(content)) != 1:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_VERSION_INVALID,
            400,
            status="fail",
        )
    matches = list(_MARKDOWN_BLOCK_RE.finditer(content))
    if len(matches) != len(_MARKDOWN_BLOCK_OPEN_RE.findall(content)):
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_BLOCK_INVALID,
            400,
            status="fail",
        )

    facts: list[ContextVaultPortableFact] = []
    try:
        for match in matches:
            raw = json.loads(match.group("payload"))
            facts.append(ContextVaultPortableFact.model_validate(raw))
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError, RecursionError) as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_MARKDOWN_FACT_INVALID,
            400,
            status="fail",
        ) from exc
    _validate_import_facts(facts)
    return facts


def parse_import_document(
    import_format: ImportFormat,
    content: str,
) -> list[ContextVaultPortableFact]:
    """Strictly parse a bounded versioned portability document."""
    _validate_content_size(content)
    if import_format == "json":
        return _parse_json_document(content)
    if import_format == "markdown":
        return _parse_markdown_document(content)
    raise ApiServiceError(ERROR_CONTEXT_VAULT_IMPORT_FORMAT_INVALID, 400, status="fail")


def _canonical_digest(import_format: ImportFormat, facts: list[ContextVaultPortableFact]) -> str:
    canonical = json.dumps(
        {
            "format": import_format,
            "facts": [fact.model_dump(mode="json") for fact in facts],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _preview_serializer() -> URLSafeTimedSerializer:
    secret = get_session_secret_key()
    if not secret:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_UNAVAILABLE,
            503,
            status="fail",
        )
    return URLSafeTimedSerializer(secret, salt=_TOKEN_SALT)


def _build_preview_token(
    user_id: int,
    import_format: ImportFormat,
    facts: list[ContextVaultPortableFact],
) -> str:
    return _preview_serializer().dumps(
        {
            "user_id": user_id,
            "format": import_format,
            "digest": _canonical_digest(import_format, facts),
        }
    )


def _verify_preview_token(
    token: str,
    user_id: int,
    import_format: ImportFormat,
    facts: list[ContextVaultPortableFact],
) -> None:
    try:
        payload = _preview_serializer().loads(
            token,
            max_age=IMPORT_PREVIEW_TOKEN_TTL_SECONDS,
        )
    except SignatureExpired as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_EXPIRED,
            400,
            status="fail",
        ) from exc
    except BadSignature as exc:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_INVALID,
            400,
            status="fail",
        ) from exc

    expected_digest = _canonical_digest(import_format, facts)
    if (
        not isinstance(payload, dict)
        or payload.get("user_id") != user_id
        or payload.get("format") != import_format
        or payload.get("digest") != expected_digest
    ):
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_MISMATCH,
            400,
            status="fail",
        )


def build_export(user_id: int, export_format: ImportFormat) -> tuple[str, str, str]:
    """Build a complete, non-truncated owner export."""
    rows = _repository().list_all_facts(
        user_id,
        limit=MAX_CONTEXT_VAULT_IMPORT_FACTS + 1,
    )
    if len(rows) > MAX_CONTEXT_VAULT_IMPORT_FACTS:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_EXPORT_TOO_MANY,
            409,
            status="fail",
        )

    facts = [_portable_fact(row) for row in rows]
    exported_at = datetime.now(timezone.utc).isoformat()
    if export_format == "json":
        document = ContextVaultExportDocument(
            format=CONTEXT_VAULT_FORMAT,
            version=CONTEXT_VAULT_FORMAT_VERSION,
            exported_at=exported_at,
            facts=facts,
        )
        content = document.model_dump_json(indent=2)
        if len(content.encode("utf-8")) > MAX_CONTEXT_VAULT_IMPORT_BYTES:
            raise ApiServiceError(
                ERROR_CONTEXT_VAULT_EXPORT_TOO_LARGE,
                409,
                status="fail",
            )
        return (
            content,
            "application/json",
            "chat-core-context-vault.json",
        )
    if export_format == "markdown":
        sections = [
            "# Chat-Core Personal Context Vault",
            "",
            _MARKDOWN_VERSION_MARKER,
            "",
            f"Exported at: `{exported_at}`",
        ]
        for fact in facts:
            heading = _escape_markdown_heading(fact.title)
            sections.extend(
                [
                    "",
                    f"## {heading}",
                    "",
                    (
                        f"- Type: `{fact.fact_type}`"
                        f" · Status: `{fact.status}`"
                        f" · Importance: `{fact.importance}`"
                    ),
                    "",
                    "```context-fact",
                    fact.model_dump_json(),
                    "```",
                ]
            )
        content = "\n".join(sections) + "\n"
        if len(content.encode("utf-8")) > MAX_CONTEXT_VAULT_IMPORT_BYTES:
            raise ApiServiceError(
                ERROR_CONTEXT_VAULT_EXPORT_TOO_LARGE,
                409,
                status="fail",
            )
        return (
            content,
            "text/markdown; charset=utf-8",
            "chat-core-context-vault.md",
        )
    raise ApiServiceError(ERROR_CONTEXT_VAULT_EXPORT_FORMAT_INVALID, 400, status="fail")


def preview_import(
    user_id: int,
    import_format: ImportFormat,
    content: str,
) -> ContextVaultImportPreviewResponse:
    """Validate and compare an import without changing persistent state."""
    facts = parse_import_document(import_format, content)
    repo = _repository()
    fact_payloads = [fact.model_dump(mode="python") for fact in facts]
    existing = repo.find_existing_portable_signatures(user_id, fact_payloads)

    unique: list[ContextVaultPortableFact] = []
    seen: set[tuple[str, str, str, str, int]] = set()
    duplicate_count = 0
    for fact in facts:
        signature = _portable_signature(fact)
        if signature in seen or signature in existing:
            duplicate_count += 1
            continue
        seen.add(signature)
        unique.append(fact)

    active_count = sum(1 for fact in unique if fact.status == "active")
    deprecated_count = len(unique) - active_count
    current_active = repo.count_active(user_id)
    can_import = current_active + active_count <= MAX_ACTIVE_CONTEXT_FACTS
    warnings: list[str] = []
    if duplicate_count:
        warnings.append(f"完全一致する{duplicate_count}件はインポート時にスキップされます。")
    if not can_import:
        warnings.append(WARNING_CONTEXT_VAULT_IMPORT_ACTIVE_LIMIT)

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=IMPORT_PREVIEW_TOKEN_TTL_SECONDS
    )
    return ContextVaultImportPreviewResponse(
        preview_token=_build_preview_token(user_id, import_format, facts),
        total_count=len(facts),
        active_count=active_count,
        deprecated_count=deprecated_count,
        duplicate_count=duplicate_count,
        importable_count=len(unique),
        can_import=can_import,
        sample_facts=unique[:IMPORT_PREVIEW_SAMPLE_SIZE],
        warnings=warnings,
        expires_at=expires_at.isoformat(),
    )


def confirm_import(
    user_id: int,
    import_format: ImportFormat,
    content: str,
    preview_token: str,
) -> ContextVaultImportResponse:
    """Append the exact previewed payload in one cap-safe transaction."""
    facts = parse_import_document(import_format, content)
    _verify_preview_token(preview_token, user_id, import_format, facts)
    result = _repository().bulk_import_facts(
        user_id,
        [fact.model_dump(mode="python") for fact in facts],
    )
    for fact in result["facts"]:
        if fact["status"] == "active":
            schedule_embedding(
                int(fact["id"]),
                str(fact["fact_type"]),
                str(fact["title"]),
                str(fact["content"]),
                int(fact["revision"]),
            )
    return ContextVaultImportResponse(
        imported_count=len(result["facts"]),
        skipped_duplicate_count=int(result["skipped_duplicate_count"]),
        active_count=int(result["active_count"]),
        deprecated_count=int(result["deprecated_count"]),
    )
