import { absoluteUrl } from "../seo";

// ---------------------------------------------------------------------------
// Memo page constants
// ---------------------------------------------------------------------------

export const DEFAULT_LIMIT = 50;
export const MEMO_ACTION_MENU_WIDTH = 168;
export const MEMO_ACTION_MENU_ESTIMATED_HEIGHT = 172;
export const MEMO_ACTION_MENU_GAP = 6;
export const MEMO_ACTION_MENU_VIEWPORT_MARGIN = 8;
export const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
export const MEMO_SHARE_TEXT = "このメモを共有しました。";
export const memoPageDescription =
  "Chat CoreでAIとのやり取りや作業メモを保存し、検索・整理・共有できるノート画面です。";
export const memoStructuredData = {
  "@context": "https://schema.org",
  "@type": "WebPage",
  name: "Chat Core メモ",
  url: absoluteUrl("/memo"),
  description: memoPageDescription,
  inLanguage: "ja",
  isPartOf: {
    "@type": "WebSite",
    name: "Chat Core",
    url: absoluteUrl("/")
  }
};
export const DETAIL_AUTOSAVE_DELAY_MS = 900;
export const MEMO_DETAIL_CLOSE_ANIMATION_MS = 240;
export const EXPORT_FORMATS = [
  { value: "markdown", label: "Markdown (.md)", icon: "bi-markdown" },
  { value: "json", label: "JSON (.json)", icon: "bi-filetype-json" },
  { value: "csv", label: "CSV (.csv)", icon: "bi-filetype-csv" },
] as const;
export const MEMO_COLOR_OPTIONS = [
  { value: "", label: "標準", color: "#ffffff" },
  { value: "#fff8b8", label: "レモン", color: "#fff8b8" },
  { value: "#fce8e6", label: "コーラル", color: "#fce8e6" },
  { value: "#fef3c7", label: "アンバー", color: "#fef3c7" },
  { value: "#dcfce7", label: "ミント", color: "#dcfce7" },
  { value: "#dbeafe", label: "ブルー", color: "#dbeafe" },
  { value: "#ede9fe", label: "ラベンダー", color: "#ede9fe" },
  { value: "#fce7f3", label: "ローズ", color: "#fce7f3" },
] as const;
export const MEMO_AGENT_QUICK_PROMPTS = [
  "このメモを要約して",
  "重要なポイントを箇条書きにして",
  "このメモについて質問に答えて"
];
