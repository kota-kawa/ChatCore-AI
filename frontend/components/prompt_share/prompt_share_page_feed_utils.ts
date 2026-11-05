// プロンプト共有フィードの一覧データを扱う純粋関数（PromptRecord への変換、重複排除つきの連結、絞り込み、件数表示の組み立て）。
// Pure functions for the prompt sharing feed data: converting to PromptRecord, appending pages without duplicates, filtering, and building count text.
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
import { promptShareText } from "../../scripts/prompt_share/i18n";

// SSR/API由来のPromptDataをReact側で扱うPromptRecordに揃える
// Converts SSR/API PromptData into PromptRecords used by the React UI
export function buildInitialPromptRecords(items: PromptData[]) {
  return items.map((item, index) => ({
    ...normalizePromptData(item),
    clientId: `prompt-initial-${String(item.id ?? index)}`,
    liked: Boolean(item.liked),
    used_in_chat: Boolean(item.used_in_chat),
    added_to_skills: Boolean(item.added_to_skills)
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

// フォーマットフィルターの表示名を返す（all は「すべて」）。
// Returns the display label of a format filter ("all" maps to the generic label).
export function getContentFormatFilterLabel(contentFormatFilter: ContentFormatFilter) {
  return contentFormatFilter === "all" ? promptShareText("promptShare.all") : getPromptFormatLabel(contentFormatFilter);
}

// メディアフィルターの表示名を返す（all は「すべて」）。
// Returns the display label of a media filter ("all" maps to the generic label).
export function getMediaTypeFilterLabel(mediaTypeFilter: MediaTypeFilter) {
  return mediaTypeFilter === "all" ? promptShareText("promptShare.all") : getPromptMediaLabel(mediaTypeFilter);
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

// 絞り込み後に表示される件数を数える。
// Counts the prompts that remain visible after filtering.
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
    return promptShareText("promptShare.resultsCount", { filters: filterSuffix, visible: visibleCount, total: options.searchTotal });
  }

  const loadedSuffix = options?.hasMore ? promptShareText("promptShare.loadedCount", { count: visibleCount }) : promptShareText("promptShare.itemsCount", { count: visibleCount });
  return `${getCategoryCountLabel(category || "all")}${filterSuffix}: ${loadedSuffix}`;
}

// 絞り込みの結果が0件のときのメッセージ。フォーマット・メディアの条件があれば、その名前を含める。
// Message for an empty filtered result; it names the format/media conditions when any are set.
export function getFilterEmptyMessage(
  contentFormatFilter: ContentFormatFilter,
  mediaTypeFilter: MediaTypeFilter
) {
  if (contentFormatFilter === "all" && mediaTypeFilter === "all") {
    return promptShareText("promptShare.noMatches");
  }
  const labels = [
    contentFormatFilter === "all" ? "" : getContentFormatFilterLabel(contentFormatFilter),
    mediaTypeFilter === "all" ? "" : getMediaTypeFilterLabel(mediaTypeFilter)
  ].filter(Boolean);
  return promptShareText("promptShare.noMatchesFor", { filters: labels.join(" / ") });
}
