# services/prompt_types.py
"""共有プロンプトの「2軸」モデルを定義する単一の真実の源。

[JP] 投稿は2つの直交した軸を持つ:
  - フォーマット軸 (content_format): 投稿の構造。prompt / skill / 将来の agent, workflow 等。
  - メディア軸 (media_type): 生成対象。text / image / 将来の video, audio, music 等。
型固有の構造化データは attributes (dict) に、メディア添付は attachments (list) に格納する。
新しいフォーマット/メディアの追加は、原則このモジュールへ1エントリ足すだけで済む
(DBスキーマ変更不要)。バリデーション・保存・シリアライズはすべてここを参照する。

[EN] Single source of truth for the prompt "two-axis" model. Adding a new format or
media type should only require one entry here (no DB migration). Backend validation,
persistence, and serialization all consult this registry. Mirror in
frontend/scripts/prompt_share/prompt_type_registry.ts.
"""

from __future__ import annotations

from dataclasses import dataclass

# 型固有テキスト属性 (skill_markdown 等) の最大文字数
# Maximum length for a type-specific text attribute (e.g. skill_markdown).
MAX_PROMPT_ATTRIBUTE_TEXT_LENGTH = 30000

# フォーマット軸キー
# Content format axis keys.
CONTENT_FORMAT_PROMPT = "prompt"
CONTENT_FORMAT_SKILL = "skill"

# メディア軸キー
# Media axis keys.
MEDIA_TYPE_TEXT = "text"
MEDIA_TYPE_IMAGE = "image"

# 既定値
# Defaults.
DEFAULT_CONTENT_FORMAT = CONTENT_FORMAT_PROMPT
DEFAULT_MEDIA_TYPE = MEDIA_TYPE_TEXT

# skill フォーマットの属性キー
# Attribute keys used by the skill format.
SKILL_MARKDOWN_KEY = "skill_markdown"
SKILL_PYTHON_SCRIPT_KEY = "skill_python_script"

# 添付ロール
# Attachment role values.
ATTACHMENT_ROLE_REFERENCE = "reference"


@dataclass(frozen=True)
class AttributeField:
    """フォーマット固有の構造化フィールド定義。"""

    key: str
    label: str
    required: bool = False
    max_length: int = MAX_PROMPT_ATTRIBUTE_TEXT_LENGTH


@dataclass(frozen=True)
class AttachmentRule:
    """あるメディアが許可する添付ファイルの制約。"""

    accepted_mime: frozenset[str]
    accepted_ext: tuple[str, ...]
    max_bytes: int
    role: str = ATTACHMENT_ROLE_REFERENCE


@dataclass(frozen=True)
class ContentFormat:
    """フォーマット軸の1エントリ。"""

    key: str
    label: str
    attribute_fields: tuple[AttributeField, ...] = ()
    # 本文 (content) を必須にするか。skill は専用属性を使うため不要。
    requires_content: bool = True
    # 利用例セクションを隠すか。
    hides_examples: bool = False


@dataclass(frozen=True)
class MediaType:
    """メディア軸の1エントリ。"""

    key: str
    label: str
    attachment_rule: AttachmentRule | None = None


# --- フォーマット軸レジストリ ---------------------------------------------
CONTENT_FORMATS: dict[str, ContentFormat] = {
    CONTENT_FORMAT_PROMPT: ContentFormat(
        key=CONTENT_FORMAT_PROMPT,
        label="プロンプト",
        requires_content=True,
        hides_examples=False,
    ),
    CONTENT_FORMAT_SKILL: ContentFormat(
        key=CONTENT_FORMAT_SKILL,
        label="SKILL",
        attribute_fields=(
            AttributeField(key=SKILL_MARKDOWN_KEY, label="SKILL定義（Markdown）", required=True),
            AttributeField(key=SKILL_PYTHON_SCRIPT_KEY, label="追加 Python スクリプト", required=False),
        ),
        requires_content=False,
        hides_examples=True,
    ),
}

# --- メディア軸レジストリ -------------------------------------------------
_IMAGE_ATTACHMENT_RULE = AttachmentRule(
    accepted_mime=frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"}),
    accepted_ext=(".png", ".jpg", ".jpeg", ".webp", ".gif"),
    max_bytes=5 * 1024 * 1024,
    role=ATTACHMENT_ROLE_REFERENCE,
)

MEDIA_TYPES: dict[str, MediaType] = {
    MEDIA_TYPE_TEXT: MediaType(key=MEDIA_TYPE_TEXT, label="テキスト"),
    MEDIA_TYPE_IMAGE: MediaType(
        key=MEDIA_TYPE_IMAGE,
        label="画像",
        attachment_rule=_IMAGE_ATTACHMENT_RULE,
    ),
}

# 旧 prompt_type からのエイリアス吸収用 (正規化に使用)
# Aliases for resolving a legacy/loosely-typed value to a canonical key.
_CONTENT_FORMAT_ALIASES: dict[str, str] = {
    "skill": CONTENT_FORMAT_SKILL,
    "skill_prompt": CONTENT_FORMAT_SKILL,
    "claude_skill": CONTENT_FORMAT_SKILL,
    "codex_skill": CONTENT_FORMAT_SKILL,
    "prompt": CONTENT_FORMAT_PROMPT,
    "text": CONTENT_FORMAT_PROMPT,
    "image": CONTENT_FORMAT_PROMPT,
}
_MEDIA_TYPE_ALIASES: dict[str, str] = {
    "image": MEDIA_TYPE_IMAGE,
    "image_prompt": MEDIA_TYPE_IMAGE,
    "image-generation": MEDIA_TYPE_IMAGE,
    "image_generation": MEDIA_TYPE_IMAGE,
    "text": MEDIA_TYPE_TEXT,
    "skill": MEDIA_TYPE_TEXT,
}

# 旧 prompt_type 値 -> (content_format, media_type)
# Legacy single-axis value -> two-axis mapping (used by serialization & migration).
_LEGACY_PROMPT_TYPE_MAP: dict[str, tuple[str, str]] = {
    "text": (CONTENT_FORMAT_PROMPT, MEDIA_TYPE_TEXT),
    "image": (CONTENT_FORMAT_PROMPT, MEDIA_TYPE_IMAGE),
    "skill": (CONTENT_FORMAT_SKILL, MEDIA_TYPE_TEXT),
}


def normalize_content_format(value: object) -> str:
    """フォーマット軸の値を正規化する。未知の値は既定値へフォールバック。"""
    normalized = str(value or "").strip().lower()
    if normalized in CONTENT_FORMATS:
        return normalized
    return _CONTENT_FORMAT_ALIASES.get(normalized, DEFAULT_CONTENT_FORMAT)


def normalize_media_type(value: object) -> str:
    """メディア軸の値を正規化する。未知の値は既定値へフォールバック。"""
    normalized = str(value or "").strip().lower()
    if normalized in MEDIA_TYPES:
        return normalized
    return _MEDIA_TYPE_ALIASES.get(normalized, DEFAULT_MEDIA_TYPE)


def legacy_prompt_type_to_axes(value: object) -> tuple[str, str]:
    """旧 prompt_type 文字列を (content_format, media_type) に変換する。"""
    normalized = str(value or "").strip().lower()
    if normalized in _LEGACY_PROMPT_TYPE_MAP:
        return _LEGACY_PROMPT_TYPE_MAP[normalized]
    return (normalize_content_format(value), normalize_media_type(value))


def derive_legacy_prompt_type(content_format: str, media_type: str) -> str:
    """(content_format, media_type) から旧 prompt_type 互換値を算出する。

    検索フィルタや既存表示との後方互換のための派生値であり、保存はしない。
    """
    fmt = normalize_content_format(content_format)
    media = normalize_media_type(media_type)
    if fmt == CONTENT_FORMAT_SKILL:
        return "skill"
    if media == MEDIA_TYPE_IMAGE:
        return "image"
    return "text"


def get_attachment_rule(media_type: object) -> AttachmentRule | None:
    """メディアに紐づく添付ルールを返す（添付不可なら None）。"""
    media = MEDIA_TYPES.get(normalize_media_type(media_type))
    return media.attachment_rule if media is not None else None


def media_allows_attachment(media_type: object) -> bool:
    """そのメディアがファイル添付を許可するか。"""
    return get_attachment_rule(media_type) is not None


def sanitize_attributes(content_format: object, attributes: object) -> dict[str, str]:
    """フォーマットが宣言する属性キーのみを残し、文字列化して返す。

    宣言されていないキーは破棄する（任意キーの混入防止）。
    """
    fmt = CONTENT_FORMATS.get(normalize_content_format(content_format))
    if fmt is None:
        return {}
    source = attributes if isinstance(attributes, dict) else {}
    cleaned: dict[str, str] = {}
    for spec in fmt.attribute_fields:
        raw = source.get(spec.key)
        cleaned[spec.key] = "" if raw is None else str(raw)
    return cleaned


def validate_attributes(content_format: object, attributes: dict[str, str]) -> list[str]:
    """属性の必須・最大長を検証し、エラーメッセージ一覧を返す（空なら妥当）。"""
    fmt = CONTENT_FORMATS.get(normalize_content_format(content_format))
    if fmt is None:
        return []
    errors: list[str] = []
    for spec in fmt.attribute_fields:
        value = attributes.get(spec.key, "") or ""
        if spec.required and not value.strip():
            errors.append(f"{fmt.label}投稿では {spec.key} が必須です。")
        if len(value) > spec.max_length:
            errors.append(f"{spec.key} は {spec.max_length} 文字以内で入力してください。")
    return errors


def requires_content(content_format: object) -> bool:
    """そのフォーマットが本文 content を必須とするか。"""
    fmt = CONTENT_FORMATS.get(normalize_content_format(content_format))
    return bool(fmt.requires_content) if fmt is not None else True


def reference_attachment_url(attachments: object) -> str | None:
    """attachments 配列から代表的な参照URL (role=reference) を取り出す。"""
    if not isinstance(attachments, list):
        return None
    for att in attachments:
        if isinstance(att, dict) and att.get("role") == ATTACHMENT_ROLE_REFERENCE and att.get("url"):
            return str(att["url"])
    return None


def serialize_axes(row: dict) -> dict[str, object]:
    """DB行(2軸)から API 出力用の軸関連フィールドを構築する。

    正準フィールド (content_format / media_type / attributes / attachments) に加え、
    後方互換の派生フィールド (prompt_type / reference_image_url / skill_markdown /
    skill_python_script) を返す。検索フィルタや既存の表示を壊さないための派生値であり、
    保存はしない。
    """
    content_format = normalize_content_format(row.get("content_format"))
    media_type = normalize_media_type(row.get("media_type"))
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    attachments = row.get("attachments")
    if not isinstance(attachments, list):
        attachments = []
    return {
        "content_format": content_format,
        "media_type": media_type,
        "attributes": attributes,
        "attachments": attachments,
        "prompt_type": derive_legacy_prompt_type(content_format, media_type),
        "reference_image_url": reference_attachment_url(attachments),
        "skill_markdown": str(attributes.get(SKILL_MARKDOWN_KEY, "") or ""),
        "skill_python_script": str(attributes.get(SKILL_PYTHON_SCRIPT_KEY, "") or ""),
    }
