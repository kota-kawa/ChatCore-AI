import type { ContentFormat, MediaType, PromptData, PromptType } from "./types";
import { CONTENT_CHAR_LIMIT } from "./constants";
import { escapeHtml } from "../core/html";
import { formatDate } from "../../lib/datetime";
import {
  getContentFormat,
  getMediaType,
  normalizeContentFormat,
  normalizeMediaType
} from "./prompt_type_registry";
import { normalizeSkillResources } from "./skill_resources";
import type { Locale } from "../../lib/i18n/config";
import { promptShareText } from "./i18n";

export function truncateText(text: string, limit: number) {
  const safeText = text || "";
  const chars = Array.from(safeText);
  return chars.length > limit ? chars.slice(0, limit).join("") + "..." : safeText;
}

export function truncateContent(content: string) {
  return truncateText(content, CONTENT_CHAR_LIMIT);
}

// 説明がある投稿は説明をカード用のプレビューに優先し、未設定の既存投稿は本文へ戻す。
// Prefer the optional description for cards and keep legacy posts on their body preview.
export function getPromptPreviewSource(
  description: string | undefined,
  contentFormat: string | undefined,
  content: string | undefined,
  skillMarkdown: string | undefined
) {
  if (description?.trim()) {
    return description;
  }
  return normalizeContentFormat(contentFormat) === "skill"
    ? skillMarkdown || ""
    : content || "";
}

export function formatPromptDate(createdAt?: string) {
  return formatDate(createdAt);
}

export { escapeHtml };

export function normalizePromptType(value?: string): PromptType {
  if (value === "image" || value === "skill") {
    return value;
  }
  return "text";
}

export function getPromptTypeLabel(promptType: PromptType, locale?: Locale) {
  if (promptType === "image") return promptShareText("promptShare.mediaImage", undefined, locale);
  if (promptType === "skill") return "SKILL";
  return promptShareText("promptShare.formatPrompt", undefined, locale);
}

export function getPromptTypeIconClass(promptType: PromptType) {
  if (promptType === "image") return "bi-image";
  if (promptType === "skill") return "bi-code-slash";
  return "bi-chat-square-text";
}

export function normalizePromptContentFormat(value?: string): ContentFormat {
  return normalizeContentFormat(value);
}

export function normalizePromptMediaType(value?: string): MediaType {
  return normalizeMediaType(value);
}

export function getPromptFormatLabel(contentFormat?: string, locale?: Locale) {
  return normalizeContentFormat(contentFormat) === "skill" ? "SKILL" : promptShareText("promptShare.formatPrompt", undefined, locale);
}

export function getPromptFormatIconClass(contentFormat?: string) {
  return getContentFormat(contentFormat || "").icon;
}

export function getPromptMediaLabel(mediaType?: string, locale?: Locale) {
  return normalizeMediaType(mediaType) === "image" ? promptShareText("promptShare.mediaImage", undefined, locale) : promptShareText("promptShare.mediaText", undefined, locale);
}

export function getPromptMediaIconClass(mediaType?: string) {
  return getMediaType(mediaType || "").icon;
}

// APIが返す明示的な参照画像URLを優先し、移行中のレスポンスではreference添付から補完する。
// Prefer the API's explicit reference image URL and fall back to a reference attachment
// for responses produced during the attachments migration.
function resolveReferenceImageUrl(prompt: PromptData): string {
  const explicitUrl = String(prompt.reference_image_url || "").trim();
  const referenceAttachment = Array.isArray(prompt.attachments)
    ? prompt.attachments.find(
        (attachment) => attachment.role === "reference" && String(attachment.url || "").trim()
      )
    : undefined;
  const attachmentUrl = String(referenceAttachment?.url || "").trim();
  const url = explicitUrl || attachmentUrl;

  if (!url || url.startsWith("/") || /^[a-z][a-z\d+.-]*:/i.test(url)) {
    return url;
  }
  return `/${url}`;
}

export function normalizePromptData(prompt: PromptData): PromptData {
  const contentFormat = normalizePromptContentFormat(String(prompt.content_format || ""));
  const mediaType = normalizePromptMediaType(String(prompt.media_type || ""));
  return {
    ...prompt,
    content_format: contentFormat,
    media_type: mediaType,
    description: prompt.description || "",
    attributes: prompt.attributes || {},
    attachments: Array.isArray(prompt.attachments) ? prompt.attachments : [],
    resources: normalizeSkillResources(prompt.resources, prompt.skill_python_script || ""),
    prompt_type: normalizePromptType(prompt.prompt_type),
    reference_image_url: resolveReferenceImageUrl(prompt),
    skill_markdown: prompt.skill_markdown || "",
    skill_python_script: prompt.skill_python_script || "",
    liked: Boolean(prompt.liked),
    used_in_chat: Boolean(prompt.used_in_chat),
    comment_count: Number(prompt.comment_count || 0)
  };
}
