import type { PromptAssistFieldName, PromptAssistSuggestionMode } from "./types";

export function createStateCard(label: string, value: string) {
  const card = document.createElement("div");
  const isFilled = Boolean(value);
  card.className = "prompt-assist__state";
  card.dataset.state = isFilled ? "filled" : "empty";

  const dot = document.createElement("span");
  dot.className = "prompt-assist__state-dot";
  dot.setAttribute("aria-hidden", "true");

  const body = document.createElement("span");
  body.className = "prompt-assist__state-body";

  const title = document.createElement("strong");
  title.textContent = label;

  const meta = document.createElement("small");
  meta.textContent = isFilled ? "Ready" : "Empty";

  body.append(title, meta);
  card.append(dot, body);
  return card;
}

export function createFieldPreviewCard(
  fieldName: PromptAssistFieldName,
  fieldLabel: string,
  currentValue: string,
  nextValue: string,
  mode: PromptAssistSuggestionMode
) {
  const card = document.createElement("article");
  card.className = "prompt-assist__field";
  card.dataset.mode = mode;

  const header = document.createElement("div");
  header.className = "prompt-assist__field-header";

  const titleGroup = document.createElement("div");
  titleGroup.className = "prompt-assist__field-title-group";

  const label = document.createElement("strong");
  label.className = "prompt-assist__field-label";
  label.textContent = fieldLabel;

  const badge = document.createElement("span");
  badge.className = "prompt-assist__field-badge";
  badge.textContent = mode === "create" ? "新規補完" : "改善提案";

  titleGroup.append(label, badge);

  const applyButton = document.createElement("button");
  applyButton.type = "button";
  applyButton.className = "prompt-assist__field-apply";
  applyButton.dataset.assistApplyField = fieldName;
  applyButton.textContent = "反映";

  header.append(titleGroup, applyButton);

  const compare = document.createElement("div");
  compare.className = "prompt-assist__field-compare";

  if (currentValue) {
    const currentPanel = document.createElement("section");
    currentPanel.className = "prompt-assist__field-panel prompt-assist__field-panel--before";

    const currentEyebrow = document.createElement("span");
    currentEyebrow.className = "prompt-assist__field-panel-label";
    currentEyebrow.textContent = "現在";

    const currentBody = document.createElement("p");
    currentBody.className = "prompt-assist__field-body prompt-assist__field-body--muted";
    currentBody.textContent = currentValue;

    currentPanel.append(currentEyebrow, currentBody);
    compare.append(currentPanel);
  }

  const nextPanel = document.createElement("section");
  nextPanel.className = "prompt-assist__field-panel prompt-assist__field-panel--after";

  const nextEyebrow = document.createElement("span");
  nextEyebrow.className = "prompt-assist__field-panel-label";
  nextEyebrow.textContent = currentValue ? "AI提案" : "追加内容";

  const nextBody = document.createElement("p");
  nextBody.className = "prompt-assist__field-body";
  nextBody.textContent = nextValue;

  nextPanel.append(nextEyebrow, nextBody);
  compare.append(nextPanel);

  card.append(header, compare);
  return card;
}
