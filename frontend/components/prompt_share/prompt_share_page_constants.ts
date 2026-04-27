import type { PromptCategory } from "./prompt_share_page_types";

export const SEARCH_RESULTS_PER_PAGE = 20;

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
