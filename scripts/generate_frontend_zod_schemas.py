from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.request_models import (  # noqa: E402
    AddTaskRequest,
    AuthCodeRequest,
    BookmarkCreateRequest,
    BookmarkDeleteRequest,
    ChatMessageRequest,
    ChatRoomIdRequest,
    DeleteTaskRequest,
    EditTaskRequest,
    EmailRequest,
    MemoBulkActionRequest,
    MemoCollectionCreateRequest,
    MemoCollectionUpdateRequest,
    MemoCreateRequest,
    MemoShareCreateRequest,
    MemoSuggestRequest,
    MemoToggleRequest,
    MemoUpdateRequest,
    NewChatRoomRequest,
    PromptAssistRequest,
    PromptListEntryCreateRequest,
    PromptUpdateRequest,
    RenameChatRoomRequest,
    ShareChatRoomRequest,
    ShareMemoRequest,
    SharedPromptCreateRequest,
    UpdateTasksOrderRequest,
)
from services.response_models import (  # noqa: E402
    ApiDetailObject,
    ApiErrorPayload,
    ChatHistoryMessage,
    ChatHistoryPagination,
    ChatGenerationStatusResponse,
    ChatHistoryResponse,
    ChatJsonResponse,
    MemoSaveResponse,
    MyPromptsApiResponse,
    PromptListEntryApi,
    PromptListEntryLegacyApi,
    PromptRecordApi,
    PromptListApiResponse,
    PromptManageMutationApiResponse,
    ShareChatRoomResponse,
    StoredChatHistoryEntry,
)
FRONTEND_GENERATED_DIR = REPO_ROOT / "frontend" / "types" / "generated"
GENERATED_FILE = FRONTEND_GENERATED_DIR / "api_schemas.ts"


MODEL_REGISTRY: list[tuple[str, type[BaseModel]]] = [
    # Request payloads (source of truth: services/request_models.py)
    ("EmailRequest", EmailRequest),
    ("AuthCodeRequest", AuthCodeRequest),
    ("NewChatRoomRequest", NewChatRoomRequest),
    ("ChatRoomIdRequest", ChatRoomIdRequest),
    ("RenameChatRoomRequest", RenameChatRoomRequest),
    ("ShareChatRoomRequest", ShareChatRoomRequest),
    ("ChatMessageRequest", ChatMessageRequest),
    ("UpdateTasksOrderRequest", UpdateTasksOrderRequest),
    ("DeleteTaskRequest", DeleteTaskRequest),
    ("EditTaskRequest", EditTaskRequest),
    ("AddTaskRequest", AddTaskRequest),
    ("PromptAssistRequest", PromptAssistRequest),
    ("SharedPromptCreateRequest", SharedPromptCreateRequest),
    ("BookmarkCreateRequest", BookmarkCreateRequest),
    ("BookmarkDeleteRequest", BookmarkDeleteRequest),
    ("PromptListEntryCreateRequest", PromptListEntryCreateRequest),
    ("PromptUpdateRequest", PromptUpdateRequest),
    ("MemoCreateRequest", MemoCreateRequest),
    ("ShareMemoRequest", ShareMemoRequest),
    ("MemoUpdateRequest", MemoUpdateRequest),
    ("MemoToggleRequest", MemoToggleRequest),
    ("MemoShareCreateRequest", MemoShareCreateRequest),
    ("MemoSuggestRequest", MemoSuggestRequest),
    ("MemoBulkActionRequest", MemoBulkActionRequest),
    ("MemoCollectionCreateRequest", MemoCollectionCreateRequest),
    ("MemoCollectionUpdateRequest", MemoCollectionUpdateRequest),
    # Response payloads (source of truth: services/response_models.py)
    ("ApiErrorPayload", ApiErrorPayload),
    ("ApiDetailObject", ApiDetailObject),
    ("ChatJsonResponse", ChatJsonResponse),
    ("ChatGenerationStatusResponse", ChatGenerationStatusResponse),
    ("ChatHistoryMessage", ChatHistoryMessage),
    ("ChatHistoryPagination", ChatHistoryPagination),
    ("ChatHistoryResponse", ChatHistoryResponse),
    ("ShareChatRoomResponse", ShareChatRoomResponse),
    ("StoredChatHistoryEntry", StoredChatHistoryEntry),
    ("PromptRecordApi", PromptRecordApi),
    ("PromptListEntryApi", PromptListEntryApi),
    ("PromptListEntryLegacyApi", PromptListEntryLegacyApi),
    ("MyPromptsApiResponse", MyPromptsApiResponse),
    ("PromptListApiResponse", PromptListApiResponse),
    ("PromptManageMutationApiResponse", PromptManageMutationApiResponse),
    ("MemoSaveResponse", MemoSaveResponse),
]


def _collect_model_schemas() -> list[tuple[str, dict]]:
    collected: list[tuple[str, dict]] = []
    for symbol, model in MODEL_REGISTRY:
        raw_schema = model.model_json_schema()
        collected.append((symbol, _schema_without_defs(raw_schema)))
    return collected


def get_schema_fingerprint() -> str:
    model_schemas = {symbol: schema for symbol, schema in _collect_model_schemas()}
    payload = json.dumps(
        model_schemas,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_without_defs(schema: dict) -> dict:
    defs = schema.get("$defs")

    def dereference(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                key = ref.split("/")[-1]
                target = defs.get(key) if isinstance(defs, dict) else None
                if isinstance(target, dict):
                    merged = deepcopy(target)
                    for k, v in node.items():
                        if k == "$ref":
                            continue
                        merged[k] = dereference(v)
                    return dereference(merged)
            return {
                key: dereference(value)
                for key, value in node.items()
                if key != "$defs"
            }
        if isinstance(node, list):
            return [dereference(item) for item in node]
        return node

    return dereference(schema)


def _normalize_zod_export(code: str, symbol: str) -> str:
    normalized = code.strip()
    prefix = f"const {symbol} = "
    if not normalized.startswith(prefix):
        raise RuntimeError(f"Unexpected generator output for {symbol}: {normalized[:120]}")
    return f"export const {symbol}Schema = {normalized[len(prefix):]};"


def _convert_schema_to_zod(symbol: str, schema: dict) -> str:
    schema_json = json.dumps(schema, ensure_ascii=False)
    proc = subprocess.run(
        [
            "npm",
            "--prefix",
            "frontend",
            "exec",
            "json-schema-to-zod",
            "--",
            "--name",
            symbol,
            "--module",
            "none",
            "--zodVersion",
            "3",
        ],
        input=schema_json,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to generate Zod schema for {symbol}: {proc.stderr.strip()}")
    return _normalize_zod_export(proc.stdout, symbol)


def main() -> None:
    FRONTEND_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    model_schemas = _collect_model_schemas()
    fingerprint = get_schema_fingerprint()

    lines: list[str] = [
        '// AUTO-GENERATED FILE. DO NOT EDIT MANUALLY.',
        '// Source of truth: backend Pydantic models in services/request_models.py and services/response_models.py',
        '// Regenerate with: python3 scripts/generate_frontend_zod_schemas.py',
        f"// Schema fingerprint: {fingerprint}",
        "",
        'import { z } from "zod";',
        "",
    ]

    for symbol, schema in model_schemas:
        lines.append(_convert_schema_to_zod(symbol, schema))
        lines.append(f"export type {symbol} = z.infer<typeof {symbol}Schema>;")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    GENERATED_FILE.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
