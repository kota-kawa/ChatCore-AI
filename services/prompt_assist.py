from __future__ import annotations

import json
import re
from typing import Any

from services.llm import LlmProviderError, get_llm_response

PROMPT_ASSIST_MODEL = "openai/gpt-oss-20b"
PROMPT_ASSIST_TARGETS = {
    "task_modal": {
        "allowed_fields": ("title", "prompt_content", "input_examples", "output_examples"),
        "primary_field": "prompt_content",
        "target_label": "トップページのタスク追加モーダル",
        "context_fields": ("title", "prompt_content", "input_examples", "output_examples"),
    },
    "shared_prompt_modal": {
        "allowed_fields": ("title", "content", "input_examples", "output_examples"),
        "primary_field": "content",
        "target_label": "共有プロンプト投稿モーダル",
        "context_fields": (
            "title",
            "category",
            "content",
            "author",
            "prompt_type",
            "input_examples",
            "output_examples",
            "ai_model",
        ),
    },
}
PROMPT_ASSIST_ACTION_LABELS = {
    "generate_draft": "下書きを作る",
    "improve": "改善する",
    "shorten": "短くする",
    "expand": "詳しくする",
    "generate_examples": "入出力例を作る",
}
PROMPT_ASSIST_FIELD_LABELS = {
    "title": "タイトル",
    "content": "プロンプト内容",
    "prompt_content": "プロンプト内容",
    "category": "カテゴリ",
    "author": "投稿者名",
    "prompt_type": "投稿タイプ",
    "input_examples": "入力例",
    "output_examples": "出力例",
    "ai_model": "使用AIモデル",
}
PROMPT_ASSIST_DEFAULT_SUMMARY = "AIが入力内容をもとに下書きを提案しました。"


def _normalize_field_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_fields(target: str, fields: dict[str, Any]) -> dict[str, str]:
    target_config = PROMPT_ASSIST_TARGETS[target]
    normalized = {key: _normalize_field_value(fields.get(key, "")) for key in target_config["context_fields"]}
    normalized["prompt_type"] = "image" if normalized.get("prompt_type") == "image" else "text"
    return normalized


def _validate_prompt_assist_request(target: str, action: str, fields: dict[str, str]) -> None:
    target_config = PROMPT_ASSIST_TARGETS[target]
    primary_field = target_config["primary_field"]
    primary_value = fields.get(primary_field, "")

    if action in {"improve", "shorten", "expand"} and not primary_value:
        raise ValueError("本文を入力してからAI補助を実行してください。")

    if action == "generate_examples" and not primary_value:
        raise ValueError("入出力例を作るには本文を入力してください。")


def _build_prompt_assist_messages(target: str, action: str, fields: dict[str, str]) -> list[dict[str, str]]:
    target_config = PROMPT_ASSIST_TARGETS[target]
    allowed_fields = list(target_config["allowed_fields"])
    target_label = target_config["target_label"]
    current_payload = {key: fields.get(key, "") for key in target_config["context_fields"]}
    allowed_field_labels = {key: PROMPT_ASSIST_FIELD_LABELS[key] for key in allowed_fields}

    system_message = (
        "あなたは日本語のプロンプト作成支援アシスタントです。"
        "ユーザーの意図を保ちながら、Webアプリの投稿フォーム向けにわかりやすく実用的な文章へ整えてください。"
        "必ずJSONオブジェクトのみを返し、Markdownやコードフェンスは使わないでください。"
    )
    user_message = (
        f"対象UI: {target_label}\n"
        f"依頼内容: {PROMPT_ASSIST_ACTION_LABELS[action]}\n"
        f"更新候補として返してよいフィールド: {json.dumps(allowed_field_labels, ensure_ascii=False)}\n"
        "現在の入力値:\n"
        f"{json.dumps(current_payload, ensure_ascii=False)}\n\n"
        "次のJSON形式だけを返してください。\n"
        '{'
        '"summary":"1文の要約",'
        '"warnings":["必要なら短い注意点"],'
        '"suggested_fields":{"field_name":"提案文"}}\n'
        "ルール:\n"
        "1. suggested_fields には更新提案があるフィールドだけを含める。\n"
        "2. title は簡潔で具体的にする。\n"
        "3. 本文は日本語で、すぐ使える完成度を目指す。\n"
        "4. generate_examples の場合は input_examples と output_examples を優先して埋める。\n"
        "5. shared_prompt_modal では category, author, prompt_type, ai_model は文脈としてのみ使い、suggested_fields に含めない。\n"
        "6. task_modal では prompt_content を本文キーとして扱う。\n"
        "7. 不足情報があっても、警告を出しつつ最大限補完する。\n"
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _extract_json_text(raw_response: str) -> str:
    stripped = raw_response.strip()
    if not stripped:
        raise LlmProviderError("AI assist response was empty.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        return fenced_match.group(1)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]

    raise LlmProviderError("AI assist response did not contain JSON.")


def _parse_prompt_assist_response(raw_response: str) -> dict[str, Any]:
    json_text = _extract_json_text(raw_response)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise LlmProviderError("AI assist response was invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise LlmProviderError("AI assist response was not an object.")

    return parsed


def _normalize_prompt_assist_response(
    target: str,
    parsed_response: dict[str, Any],
    current_fields: dict[str, str],
) -> dict[str, Any]:
    target_config = PROMPT_ASSIST_TARGETS[target]
    allowed_fields = target_config["allowed_fields"]

    raw_suggested_fields = parsed_response.get("suggested_fields", {})
    suggested_fields: dict[str, str] = {}
    suggestion_modes: dict[str, str] = {}
    if isinstance(raw_suggested_fields, dict):
        for field_name in allowed_fields:
            value = raw_suggested_fields.get(field_name)
            normalized_value = _normalize_field_value(value)
            if normalized_value:
                if normalized_value == current_fields.get(field_name, ""):
                    continue
                suggested_fields[field_name] = normalized_value
                suggestion_modes[field_name] = (
                    "create" if not current_fields.get(field_name, "") else "refine"
                )

    if not suggested_fields:
        raise LlmProviderError("AI assist response did not contain usable suggestions.")

    raw_warnings = parsed_response.get("warnings", [])
    warnings: list[str] = []
    if isinstance(raw_warnings, list):
        for item in raw_warnings[:3]:
            normalized_item = _normalize_field_value(item)
            if normalized_item:
                warnings.append(normalized_item)

    summary = _normalize_field_value(parsed_response.get("summary")) or PROMPT_ASSIST_DEFAULT_SUMMARY

    return {
        "summary": summary,
        "warnings": warnings,
        "suggested_fields": suggested_fields,
        "suggestion_modes": suggestion_modes,
        "model": PROMPT_ASSIST_MODEL,
    }


def create_prompt_assist_payload(
    target: str,
    action: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if target not in PROMPT_ASSIST_TARGETS:
        raise ValueError("サポートされていないAI補助対象です。")
    if action not in PROMPT_ASSIST_ACTION_LABELS:
        raise ValueError("サポートされていないAI補助アクションです。")

    normalized_fields = _normalize_fields(target, fields)
    _validate_prompt_assist_request(target, action, normalized_fields)
    messages = _build_prompt_assist_messages(target, action, normalized_fields)
    raw_response = get_llm_response(messages, PROMPT_ASSIST_MODEL)
    return _normalize_prompt_assist_response(
        target,
        _parse_prompt_assist_response(raw_response or ""),
        normalized_fields,
    )
