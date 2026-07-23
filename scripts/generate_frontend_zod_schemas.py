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
    ChatMessageRequest,
    ChatRoomIdRequest,
    ChatRoomIdsRequest,
    ContextExtractionSettingsUpdateRequest,
    ContextFactCandidateApproveRequest,
    ContextFactCandidateRejectRequest,
    ContextFactCreateRequest,
    ContextFactUpdateRequest,
    ContextVaultImportConfirmRequest,
    ContextVaultImportPreviewRequest,
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
    PromptTaskCreateRequest,
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
    ContextDigestGroup,
    ContextDigestResponse,
    ContextExtractionSettingsResponse,
    ContextFactCandidateApprovalResponse,
    ContextFactCandidateListResponse,
    ContextFactCandidateResponse,
    ContextFactListResponse,
    ContextFactResponse,
    ContextVaultExportDocument,
    ContextVaultImportPreviewResponse,
    ContextVaultImportResponse,
    ContextVaultPortableFact,
    LikedPromptApi,
    LikedPromptsApiResponse,
    MemoSaveResponse,
    MyPromptsApiResponse,
    PromptRecordApi,
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
    ("ChatRoomIdsRequest", ChatRoomIdsRequest),
    ("RenameChatRoomRequest", RenameChatRoomRequest),
    ("ShareChatRoomRequest", ShareChatRoomRequest),
    ("ChatMessageRequest", ChatMessageRequest),
    ("UpdateTasksOrderRequest", UpdateTasksOrderRequest),
    ("DeleteTaskRequest", DeleteTaskRequest),
    ("EditTaskRequest", EditTaskRequest),
    ("AddTaskRequest", AddTaskRequest),
    ("PromptAssistRequest", PromptAssistRequest),
    ("SharedPromptCreateRequest", SharedPromptCreateRequest),
    ("PromptTaskCreateRequest", PromptTaskCreateRequest),
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
    ("ContextFactCreateRequest", ContextFactCreateRequest),
    ("ContextFactUpdateRequest", ContextFactUpdateRequest),
    ("ContextVaultImportPreviewRequest", ContextVaultImportPreviewRequest),
    ("ContextVaultImportConfirmRequest", ContextVaultImportConfirmRequest),
    ("ContextFactCandidateApproveRequest", ContextFactCandidateApproveRequest),
    ("ContextFactCandidateRejectRequest", ContextFactCandidateRejectRequest),
    ("ContextExtractionSettingsUpdateRequest", ContextExtractionSettingsUpdateRequest),
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
    ("LikedPromptApi", LikedPromptApi),
    ("MyPromptsApiResponse", MyPromptsApiResponse),
    ("LikedPromptsApiResponse", LikedPromptsApiResponse),
    ("PromptManageMutationApiResponse", PromptManageMutationApiResponse),
    ("MemoSaveResponse", MemoSaveResponse),
    ("ContextFactResponse", ContextFactResponse),
    ("ContextFactListResponse", ContextFactListResponse),
    ("ContextVaultPortableFact", ContextVaultPortableFact),
    ("ContextVaultExportDocument", ContextVaultExportDocument),
    ("ContextVaultImportPreviewResponse", ContextVaultImportPreviewResponse),
    ("ContextVaultImportResponse", ContextVaultImportResponse),
    ("ContextFactCandidateResponse", ContextFactCandidateResponse),
    ("ContextFactCandidateListResponse", ContextFactCandidateListResponse),
    ("ContextFactCandidateApprovalResponse", ContextFactCandidateApprovalResponse),
    ("ContextExtractionSettingsResponse", ContextExtractionSettingsResponse),
    ("ContextDigestGroup", ContextDigestGroup),
    ("ContextDigestResponse", ContextDigestResponse),
]


# 日本語: 登録されているすべてのPydanticモデル定義からJSONスキーマを抽出し、再帰参照を解決したスキーマの一覧を生成します。
# English: Extract JSON schemas from all registered Pydantic models and resolve recursive references to generate a list of schemas.
def _collect_model_schemas() -> list[tuple[str, dict]]:
    collected: list[tuple[str, dict]] = []
    # 日本語: モデルレジストリ内の各Pydanticモデルに対して、JSONスキーマを生成し、再帰定義を解決した上でリストに追加します。
    # English: For each Pydantic model in the model registry, generate its JSON schema, resolve recursive definitions, and append to the list.
    for symbol, model in MODEL_REGISTRY:
        raw_schema = model.model_json_schema()
        collected.append((symbol, _schema_without_defs(raw_schema)))
    return collected


# 日本語: 収集したすべてのモデルのJSONスキーマの構造に基づいて、ユニークなSHA-256フィンガープリント（ハッシュ値）を生成します。
# English: Generate a unique SHA-256 fingerprint (hash value) based on the structure of all collected Pydantic model JSON schemas.
def get_schema_fingerprint() -> str:
    model_schemas = {symbol: schema for symbol, schema in _collect_model_schemas()}
    payload = json.dumps(
        model_schemas,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 日本語: スキーマ内の `$defs` に格納されている参照定義オブジェクトを解決し、各フィールドの `$ref` 参照部分へインライン展開します。
# English: Resolve reference definitions stored in `$defs` within the schema and inline them into each corresponding `$ref` reference.
def _schema_without_defs(schema: dict) -> dict:
    defs = schema.get("$defs")

    # 日本語: スキーマツリーを再帰的に走査し、見つかった `$ref` 参照定義を実際のオブジェクト内容に置き換えます。
    # English: Recursively traverse the schema tree, replacing any encountered `$ref` reference definitions with their actual object contents.
    def dereference(node):
        # 日本語: 辞書型（dict）ノード内の `$ref` キーを判定し、`$defs` 内の対応する定義内容とマージ・展開します。
        # English: Detect `$ref` keys inside dictionary nodes, then merge and expand them with corresponding definitions from `$defs`.
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
        # 日本語: リスト型（list）ノードの場合、各要素に対して再帰的に参照解決を適用します。
        # English: For list nodes, recursively apply reference resolution to each element.
        if isinstance(node, list):
            return [dereference(item) for item in node]
        return node

    return dereference(schema)


# 日本語: json-schema-to-zod ツールが生成した JS/TS コードの定数宣言を、フロントエンドで利用可能な `export const ...Schema = ...` 形式に正規化します。
# English: Normalize the constant declarations in the JS/TS code generated by json-schema-to-zod into `export const ...Schema = ...` format for frontend usage.
def _normalize_zod_export(code: str, symbol: str) -> str:
    normalized = code.strip()
    prefix = f"const {symbol} = "
    # 日本語: 生成されたコードが想定された定数定義プレフィックスで始まっていない場合はエラーをスローします。
    # English: Throw an error if the generated code does not start with the expected constant definition prefix.
    if not normalized.startswith(prefix):
        raise RuntimeError(f"Unexpected generator output for {symbol}: {normalized[:120]}")
    return f"export const {symbol}Schema = {normalized[len(prefix):]};"


# 日本語: JSONスキーマを受け取り、npmツール `json-schema-to-zod` をサブプロセスとして実行してZodスキーマのTypeScriptコードに変換します。
# English: Receive a JSON schema and convert it into Zod schema TypeScript code by executing the `json-schema-to-zod` npm package as a subprocess.
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
            "4",
        ],
        input=schema_json,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )
    # 日本語: サブプロセスの実行ステータスが正常終了（0）でない場合はエラーをスローします。
    # English: Throw an error if the execution status of the subprocess does not complete successfully (non-zero exit code).
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to generate Zod schema for {symbol}: {proc.stderr.strip()}")
    return _normalize_zod_export(proc.stdout, symbol)


# 日本語: スキーマ生成処理のメインエントリーポイントです。収集、変換、型定義の追加を行い、`api_schemas.ts` ファイルへ書き出します。
# English: Main entry point for the schema generation process. Handles collection, conversion, type inference addition, and writes to `api_schemas.ts`.
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

    # 日本語: 収集した各モデルスキーマをZodスキーマ定義に変換し、TypeScriptの型推論定義（z.infer）とともに出力行リストへ追加します。
    # English: Convert each collected model schema into a Zod schema definition, and append it along with TypeScript type inference definitions (z.infer) to the output list.
    for symbol, schema in model_schemas:
        lines.append(_convert_schema_to_zod(symbol, schema))
        lines.append(f"export type {symbol} = z.infer<typeof {symbol}Schema>;")
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n"
    GENERATED_FILE.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
