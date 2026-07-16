import {
  getPromptFormatLabel,
  getPromptMediaLabel,
  normalizePromptContentFormat,
  normalizePromptData,
  normalizePromptMediaType
} from "../../scripts/prompt_share/formatters";
import type { PromptData } from "../../scripts/prompt_share/types";
import type { PromptRecord } from "./prompt_card";
import type {
  ContentFormatFilter,
  MediaTypeFilter
} from "./prompt_share_page_types";
import { getCategoryCountLabel } from "./prompt_share_page_utils";

// SSR/API由来のPromptDataをReact側で扱うPromptRecordに揃える
// Converts SSR/API PromptData into PromptRecords used by the React UI
export function buildInitialPromptRecords(items: PromptData[]) {
  return items.map((item, index) => ({
    ...normalizePromptData(item),
    clientId: `prompt-initial-${String(item.id ?? index)}`,
    liked: Boolean(item.liked),
    used_in_chat: Boolean(item.used_in_chat)
  }));
}

// キャッシュ保存用にclientIdを取り除く
// Removes the client-only clientId before writing prompt cache
export function toCachedPromptData(items: PromptRecord[]) {
  return items.map(({ clientId, ...prompt }) => prompt);
}

// 追加ページをIDで重複排除しながら現在の一覧へ連結する。
// Append another page while de-duplicating records by persisted prompt ID.
export function appendUniquePromptRecords(current: PromptRecord[], incoming: PromptRecord[]) {
  const knownIds = new Set(
    current.map((prompt) => String(prompt.id ?? prompt.clientId))
  );
  return [
    ...current,
    ...incoming.filter((prompt) => {
      const key = String(prompt.id ?? prompt.clientId);
      if (knownIds.has(key)) {
        return false;
      }
      knownIds.add(key);
      return true;
    })
  ];
}

export function getContentFormatFilterLabel(contentFormatFilter: ContentFormatFilter) {
  return contentFormatFilter === "all" ? "全て" : getPromptFormatLabel(contentFormatFilter);
}

export function getMediaTypeFilterLabel(mediaTypeFilter: MediaTypeFilter) {
  return mediaTypeFilter === "all" ? "全て" : getPromptMediaLabel(mediaTypeFilter);
}

// カテゴリ・フォーマット・メディアの条件でプロンプト一覧を絞り込む
// Filters prompts by category, content format, and media type
export function filterPrompts(
  items: PromptRecord[],
  category: string | null,
  contentFormatFilter: ContentFormatFilter,
  mediaTypeFilter: MediaTypeFilter
) {
  return items.filter((item) => {
    const categoryMatches = !category || category === "all" || (item.category || "") === category;
    const contentFormatMatches =
      contentFormatFilter === "all" ||
      normalizePromptContentFormat(String(item.content_format || "")) === contentFormatFilter;
    const mediaTypeMatches =
      mediaTypeFilter === "all" ||
      normalizePromptMediaType(String(item.media_type || "")) === mediaTypeFilter;
    return categoryMatches && contentFormatMatches && mediaTypeMatches;
  });
}

export function countVisiblePrompts(
  items: PromptRecord[],
  category: string | null,
  contentFormatFilter: ContentFormatFilter,
  mediaTypeFilter: MediaTypeFilter
) {
  return filterPrompts(items, category, contentFormatFilter, mediaTypeFilter).length;
}

// 現在のフィルタ・検索結果に応じてカウント表示文字列を構築する
// Builds the count display string based on current filters and search results
export function buildPromptCountMeta(
  items: PromptRecord[],
  category: string | null,
  contentFormatFilter: ContentFormatFilter,
  mediaTypeFilter: MediaTypeFilter,
  options?: { searchTotal?: number; hasMore?: boolean }
) {
  const visibleCount = countVisiblePrompts(items, category, contentFormatFilter, mediaTypeFilter);
  const formatSuffix =
    contentFormatFilter === "all" ? "" : ` / ${getContentFormatFilterLabel(contentFormatFilter)}`;
  const mediaSuffix =
    mediaTypeFilter === "all" ? "" : ` / ${getMediaTypeFilterLabel(mediaTypeFilter)}`;
  const filterSuffix = `${formatSuffix}${mediaSuffix}`;

  if (typeof options?.searchTotal === "number") {
    return `検索結果${filterSuffix}: ${visibleCount}件 / ${options.searchTotal}件`;
  }

  const loadedSuffix = options?.hasMore ? `${visibleCount}件を表示` : `${visibleCount}件`;
  return `${getCategoryCountLabel(category || "all")}${filterSuffix}: ${loadedSuffix}`;
}

export function getFilterEmptyMessage(
  contentFormatFilter: ContentFormatFilter,
  mediaTypeFilter: MediaTypeFilter
) {
  if (contentFormatFilter === "all" && mediaTypeFilter === "all") {
    return "条件に一致するプロンプトが見つかりませんでした。";
  }
  const labels = [
    contentFormatFilter === "all" ? "" : getContentFormatFilterLabel(contentFormatFilter),
    mediaTypeFilter === "all" ? "" : getMediaTypeFilterLabel(mediaTypeFilter)
  ].filter(Boolean);
  return `${labels.join(" / ")}のプロンプトが見つかりませんでした。`;
}
