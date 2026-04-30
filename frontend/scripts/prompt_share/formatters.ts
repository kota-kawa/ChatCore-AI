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

export function getBookmarkButtonMarkup(isBookmarked: boolean) {
  const iconClass = isBookmarked ? "bi-bookmark-check-fill" : "bi-bookmark";
  return `<i class="bi ${iconClass}"></i>`;
}

export function normalizePromptType(value?: string): PromptType {
  return value === "image" ? "image" : "text";
}

export function getPromptTypeLabel(promptType: PromptType) {
  return promptType === "image" ? "画像生成" : "通常";
}

export function getPromptTypeIconClass(promptType: PromptType) {
  return promptType === "image" ? "bi-image" : "bi-chat-square-text";
}

export function normalizePromptData(prompt: PromptData): PromptData {
  return {
    ...prompt,
    prompt_type: normalizePromptType(prompt.prompt_type),
    reference_image_url: prompt.reference_image_url || "",
    liked: Boolean(prompt.liked),
    bookmarked: Boolean(prompt.bookmarked),
    saved_to_list: Boolean(prompt.saved_to_list),
    comment_count: Number(prompt.comment_count || 0)
  };
}
