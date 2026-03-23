import type { PromptAssistFieldConfig } from "./types";

export function animateAppliedField(
  fieldConfig: PromptAssistFieldConfig | undefined
) {
  const element = fieldConfig?.element;
  if (!element) {
    return;
  }
  element.classList.remove("prompt-assist-applied");
  void element.offsetWidth;
  element.classList.add("prompt-assist-applied");
  window.setTimeout(() => {
    element.classList.remove("prompt-assist-applied");
  }, 900);
}
