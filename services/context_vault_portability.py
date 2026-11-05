"""個人コンテキスト（Context Vault）のエクスポート／インポート（JSON・Markdown）を扱う。
形式にはバージョンを持たせ、所有者単位で処理する。インポートは「プレビュー → 確定」の 2 段階で、
プレビューで発行した署名付きトークンと内容のダイジェストが一致した場合だけ確定できる。

Versioned, owner-scoped export/import (JSON and Markdown) for the personal context vault.
Import is two-step (preview, then confirm): confirmation requires the signed preview token to match the content digest.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, TypeVar

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.context_vault_embeddings import schedule_embedding
from services.db import is_retryable_db_error, session_scope
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

# 日本語: Markdown 形式の目印と事実ブロック（```context-fact の 1 行 JSON）を厳密に見つける正規表現。
# 開始行の数とブロック全体の一致数が違えば、壊れたブロックがあるとして拒否する。
# English: Regexes that strictly locate the Markdown version marker and fact blocks (a one-line JSON in ```context-fact).
# If the number of opening fences differs from the number of full matches, the document is rejected as malformed.
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
# 日本語: プレビュー用トークンの署名ソルト。他用途の署名と取り違えないよう用途専用の値にしている。
# English: Signing salt for preview tokens, dedicated to this use so it cannot be confused with other signatures.
_TOKEN_SALT = "chat-core.context-vault-import-preview.v1"

ImportFormat = Literal["json", "markdown"]
MAX_DB_WRITE_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05
T = TypeVar("T")


def _repository(session: AsyncSession) -> ContextFactRepository:
    return ContextFactRepository(session)


# 日本語: session があればそのまま使い、なければ新規トランザクションで実行する。
# 一時的な DB エラーのときだけバックオフ付きで再試行する。
# English: Use the given session as is, otherwise run in a new transaction,
# retrying with backoff only on retryable DB errors.
async def _transaction(
    session: AsyncSession | None,
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    if session is not None:
        return await operation(session)
    for attempt in range(MAX_DB_WRITE_ATTEMPTS):
        try:
            async with session_scope() as db, db.begin():
                return await operation(db)
        except ApiServiceError:
            raise
        except SQLAlchemyError as exc:
            if attempt + 1 >= MAX_DB_WRITE_ATTEMPTS or not is_retryable_db_error(exc):
                raise
            await asyncio.sleep(DB_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("Context portability transaction retry loop exhausted.")


def _portable_fact(row: dict[str, Any]) -> ContextVaultPortableFact:
    return ContextVaultPortableFact(
        fact_type=row["fact_type"],
        title=row["title"],
        content=row["content"],
        status=row["status"],
        importance=row.get("importance", 50),
        confidence=row.get("confidence"),
        last_confirmed_at=row.get("last_confirmed_at"),
    )


# 日本語: 重複判定用のキー。種別・題名・本文・状態・重要度がすべて一致する事実を同一とみなす。
# English: Key for duplicate detection; facts with identical type, title, content, status and importance count as the same.
def _portable_signature(fact: ContextVaultPortableFact) -> tuple[str, str, str, str, int]:
    return (
        fact.fact_type,
        fact.title,
        fact.content,
        fact.status,
        fact.importance,
    )


# 日本語: 題名を Markdown の見出しに埋め込む前に、改行を潰して HTML と Markdown の記号をエスケープする。
# English: Collapse newlines and escape HTML and Markdown syntax before embedding a title in a heading.
def _escape_markdown_heading(value: str) -> str:
    escaped = html.escape(" ".join(value.splitlines()).strip(), quote=True)
    return re.sub(r"([\\`*_[\]{}()#+.!|>-])", r"\\\1", escaped)


# 日本語: UTF-8 に変換できない文字列は JSON 不正として扱い、サイズ上限（バイト数）も確認する。
# English: Strings that cannot be encoded as UTF-8 are treated as invalid JSON; the byte-size limit is also enforced.
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
    """サイズ上限のあるバージョン付きの移行ドキュメントを、形式（json / markdown）に応じて厳密に解析する。

    Strictly parse a bounded versioned portability document.
    """
    _validate_content_size(content)
    if import_format == "json":
        return _parse_json_document(content)
    if import_format == "markdown":
        return _parse_markdown_document(content)
    raise ApiServiceError(ERROR_CONTEXT_VAULT_IMPORT_FORMAT_INVALID, 400, status="fail")


# 日本語: 形式と事実一覧を正規化した JSON のハッシュ。プレビュー時と確定時で内容が同じか確かめるのに使う。
# English: Hash of the canonicalized format and fact list, used to verify that preview and confirm saw the same content.
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


# 日本語: セッション秘密鍵が未設定ならプレビュー署名を作れないため、503 で利用不可を返す。
# English: Without a session secret the preview token cannot be signed, so respond with 503 (unavailable).
def _preview_serializer() -> URLSafeTimedSerializer:
    secret = get_session_secret_key()
    if not secret:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_IMPORT_PREVIEW_UNAVAILABLE,
            503,
            status="fail",
        )
    return URLSafeTimedSerializer(secret, salt=_TOKEN_SALT)


# 日本語: ユーザー ID・形式・内容ダイジェストを署名したトークンを作る。
# English: Build a token that signs the user id, format and content digest.
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


# 日本語: 署名と有効期限を確認し、トークンが別ユーザー・別形式・別内容のものでないことも確かめる。
# English: Check signature and expiry, and ensure the token does not belong to another user, format or content.
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


async def _preview_database_state(
    session: AsyncSession,
    user_id: int,
    fact_payloads: list[dict[str, Any]],
) -> tuple[set[tuple[str, str, str, str, int]], int]:
    repo = _repository(session)
    return (
        await repo.find_existing_portable_signatures(user_id, fact_payloads),
        await repo.count_active(user_id),
    )


async def build_export(
    user_id: int,
    export_format: ImportFormat,
    *,
    session: AsyncSession | None = None,
) -> tuple[str, str, str]:
    """所有者の事実を切り捨てずにすべてエクスポートし、(本文, Content-Type, ファイル名) を返す。
    件数かサイズが上限を超える場合は、欠けたデータを渡さないよう 409 で失敗させる。

    Build a complete, non-truncated owner export.
    Returns (content, content type, filename); fails with 409 if count or size exceeds the limits,
    rather than handing out incomplete data.
    """
    rows = await _transaction(
        session,
        lambda db: _repository(db).list_all_facts(
            user_id,
            limit=MAX_CONTEXT_VAULT_IMPORT_FACTS + 1,
        ),
    )
    if len(rows) > MAX_CONTEXT_VAULT_IMPORT_FACTS:
        raise ApiServiceError(
            ERROR_CONTEXT_VAULT_EXPORT_TOO_MANY,
            409,
            status="fail",
        )

    facts = [_portable_fact(row) for row in rows]
    exported_at = datetime.now(UTC).isoformat()
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


async def preview_import(
    user_id: int,
    import_format: ImportFormat,
    content: str,
    *,
    session: AsyncSession | None = None,
) -> ContextVaultImportPreviewResponse:
    """データを変更せずに、インポート内容の検証と既存データとの比較を行い、確定用のトークンを発行する。
    完全一致する重複はスキップ扱いとして数え、有効な事実の上限を超える場合は can_import を False にする。

    Validate and compare an import without changing persistent state.
    Exact duplicates are counted as skipped, and can_import is False if the active-fact cap would be exceeded.
    """
    facts = parse_import_document(import_format, content)
    fact_payloads = [fact.model_dump(mode="python") for fact in facts]
    existing, current_active = await _transaction(
        session,
        lambda db: _preview_database_state(db, user_id, fact_payloads),
    )

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
    can_import = current_active + active_count <= MAX_ACTIVE_CONTEXT_FACTS
    warnings: list[str] = []
    if duplicate_count:
        warnings.append(f"完全一致する{duplicate_count}件はインポート時にスキップされます。")
    if not can_import:
        warnings.append(WARNING_CONTEXT_VAULT_IMPORT_ACTIVE_LIMIT)

    expires_at = datetime.now(UTC) + timedelta(
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


async def confirm_import(
    user_id: int,
    import_format: ImportFormat,
    content: str,
    preview_token: str,
    *,
    session: AsyncSession | None = None,
) -> ContextVaultImportResponse:
    """プレビューしたものと同一の内容を、上限を守る 1 つのトランザクションで追記する。
    トークンが一致しなければ書き込まず、追記された有効な事実には埋め込み生成を予約する。

    Append the exact previewed payload in one cap-safe transaction.
    Nothing is written if the token does not match; embeddings are scheduled for newly imported active facts.
    """
    facts = parse_import_document(import_format, content)
    _verify_preview_token(preview_token, user_id, import_format, facts)
    result = await _transaction(
        session,
        lambda db: _repository(db).bulk_import_facts(
            user_id,
            [fact.model_dump(mode="python") for fact in facts],
        ),
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
