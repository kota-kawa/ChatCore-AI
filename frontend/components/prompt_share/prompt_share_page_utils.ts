import { getCategoryLabelOrFallback } from "../../scripts/prompt_share/prompt_category_registry";
import type { PromptData } from "../../scripts/prompt_share/types";

// カテゴリーに応じたカウントラベルを返す（allの場合は汎用ラベル）
// Return a count label based on the category (generic label for "all")
export function getCategoryCountLabel(category: string) {
  return category === "all" ? "公開プロンプト" : getCategoryLabelOrFallback(category);
}

// カテゴリーに応じたページタイトルを返す（allの場合は全件タイトル）
// Return the page title based on the category (all-items title for "all")
export function getCategoryTitle(category: string) {
  return category === "all"
    ? "全てのプロンプト"
    : `${getCategoryLabelOrFallback(category)} のプロンプト`;
}

// プロンプトのIDを文字列として返す（nullや未定義の場合は空文字）
// Return the prompt ID as a string (empty string for null or undefined)
export function getPromptId(prompt: PromptData | null | undefined) {
  if (!prompt) return "";
  if (prompt.id === undefined || prompt.id === null) return "";
  return String(prompt.id);
}

// モーダル内でフォーカス可能な要素を取得する（非表示・無効・不可視の要素は除外）
// Get focusable elements within a modal (excluding hidden, disabled, or invisible elements)
export function getModalFocusableElements(modal: HTMLElement) {
  const selector = [
    "a[href]",
    "area[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])"
  ].join(", ");

  return Array.from(modal.querySelectorAll<HTMLElement>(selector)).filter((element) => {
    const style = window.getComputedStyle(element);
    return (
      !element.closest("[hidden]") &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      element.getClientRects().length > 0
    );
  });
}
