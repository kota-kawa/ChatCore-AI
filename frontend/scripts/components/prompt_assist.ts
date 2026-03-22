type PromptAssistTarget = "task_modal" | "shared_prompt_modal";
type PromptAssistAction =
  | "generate_draft"
  | "improve"
  | "shorten"
  | "expand"
  | "generate_examples";

type PromptAssistFieldName =
  | "title"
  | "content"
  | "prompt_content"
  | "category"
  | "author"
  | "prompt_type"
  | "input_examples"
  | "output_examples"
  | "ai_model";

type PromptAssistResponse = {
  summary?: string;
  warnings?: string[];
  suggested_fields?: Partial<Record<PromptAssistFieldName, string>>;
  model?: string;
};

type PromptAssistFieldConfig = {
  label: string;
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
  getValue?: () => string;
};

type PromptAssistConfig = {
  root: HTMLElement | null;
  target: PromptAssistTarget;
  fields: Partial<Record<PromptAssistFieldName, PromptAssistFieldConfig>>;
  beforeApplyField?: (fieldName: PromptAssistFieldName) => void;
};

const PROMPT_ASSIST_ACTION_LABELS: Record<PromptAssistAction, string> = {
  generate_draft: "AIで下書き生成",
  improve: "改善する",
  shorten: "短くする",
  expand: "詳しくする",
  generate_examples: "入出力例を作る",
};

const PROMPT_ASSIST_ACTION_ORDER: PromptAssistAction[] = [
  "generate_draft",
  "improve",
  "shorten",
  "expand",
  "generate_examples",
];

function createPromptAssistMarkup(panelId: string) {
  const actions = PROMPT_ASSIST_ACTION_ORDER.map(
    (action) =>
      `<button type="button" class="prompt-assist__action" data-assist-action="${action}">${PROMPT_ASSIST_ACTION_LABELS[action]}</button>`
  ).join("");

  return `
    <section class="prompt-assist" aria-label="AI入力補助">
      <button
        type="button"
        class="prompt-assist__toggle"
        data-assist-toggle
        aria-expanded="false"
        aria-controls="${panelId}"
        title="AI入力補助を開く"
      >
        <span class="prompt-assist__toggle-icon" aria-hidden="true">
          <i class="bi bi-stars"></i>
        </span>
        <span class="prompt-assist__toggle-ping" aria-hidden="true"></span>
      </button>
      <div class="prompt-assist__panel" id="${panelId}" data-assist-panel hidden>
        <div class="prompt-assist__header">
          <div class="prompt-assist__header-copy">
            <p class="prompt-assist__eyebrow">AI入力補助</p>
            <h3 class="prompt-assist__title">下書きと編集をその場で補助</h3>
            <p class="prompt-assist__lead">GPT OSS 20B でタイトル、本文、入出力例をすばやく整えます。</p>
          </div>
          <div class="prompt-assist__header-actions">
            <span class="prompt-assist__model">GPT OSS 20B</span>
            <button type="button" class="prompt-assist__close" data-assist-close aria-label="AI入力補助を閉じる">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        </div>
        <div class="prompt-assist__actions">${actions}</div>
        <p class="prompt-assist__status" data-assist-status hidden></p>
        <section class="prompt-assist__preview" data-assist-preview hidden>
          <div class="prompt-assist__preview-header">
            <div>
              <p class="prompt-assist__preview-eyebrow">AI提案</p>
              <p class="prompt-assist__summary" data-assist-summary></p>
            </div>
            <button type="button" class="prompt-assist__apply-all" data-assist-apply-all>提案をすべて反映</button>
          </div>
          <ul class="prompt-assist__warnings" data-assist-warnings hidden></ul>
          <div class="prompt-assist__field-list" data-assist-field-list></div>
        </section>
      </div>
    </section>
  `;
}

function createFieldPreviewCard(
  fieldName: PromptAssistFieldName,
  fieldLabel: string,
  value: string
) {
  const card = document.createElement("article");
  card.className = "prompt-assist__field";

  const header = document.createElement("div");
  header.className = "prompt-assist__field-header";

  const label = document.createElement("strong");
  label.className = "prompt-assist__field-label";
  label.textContent = fieldLabel;

  const applyButton = document.createElement("button");
  applyButton.type = "button";
  applyButton.className = "prompt-assist__field-apply";
  applyButton.dataset.assistApplyField = fieldName;
  applyButton.textContent = "この項目を反映";

  header.append(label, applyButton);

  const body = document.createElement("pre");
  body.className = "prompt-assist__field-body";
  body.textContent = value;

  card.append(header, body);
  return card;
}

export function initPromptAssist(config: PromptAssistConfig) {
  const { root, target, fields, beforeApplyField } = config;
  if (!root) {
    return;
  }

  const panelId = `promptAssistPanel-${target}`;
  root.innerHTML = createPromptAssistMarkup(panelId);
  const actionButtons = Array.from(
    root.querySelectorAll<HTMLButtonElement>("[data-assist-action]")
  );
  const containerEl = root.querySelector<HTMLElement>(".prompt-assist");
  const toggleButton = root.querySelector<HTMLButtonElement>("[data-assist-toggle]");
  const closeButton = root.querySelector<HTMLButtonElement>("[data-assist-close]");
  const panelEl = root.querySelector<HTMLElement>("[data-assist-panel]");
  const statusEl = root.querySelector<HTMLElement>("[data-assist-status]");
  const previewEl = root.querySelector<HTMLElement>("[data-assist-preview]");
  const summaryEl = root.querySelector<HTMLElement>("[data-assist-summary]");
  const warningsEl = root.querySelector<HTMLElement>("[data-assist-warnings]");
  const fieldListEl = root.querySelector<HTMLElement>("[data-assist-field-list]");
  const applyAllButton = root.querySelector<HTMLButtonElement>("[data-assist-apply-all]");

  if (
    !containerEl ||
    !toggleButton ||
    !closeButton ||
    !panelEl ||
    !statusEl ||
    !previewEl ||
    !summaryEl ||
    !warningsEl ||
    !fieldListEl ||
    !applyAllButton
  ) {
    return;
  }

  let latestSuggestion: Partial<Record<PromptAssistFieldName, string>> = {};
  let isExpanded = false;

  const syncExpandedState = (expanded: boolean) => {
    isExpanded = expanded;
    containerEl.classList.toggle("is-open", expanded);
    panelEl.hidden = !expanded;
    toggleButton.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggleButton.title = expanded ? "AI入力補助を閉じる" : "AI入力補助を開く";
  };

  const openPanel = () => {
    syncExpandedState(true);
  };

  const closePanel = () => {
    syncExpandedState(false);
  };

  const reset = () => {
    latestSuggestion = {};
    previewEl.hidden = true;
    fieldListEl.innerHTML = "";
    warningsEl.innerHTML = "";
    warningsEl.hidden = true;
    summaryEl.textContent = "";
    setStatus("", "info");
    setLoading(false);
    closePanel();
  };

  const setLoading = (loading: boolean) => {
    actionButtons.forEach((button) => {
      button.disabled = loading;
      button.classList.toggle("is-loading", loading);
    });
    applyAllButton.disabled = loading;
  };

  const setStatus = (message: string, variant: "info" | "error" | "success") => {
    statusEl.hidden = !message;
    statusEl.textContent = message;
    statusEl.dataset.variant = variant;
  };

  const collectFieldValues = () => {
    const collected: Partial<Record<PromptAssistFieldName, string>> = {};
    Object.entries(fields).forEach(([fieldName, fieldConfig]) => {
      if (!fieldConfig?.element) {
        if (!fieldConfig?.getValue) {
          return;
        }
      }
      const value = fieldConfig.getValue ? fieldConfig.getValue() : fieldConfig.element?.value || "";
      collected[fieldName as PromptAssistFieldName] = value.trim();
    });
    return collected;
  };

  const applyFieldValue = (fieldName: PromptAssistFieldName) => {
    const fieldConfig = fields[fieldName];
    const nextValue = latestSuggestion[fieldName];
    if (!fieldConfig?.element || typeof nextValue !== "string") {
      return;
    }

    beforeApplyField?.(fieldName);
    fieldConfig.element.value = nextValue;
    fieldConfig.element.dispatchEvent(new Event("input", { bubbles: true }));
    fieldConfig.element.dispatchEvent(new Event("change", { bubbles: true }));
  };

  const renderPreview = (response: PromptAssistResponse) => {
    openPanel();
    latestSuggestion = response.suggested_fields || {};
    fieldListEl.innerHTML = "";

    Object.entries(latestSuggestion).forEach(([fieldName, fieldValue]) => {
      if (!fieldValue) {
        return;
      }
      const fieldConfig = fields[fieldName as PromptAssistFieldName];
      if (!fieldConfig) {
        return;
      }
      fieldListEl.append(
        createFieldPreviewCard(fieldName as PromptAssistFieldName, fieldConfig.label, fieldValue)
      );
    });

    if (!fieldListEl.children.length) {
      previewEl.hidden = true;
      setStatus("AIから反映可能な提案を取得できませんでした。", "error");
      return;
    }

    summaryEl.textContent = response.summary || "AIが入力内容の改善案を提案しました。";
    const warnings = Array.isArray(response.warnings) ? response.warnings.filter(Boolean) : [];
    warningsEl.innerHTML = "";
    warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      warningsEl.append(item);
    });
    warningsEl.hidden = warnings.length === 0;
    previewEl.hidden = false;
    setStatus("提案を確認して必要な項目だけ反映できます。", "success");
  };

  const runPromptAssist = async (action: PromptAssistAction) => {
    openPanel();
    setLoading(true);
    setStatus("AIが提案を作成しています...", "info");

    try {
      const response = await fetch("/api/prompt-assist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target,
          action,
          fields: collectFieldValues(),
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as PromptAssistResponse & {
        error?: string;
      };

      if (!response.ok || payload.error) {
        throw new Error(payload.error || "AI補助の取得に失敗しました。");
      }

      renderPreview(payload);
    } catch (error) {
      previewEl.hidden = true;
      setStatus(
        error instanceof Error ? error.message : "AI補助の取得に失敗しました。",
        "error"
      );
    } finally {
      setLoading(false);
    }
  };

  actionButtons.forEach((button) => {
    const action = button.dataset.assistAction as PromptAssistAction | undefined;
    if (!action) {
      return;
    }
    button.addEventListener("click", () => {
      void runPromptAssist(action);
    });
  });

  toggleButton.addEventListener("click", () => {
    if (isExpanded) {
      closePanel();
      return;
    }
    openPanel();
  });

  closeButton.addEventListener("click", () => {
    closePanel();
  });

  applyAllButton.addEventListener("click", () => {
    Object.keys(latestSuggestion).forEach((fieldName) => {
      applyFieldValue(fieldName as PromptAssistFieldName);
    });
    setStatus("提案をフォームへ反映しました。", "success");
  });

  fieldListEl.addEventListener("click", (event) => {
    const targetButton = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>(
      "[data-assist-apply-field]"
    );
    const fieldName = targetButton?.dataset.assistApplyField as PromptAssistFieldName | undefined;
    if (!fieldName) {
      return;
    }
    applyFieldValue(fieldName);
    setStatus(`${fields[fieldName]?.label || "項目"}へ提案を反映しました。`, "success");
  });

  return { reset };
}
