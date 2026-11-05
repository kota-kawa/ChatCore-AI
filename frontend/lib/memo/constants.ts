// メモ画面で使う定数（一覧の取得件数、操作メニューの寸法、自動保存の間隔、書き出し形式、背景色の選択肢、SEO 用の構造化データ）。
// Constants used by the memo page: list page sizes, action menu dimensions, autosave delay, export formats, background color options, and SEO structured data.

import { absoluteUrl } from "../seo";

// ---------------------------------------------------------------------------
// メモ画面の定数
// Memo page constants
// ---------------------------------------------------------------------------

// 一覧を 1 回で取得する既定の件数。
// Default number of memos requested for the list.
export const DEFAULT_LIMIT = 50;
// バックエンド（services/repositories/memo_constants.py の MAX_MEMO_LIST_LIMIT）が 1 リクエストで返す上限。
// これを超える件数は offset をずらした複数リクエストに分割して取得する。
// Mirrors MAX_MEMO_LIST_LIMIT in services/repositories/memo_constants.py: the most rows one request can
// return. Anything beyond it is fetched as several offset-shifted requests.
export const MAX_MEMO_LIST_REQUEST_LIMIT = 100;
export const MEMO_ACTION_MENU_WIDTH = 168;
export const MEMO_ACTION_MENU_ESTIMATED_HEIGHT = 172;
export const MEMO_ACTION_MENU_GAP = 6;
export const MEMO_ACTION_MENU_VIEWPORT_MARGIN = 8;
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
// 詳細モーダルで、編集が止まってから自動保存するまでの待ち時間（ミリ秒）。
// Delay (ms) after the last edit before the detail modal autosaves.
export const DETAIL_AUTOSAVE_DELAY_MS = 900;
// 詳細モーダルを閉じるアニメーションの長さ（ミリ秒）。
// Length (ms) of the detail modal's closing animation.
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
// メモ用エージェントの候補プロンプトは MemoDetailModal が memo.agentPrompt* の
// カタログから渡す（日本語をここに固定すると英語UIに漏れるため）。
// The memo agent's quick prompts come from MemoDetailModal via the memo.agentPrompt*
// catalogue keys; hardcoding Japanese here would leak into the English UI.
