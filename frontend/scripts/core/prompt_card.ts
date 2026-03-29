/**
 * プロンプトカード共通ビルダー
 *
 * settings/prompt_manage, settings/prompt_list, prompt_share/prompt_manage, setup_task_cards の
 * 独立していた .prompt-card 生成ロジックを統合する。
 */
import { escapeHtml } from "./html";

export type PromptCardButton = {
  label: string;
  iconClass: string;
  btnClass: string;
};

export type PromptCardData = {
  id?: string | number;
  title: string;
  content: string;
  category?: string;
  createdAt?: string;
  inputExamples?: string;
  outputExamples?: string;
};

export type SetupTaskCardData = {
  task: string;
  promptTemplate: string;
  responseRules?: string;
  outputSkeleton?: string;
  inputExamples?: string;
  outputExamples?: string;
  isDefault?: boolean;
};

export type PromptCardOptions = {
  /** content の <p> に付与する CSS クラス */
  contentClass?: string;
  /** 日付ラベル（デフォルト "投稿日"） */
  dateLabel?: string;
  /** カード下部に表示するボタン */
  buttons?: PromptCardButton[];
  /** true にすると category/inputExamples/outputExamples を非表示でなくインライン表示する（prompt_list スタイル） */
  inlineMeta?: boolean;
  /** 切り詰め前のフルテキストを dataset に保持する */
  fullContent?: { title: string; content: string };
  /** data-category 属性を設定する */
  dataCategory?: string;
};

export type SetupTaskCardOptions = {
  layout: "setupTask";
};

type BuildPromptCardOptions = PromptCardOptions | SetupTaskCardOptions;

function buildSetupTaskCard(data: SetupTaskCardData): HTMLDivElement {
  const card = document.createElement("div");
  card.classList.add("prompt-card");

  card.dataset.task = data.task || "無題";
  card.dataset.prompt_template = data.promptTemplate || "プロンプトテンプレートはありません";
  card.dataset.response_rules = data.responseRules || "";
  card.dataset.output_skeleton = data.outputSkeleton || "";
  card.dataset.input_examples = data.inputExamples || "";
  card.dataset.output_examples = data.outputExamples || "";
  card.dataset.is_default = data.isDefault ? "true" : "false";

  const headerContainer = document.createElement("div");
  headerContainer.className = "header-container";

  const header = document.createElement("div");
  header.className = "task-header";
  header.textContent = data.task || "無題";

  const toggleBtn = document.createElement("button");
  toggleBtn.type = "button";
  toggleBtn.classList.add("btn", "btn-outline-success", "btn-md", "task-detail-toggle");
  toggleBtn.innerHTML = '<i class="bi bi-caret-down"></i>';

  headerContainer.append(header, toggleBtn);
  card.appendChild(headerContainer);
  return card;
}

function isSetupTaskCardRequest(
  data: PromptCardData | SetupTaskCardData,
  options: BuildPromptCardOptions
): data is SetupTaskCardData {
  return (options as SetupTaskCardOptions).layout === "setupTask";
}

export function buildPromptCard(
  data: PromptCardData | SetupTaskCardData,
  options: BuildPromptCardOptions = {}
): HTMLDivElement {
  if (isSetupTaskCardRequest(data, options)) {
    return buildSetupTaskCard(data);
  }

  const {
    contentClass,
    dateLabel = "投稿日",
    buttons = [],
    inlineMeta = false,
    fullContent,
    dataCategory
  } = options as PromptCardOptions;

  const card = document.createElement("div");
  card.classList.add("prompt-card");

  if (dataCategory) {
    card.setAttribute("data-category", dataCategory);
  }

  const safeTitle = escapeHtml(data.title);
  const safeContent = escapeHtml(data.content);
  const safeId = escapeHtml(String(data.id ?? ""));
  const safeCategory = escapeHtml(data.category || "");
  const safeCreatedAt = escapeHtml(data.createdAt || "");
  const safeInputExamples = escapeHtml(data.inputExamples || "");
  const safeOutputExamples = escapeHtml(data.outputExamples || "");

  const contentClassAttr = contentClass ? ` class="${contentClass}"` : "";
  const parts: string[] = [
    `<h3>${safeTitle}</h3>`,
    `<p${contentClassAttr}>${safeContent}</p>`
  ];

  if (inlineMeta) {
    if (data.category) {
      parts.push(`<div class="meta"><strong>カテゴリ:</strong> ${safeCategory}</div>`);
    }
    if (data.inputExamples) {
      parts.push(`<div class="meta"><strong>入力例:</strong> ${safeInputExamples}</div>`);
    }
    if (data.outputExamples) {
      parts.push(`<div class="meta"><strong>出力例:</strong> ${safeOutputExamples}</div>`);
    }
    parts.push(`<div class="meta"><span>${dateLabel}: ${safeCreatedAt}</span></div>`);
  } else {
    parts.push(
      `<div class="meta">`,
      `  <span>カテゴリ: ${safeCategory}</span><br>`,
      `  <span>${dateLabel}: ${safeCreatedAt}</span>`,
      `</div>`,
      `<p class="d-none input-examples">${safeInputExamples}</p>`,
      `<p class="d-none output-examples">${safeOutputExamples}</p>`
    );
  }

  if (buttons.length > 0) {
    const btnHtml = buttons
      .map(
        (btn) =>
          `<button class="${btn.btnClass}" data-id="${safeId}">` +
          `<i class="bi ${btn.iconClass}"></i> ${btn.label}` +
          `</button>`
      )
      .join("\n");
    parts.push(`<div class="btn-group">${btnHtml}</div>`);
  }

  card.innerHTML = parts.join("\n");

  if (fullContent) {
    card.dataset.fullTitle = fullContent.title;
    card.dataset.fullContent = fullContent.content;
  }

  return card;
}
