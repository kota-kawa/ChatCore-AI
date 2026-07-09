import {
  CATEGORY_UNSET,
  PROMPT_CATEGORY_REGISTRY
} from "../../scripts/prompt_share/prompt_category_registry";
import {
  CONTENT_FORMATS,
  MEDIA_TYPES
} from "../../scripts/prompt_share/prompt_type_registry";
import type {
  ContentFormatFilter,
  MediaTypeFilter,
  PromptAxisFilterOption,
  PromptCategory,
  PromptCategoryOption
} from "./prompt_share_page_types";

// 1ページあたりの検索結果件数。APIリクエストのlimitパラメータと合わせる必要がある
// Items per search results page; must match the limit parameter used in API requests
export const SEARCH_RESULTS_PER_PAGE = 20;

// カテゴリフィルターの定義。value="all"は全件表示のための特別値。
// カテゴリの追加はレジストリへの1エントリ追加で吸収する。
// Category filter definitions; "all" is a sentinel that shows every prompt.
// New categories are picked up from the registry.
export const PROMPT_CATEGORIES: PromptCategory[] = [
  { value: "all", iconClass: "bi bi-grid", label: "全て" },
  ...PROMPT_CATEGORY_REGISTRY.map((category) => ({
    value: category.key,
    iconClass: `bi ${category.icon}`,
    label: category.label
  }))
];

// フォーマット軸による絞り込みフィルター。カテゴリ・メディアとは独立して組み合わせ可能
// Content format filter options; can be combined with category and media filters independently
export const PROMPT_CONTENT_FORMAT_FILTERS: PromptAxisFilterOption<ContentFormatFilter>[] = [
  { value: "all", iconClass: "bi bi-layers", label: "全て" },
  ...CONTENT_FORMATS.map((format) => ({
    value: format.key,
    iconClass: `bi ${format.icon}`,
    label: format.label
  }))
];

// 生成メディア軸による絞り込みフィルター。画像・動画などの拡張はレジストリ追加で吸収する
// Media type filter options; future media types are picked up from the registry
export const PROMPT_MEDIA_TYPE_FILTERS: PromptAxisFilterOption<MediaTypeFilter>[] = [
  { value: "all", iconClass: "bi bi-grid", label: "全て" },
  ...MEDIA_TYPES.map((media) => ({
    value: media.key,
    iconClass: `bi ${media.icon}`,
    label: media.label
  }))
];

// 投稿フォームのカテゴリセレクトに使う選択肢。value は保存用の安定キー、label は表示名。
// 未選択は空文字列キーで表し、投稿時のバリデーションで弾く。
// Category options for the composer form; value is the stable key persisted to the DB and
// label is what the user sees. The unset state is the empty key, rejected at submit time.
export const PROMPT_CATEGORY_OPTIONS: PromptCategoryOption[] = [
  { value: CATEGORY_UNSET, label: "未選択" },
  ...PROMPT_CATEGORY_REGISTRY.map((category) => ({
    value: category.key,
    label: category.label
  }))
];
