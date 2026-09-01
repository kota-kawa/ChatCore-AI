# LLMプロバイダへ渡すツール（関数呼び出し）スキーマを、サーバー側検証で落ちない形へ整える。
# Prepare tool (function-calling) schemas so provider-side validation cannot fail them.
"""Relax tool schemas at the provider boundary.

Groq をはじめとする OpenAI 互換プロバイダは、モデルが生成したツール引数をサーバー側で
JSON Schema 検証し、違反をストリーム途中の再試行不可エラーとして返します。引数1つの
綴り違い（例: 検索言語に ISO の ``ja`` を返す。Brave の正しい値は ``jp``）だけで、
会話ターン全体が「内部エラー」で終わります。

そのため、プロバイダへ渡すスキーマからは「モデルが少し外れただけで致命傷になる制約」を
落とします。許可値と必須項目は説明文へ移すのでモデルへの誘導は失われません。値の検証と
正規化は、不正値を既定値へ丸めたりツール結果としてモデルへ差し戻したりできる
アプリ側のハンドラが担い、そこではターンを落とさずに回復できます。

落とす制約:

- ``enum`` / ``const``: 近い値（``ja`` / ``zh-TW`` / ``day``）を拒否される。
- ``required``: 引数の欠落を拒否される。
- ``additionalProperties: false``: モデルが独自の引数（``count`` など）を足すだけで拒否される。

``type`` と ``description`` は残します。モデルへの誘導はこの2つが担い、型の取り違えは
許可値の取り違えに比べて桁違いに起きにくいためです。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# JSON Schema の入れ子をたどるキー。値が「スキーマの辞書」か「スキーマ」か「スキーマの配列」かで分ける。
# Keys whose values nest further schemas: a mapping of schemas, a single schema, or a list of schemas.
_SCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions")
_SCHEMA_VALUE_KEYS = ("items", "additionalItems", "contains", "not", "additionalProperties")
_SCHEMA_LIST_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")

# プロバイダがモデルの逸脱を致命的な拒否へ変えるキーワード。
# Keywords that turn a small model deviation into a fatal provider-side rejection.
_REJECTING_KEYWORDS = ("enum", "const", "required")


def _format_allowed_values(values: Any) -> str:
    # 許可値を説明文へ書き出す。空文字も明示し、モデルが「省略」と混同しないようにする。
    # Render allowed values for the description, spelling out the empty string so the model
    # does not confuse it with omitting the field.
    if not isinstance(values, (list, tuple)):
        return ""
    rendered = [
        '""' if isinstance(value, str) and not value else str(value)
        for value in values
    ]
    return ", ".join(rendered)


def _append_sentence(description: Any, sentence: str) -> str:
    # 既存の説明文へ1文だけ足す。重複追記はしない。
    # Append a single sentence to an existing description, never duplicating it.
    existing = str(description or "").strip()
    if not sentence or sentence in existing:
        return existing
    if not existing:
        return sentence
    separator = " " if existing.endswith((".", "!", "?")) else ". "
    return f"{existing}{separator}{sentence}"


def _relax_schema(schema: Any) -> Any:
    # スキーマを再帰的にたどり、拒否につながる制約だけを説明文へ移す。
    # Walk the schema recursively and move only the rejection-causing constraints into descriptions.
    if isinstance(schema, list):
        return [_relax_schema(entry) for entry in schema]
    if not isinstance(schema, dict):
        return schema

    relaxed: dict[str, Any] = {
        key: value for key, value in schema.items() if key not in _REJECTING_KEYWORDS
    }

    allowed_values = schema.get("enum")
    if "const" in schema:
        allowed_values = [schema["const"]]
    rendered_values = _format_allowed_values(allowed_values)
    if rendered_values:
        relaxed["description"] = _append_sentence(
            relaxed.get("description"),
            f"Allowed values: {rendered_values}.",
        )

    required = schema.get("required")
    properties = relaxed.get("properties")
    if isinstance(required, list) and isinstance(properties, dict):
        # 必須項目はスキーマから外すが、どれが必須かは各引数の説明文へ残す。
        # 呼び出し元が渡した定義は書き換えず、常に新しい辞書へ差し替える。
        # Drop the required list from the schema, but keep which arguments are required in
        # each argument's own description. Never write back into the caller's definition:
        # always substitute fresh dictionaries.
        properties = dict(properties)
        relaxed["properties"] = properties
        for name in required:
            property_schema = properties.get(name)
            if isinstance(property_schema, dict):
                properties[name] = {
                    **property_schema,
                    "description": _append_sentence(
                        property_schema.get("description"),
                        "Required.",
                    ),
                }

    for key in _SCHEMA_MAP_KEYS:
        value = relaxed.get(key)
        if isinstance(value, dict):
            relaxed[key] = {name: _relax_schema(entry) for name, entry in value.items()}

    for key in _SCHEMA_LIST_KEYS:
        value = relaxed.get(key)
        if isinstance(value, list):
            relaxed[key] = [_relax_schema(entry) for entry in value]

    for key in _SCHEMA_VALUE_KEYS:
        if key not in relaxed:
            continue
        value = relaxed[key]
        if key == "additionalProperties" and value is False:
            # 未知の引数はプロバイダに拒否させず、こちら側で無視する。
            # Ignore unknown arguments here instead of letting the provider reject them.
            relaxed[key] = True
            continue
        relaxed[key] = _relax_schema(value)

    return relaxed


def relax_tool_parameters_schema(parameters: Any) -> Any:
    """Return a provider-safe copy of one tool's JSON Schema parameters."""
    return _relax_schema(deepcopy(parameters))


def prepare_provider_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return provider-safe copies of OpenAI-style tool definitions."""
    if not tools:
        return []

    prepared: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        provider_tool = deepcopy(tool)
        function = provider_tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
            function["parameters"] = _relax_schema(function["parameters"])
        prepared.append(provider_tool)
    return prepared
