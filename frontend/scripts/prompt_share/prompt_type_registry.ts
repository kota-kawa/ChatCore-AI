// frontend/scripts/prompt_share/prompt_type_registry.ts
// 共有プロンプトの「2軸」モデルのフロント側レジストリ (services/prompt_types.py のミラー)。
// Frontend registry for the prompt "two-axis" model. Mirror of services/prompt_types.py.
//
// 2軸:
//   - フォーマット軸 (content_format): 投稿の構造。prompt / skill / 将来の agent 等。
//   - メディア軸 (media_type): 生成対象。text / image / 将来の video, audio 等。
// 新しいフォーマット/メディアの追加は、原則このファイルへ1エントリ足すだけで済む。
// Adding a new format or media type should only require one entry here.

import type { ContentFormat, MediaType, PromptType } from "./types";

// 型固有テキスト属性の最大文字数 (バックエンドの MAX_PROMPT_ATTRIBUTE_TEXT_LENGTH と一致)。
// Max length for a type-specific text attribute (matches the backend constant).
export const PROMPT_ATTRIBUTE_MAX_LENGTH = 30000;

export const SKILL_MARKDOWN_KEY = "skill_markdown";
export const SKILL_PYTHON_SCRIPT_KEY = "skill_python_script";

// レジストリが描画を駆動する、フォーマット固有フィールドの宣言。
// Declaration of a format-specific field that the registry uses to drive rendering.
export type AttributeFieldDescriptor = {
  key: string;
  label: string;
  hint?: string;
  input: "textarea" | "text";
  rows?: number;
  required?: boolean;
  maxLength?: number;
  placeholder?: string;
};

// あるメディアが許可する添付ファイルの制約。
// Constraints for the attachment a media type accepts.
export type AttachmentRule = {
  acceptedMime: string[];
  acceptedExt: string[];
  maxBytes: number;
  role: string;
  // <input accept> 属性に渡す文字列。
  // Value for the <input accept> attribute.
  accept: string;
};

// フォーマット軸の1エントリ。
// One entry on the content format axis.
export type ContentFormatDescriptor = {
  key: ContentFormat;
  label: string;
  // 排他選択UI用の短い補足 (文字は最小限に)。
  // Short supporting copy for the selector (kept minimal by design).
  tagline: string;
  icon: string;
  fields: AttributeFieldDescriptor[];
  // 本文 (content) を必須とするか。
  requiresContent: boolean;
  // 利用例セクションを隠すか。
  hidesExamples: boolean;
};

// メディア軸の1エントリ。
// One entry on the media type axis.
export type MediaTypeDescriptor = {
  key: MediaType;
  label: string;
  icon: string;
  attachmentRule?: AttachmentRule;
};

const IMAGE_ATTACHMENT_RULE: AttachmentRule = {
  acceptedMime: ["image/png", "image/jpeg", "image/webp", "image/gif"],
  acceptedExt: [".png", ".jpg", ".jpeg", ".webp", ".gif"],
  maxBytes: 5 * 1024 * 1024,
  role: "reference",
  accept: "image/png,image/jpeg,image/webp,image/gif"
};

// --- フォーマット軸レジストリ ---------------------------------------------
export const CONTENT_FORMATS: ContentFormatDescriptor[] = [
  {
    key: "prompt",
    label: "プロンプト",
    tagline: "指示文を共有",
    icon: "bi-chat-square-text",
    fields: [],
    requiresContent: true,
    hidesExamples: false
  },
  {
    key: "skill",
    label: "SKILL",
    tagline: "手順パッケージを共有",
    icon: "bi-code-slash",
    fields: [
      {
        key: SKILL_MARKDOWN_KEY,
        label: "SKILL定義（Markdown）",
        hint: "使い方・ルール・入出力例を Markdown で記述。",
        input: "textarea",
        rows: 10,
        required: true,
        maxLength: PROMPT_ATTRIBUTE_MAX_LENGTH,
        placeholder: "# SKILL名\n\n## 目的\n- ...\n\n## 手順\n1. ..."
      },
      {
        key: SKILL_PYTHON_SCRIPT_KEY,
        label: "追加 Python スクリプト（任意）",
        hint: "必要なら補助スクリプトを貼り付け。",
        input: "textarea",
        rows: 8,
        required: false,
        maxLength: PROMPT_ATTRIBUTE_MAX_LENGTH,
        placeholder: "def run(input_text: str) -> str:\n    return input_text"
      }
    ],
    requiresContent: false,
    hidesExamples: true
  }
];

// --- メディア軸レジストリ -------------------------------------------------
export const MEDIA_TYPES: MediaTypeDescriptor[] = [
  { key: "text", label: "テキスト", icon: "bi-fonts" },
  { key: "image", label: "画像", icon: "bi-image", attachmentRule: IMAGE_ATTACHMENT_RULE }
];

const CONTENT_FORMAT_MAP = new Map(CONTENT_FORMATS.map((f) => [f.key, f]));
const MEDIA_TYPE_MAP = new Map(MEDIA_TYPES.map((m) => [m.key, m]));

export const DEFAULT_CONTENT_FORMAT: ContentFormat = "prompt";
export const DEFAULT_MEDIA_TYPE: MediaType = "text";

// 全フォーマットの属性フィールドを重複なく列挙する (モーダルが常時DOMにマウントするため)。
// All attribute fields across formats, de-duplicated by key (the modal keeps them mounted).
export const ALL_ATTRIBUTE_FIELDS: AttributeFieldDescriptor[] = (() => {
  const seen = new Set<string>();
  const fields: AttributeFieldDescriptor[] = [];
  for (const format of CONTENT_FORMATS) {
    for (const field of format.fields) {
      if (seen.has(field.key)) continue;
      seen.add(field.key);
      fields.push(field);
    }
  }
  return fields;
})();

export function normalizeContentFormat(value?: string): ContentFormat {
  if (value && CONTENT_FORMAT_MAP.has(value as ContentFormat)) {
    return value as ContentFormat;
  }
  // 旧 prompt_type からの吸収。
  // Resolve legacy prompt_type values.
  if (value === "skill") return "skill";
  return DEFAULT_CONTENT_FORMAT;
}

export function normalizeMediaType(value?: string): MediaType {
  if (value && MEDIA_TYPE_MAP.has(value as MediaType)) {
    return value as MediaType;
  }
  if (value === "image") return "image";
  return DEFAULT_MEDIA_TYPE;
}

export function getContentFormat(key: string): ContentFormatDescriptor {
  return CONTENT_FORMAT_MAP.get(normalizeContentFormat(key))!;
}

export function getMediaType(key: string): MediaTypeDescriptor {
  return MEDIA_TYPE_MAP.get(normalizeMediaType(key))!;
}

export function getAttributeFields(contentFormat: string): AttributeFieldDescriptor[] {
  return getContentFormat(contentFormat).fields;
}

export function getAttachmentRule(mediaType: string): AttachmentRule | undefined {
  return getMediaType(mediaType).attachmentRule;
}

export function mediaAllowsAttachment(mediaType: string): boolean {
  return Boolean(getAttachmentRule(mediaType));
}

// 2軸から旧 prompt_type 互換値を算出する (フィード絞り込み・カード表示・AI補助の文脈用)。
// Derive the legacy prompt_type from the two axes (for feed filter, cards, AI-assist context).
export function deriveLegacyPromptType(contentFormat: string, mediaType: string): PromptType {
  if (normalizeContentFormat(contentFormat) === "skill") return "skill";
  if (normalizeMediaType(mediaType) === "image") return "image";
  return "text";
}

// 旧 prompt_type を2軸へ変換する。
// Map a legacy prompt_type to the two axes.
export function legacyPromptTypeToAxes(promptType?: string): {
  contentFormat: ContentFormat;
  mediaType: MediaType;
} {
  if (promptType === "skill") return { contentFormat: "skill", mediaType: "text" };
  if (promptType === "image") return { contentFormat: "prompt", mediaType: "image" };
  return { contentFormat: "prompt", mediaType: "text" };
}

// フォーマットが宣言するキーのみを残して attributes を組み立てる。
// Build the attributes map keeping only the keys the format declares.
export function buildAttributes(
  contentFormat: string,
  source: Record<string, string>
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const field of getAttributeFields(contentFormat)) {
    result[field.key] = source[field.key] ?? "";
  }
  return result;
}

// 添付ファイルをメディアの添付ルールで検証する (問題なければ null)。
// Validate a file against the media's attachment rule (null when valid).
export function validateAttachmentFile(mediaType: string, file: File | null): string | null {
  if (!file) return null;
  const rule = getAttachmentRule(mediaType);
  if (!rule) return "このメディアタイプではファイルを添付できません。";
  const lowerName = file.name.toLowerCase();
  const extOk = rule.acceptedExt.some((ext) => lowerName.endsWith(ext));
  if (!rule.acceptedMime.includes(file.type) && !extOk) {
    const allowed = Array.from(new Set(rule.acceptedExt.map((e) => e.replace(".", "").toUpperCase()))).join(" / ");
    return `添付は ${allowed} のいずれかを指定してください。`;
  }
  if (file.size > rule.maxBytes) {
    const maxMb = Math.round(rule.maxBytes / (1024 * 1024));
    return `添付ファイルのサイズは${maxMb}MB以下にしてください。`;
  }
  return null;
}
