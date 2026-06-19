import {
  CONTENT_FORMATS,
  MEDIA_TYPES
} from "../../scripts/prompt_share/prompt_type_registry";
import type {
  ContentFormatFilter,
  MediaTypeFilter,
  PromptAxisFilterOption,
  PromptCategory
} from "./prompt_share_page_types";

// 1ページあたりの検索結果件数。APIリクエストのlimitパラメータと合わせる必要がある
// Items per search results page; must match the limit parameter used in API requests
export const SEARCH_RESULTS_PER_PAGE = 20;

// カテゴリフィルターの定義。value="all"は全件表示のための特別値
// Category filter definitions; "all" is a sentinel value that shows every prompt
export const PROMPT_CATEGORIES: PromptCategory[] = [
  { value: "all", iconClass: "bi bi-grid", label: "全て" },
  { value: "恋愛", iconClass: "bi bi-heart-fill", label: "恋愛" },
  { value: "勉強", iconClass: "bi bi-book", label: "勉強" },
  { value: "趣味", iconClass: "bi bi-camera", label: "趣味" },
  { value: "仕事", iconClass: "bi bi-briefcase", label: "仕事" },
  { value: "その他", iconClass: "bi bi-stars", label: "その他" },
  { value: "スポーツ", iconClass: "bi bi-trophy", label: "スポーツ" },
  { value: "音楽", iconClass: "bi bi-music-note", label: "音楽" },
  { value: "旅行", iconClass: "bi bi-geo-alt", label: "旅行" },
  { value: "グルメ", iconClass: "bi bi-shop", label: "グルメ" }
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

// 投稿フォームのカテゴリセレクトに使う選択肢。"未選択"は投稿時のバリデーション用初期値
// Category options for the composer form; "未選択" is the initial value checked during validation
export const PROMPT_CATEGORY_OPTIONS = [
  "未選択",
  "恋愛",
  "勉強",
  "趣味",
  "仕事",
  "その他",
  "スポーツ",
  "音楽",
  "旅行",
  "グルメ"
];
