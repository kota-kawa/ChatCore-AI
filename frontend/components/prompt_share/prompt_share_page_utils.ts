import type { PromptData } from "../../scripts/prompt_share/types";

export function getCategoryCountLabel(category: string) {
  return category === "all" ? "公開プロンプト" : category;
}

export function getCategoryTitle(category: string) {
  return category === "all" ? "全てのプロンプト" : `${category} のプロンプト`;
}

export function getPromptId(prompt: PromptData | null | undefined) {
  if (!prompt) return "";
  if (prompt.id === undefined || prompt.id === null) return "";
  return String(prompt.id);
}

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
