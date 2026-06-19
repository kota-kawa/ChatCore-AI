import type { PromptData, PromptType } from "./types";
import { CONTENT_CHAR_LIMIT, TITLE_CHAR_LIMIT } from "./constants";
import { escapeHtml } from "../core/html";
import { formatDate } from "../../lib/datetime";

export function truncateText(text: string, limit: number) {
  const safeText = text || "";
  const chars = Array.from(safeText);
  return chars.length > limit ? chars.slice(0, limit).join("") + "..." : safeText;
}

export function truncateTitle(title: string) {
  return truncateText(title, TITLE_CHAR_LIMIT);
}

export function truncateContent(content: string) {
  return truncateText(content, CONTENT_CHAR_LIMIT);
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

export function getPromptTypeLabel(promptType: PromptType) {
  if (promptType === "image") return "画像生成";
  if (promptType === "skill") return "SKILL";
  return "通常";
}

export function getPromptTypeIconClass(promptType: PromptType) {
  if (promptType === "image") return "bi-image";
  if (promptType === "skill") return "bi-code-slash";
  return "bi-chat-square-text";
}

export function normalizePromptData(prompt: PromptData): PromptData {
  return {
    ...prompt,
    content_format: prompt.content_format || "prompt",
    media_type: prompt.media_type || "text",
    attributes: prompt.attributes || {},
    attachments: Array.isArray(prompt.attachments) ? prompt.attachments : [],
    prompt_type: normalizePromptType(prompt.prompt_type),
    reference_image_url: prompt.reference_image_url || "",
    skill_markdown: prompt.skill_markdown || "",
    skill_python_script: prompt.skill_python_script || "",
    liked: Boolean(prompt.liked),
    used_in_chat: Boolean(prompt.used_in_chat),
    comment_count: Number(prompt.comment_count || 0)
  };
}
