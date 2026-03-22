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

type PromptAssistSuggestionMode = "create" | "refine";

type PromptAssistResponse = {
  summary?: string;
  warnings?: string[];
  suggested_fields?: Partial<Record<PromptAssistFieldName, string>>;
  suggestion_modes?: Partial<Record<PromptAssistFieldName, PromptAssistSuggestionMode>>;
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

const PROMPT_ASSIST_ACTION_META: Record<
  PromptAssistAction,
  { label: string; icon: string; accent: string }
> = {
  generate_draft: {
    label: "AIで下書き生成",
    icon: "bi bi-stars",
    accent: "draft",
  },
  improve: {
    label: "改善する",
    icon: "bi bi-magic",
    accent: "refine",
  },
  shorten: {
    label: "短くする",
    icon: "bi bi-text-paragraph",
    accent: "trim",
  },
  expand: {
    label: "詳しくする",
    icon: "bi bi-arrows-angle-expand",
    accent: "expand",
  },
  generate_examples: {
    label: "入出力例を作る",
    icon: "bi bi-bezier2",
    accent: "examples",
  },
};

const PROMPT_ASSIST_ACTION_ORDER: PromptAssistAction[] = [
  "generate_draft",
  "improve",
  "shorten",
  "expand",
  "generate_examples",
];

const PROMPT_ASSIST_TARGET_META: Record<
  PromptAssistTarget,
  { title: string; lead: string; toggleLabel: string }
> = {
  task_modal: {
    title: "タスクの輪郭を整える",
    lead: "入力の抜けや重さを見ながら、タイトル・本文・例を滑らかに補います。",
    toggleLabel: "AI補助を開く",
  },
  shared_prompt_modal: {
    title: "公開用の見せ方まで磨く",
    lead: "投稿前に本文と例を引き上げ、共有しやすい完成度へ寄せます。",
    toggleLabel: "AI補助を開く",
  },
};

function createPromptAssistMarkup(panelId: string, target: PromptAssistTarget) {
  const targetMeta = PROMPT_ASSIST_TARGET_META[target];
  const actions = PROMPT_ASSIST_ACTION_ORDER.map((action) => {
    const meta = PROMPT_ASSIST_ACTION_META[action];
    return `
      <button
        type="button"
        class="prompt-assist__action"
        data-assist-action="${action}"
        data-accent="${meta.accent}"
      >
        <span class="prompt-assist__action-icon" aria-hidden="true">
          <i class="${meta.icon}"></i>
        </span>
        <span class="prompt-assist__action-label">${meta.label}</span>
      </button>
    `;
  }).join("");

  return `
    <section class="prompt-assist" data-assist-target="${target}" aria-label="AI入力補助">
      <button
        type="button"
        class="prompt-assist__toggle"
        data-assist-toggle
        aria-expanded="false"
        aria-controls="${panelId}"
        title="${targetMeta.toggleLabel}"
      >
        <span class="prompt-assist__toggle-glow" aria-hidden="true"></span>
        <span class="prompt-assist__toggle-icon" aria-hidden="true">
          <i class="bi bi-stars"></i>
        </span>
        <span class="prompt-assist__toggle-copy">
          <strong>AI Assist</strong>
          <small>磨く・補う・整える</small>
        </span>
        <span class="prompt-assist__toggle-ping" aria-hidden="true"></span>
      </button>
      <div class="prompt-assist__panel" id="${panelId}" data-assist-panel hidden>
        <div class="prompt-assist__panel-sheen" aria-hidden="true"></div>
        <div class="prompt-assist__hero">
          <div class="prompt-assist__hero-copy">
            <p class="prompt-assist__eyebrow">AI Input Assist</p>
            <h3 class="prompt-assist__title">${targetMeta.title}</h3>
            <p class="prompt-assist__lead">${targetMeta.lead}</p>
          </div>
          <div class="prompt-assist__hero-actions">
            <span class="prompt-assist__model">GPT OSS 20B</span>
            <button type="button" class="prompt-assist__close" data-assist-close aria-label="AI入力補助を閉じる">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        </div>
        <section class="prompt-assist__meter" aria-label="入力状況">
          <div class="prompt-assist__meter-bar">
            <span class="prompt-assist__meter-fill" data-assist-meter-fill></span>
          </div>
          <div class="prompt-assist__meter-meta">
            <span class="prompt-assist__meter-label" data-assist-meter-label></span>
            <span class="prompt-assist__last-action" data-assist-last-action>入力を確認中</span>
          </div>
        </section>
        <div class="prompt-assist__state-list" data-assist-state-list></div>
        <div class="prompt-assist__actions">${actions}</div>
        <div class="prompt-assist__loading" data-assist-loading hidden aria-live="polite">
          <span class="prompt-assist__loading-orb" aria-hidden="true"></span>
          <div class="prompt-assist__loading-copy">
            <strong>AIが提案を生成中</strong>
            <span>入力の温度感を見ながら、使いやすい形に整えています。</span>
          </div>
        </div>
        <p class="prompt-assist__status" data-assist-status hidden></p>
        <section class="prompt-assist__preview" data-assist-preview hidden>
          <div class="prompt-assist__preview-header">
            <div>
              <p class="prompt-assist__preview-eyebrow">AI Suggestion</p>
              <p class="prompt-assist__summary" data-assist-summary></p>
            </div>
            <button type="button" class="prompt-assist__apply-all" data-assist-apply-all>提案をまとめて反映</button>
          </div>
          <ul class="prompt-assist__warnings" data-assist-warnings hidden></ul>
          <div class="prompt-assist__field-list" data-assist-field-list></div>
        </section>
      </div>
    </section>
  `;
}

function createStateCard(label: string, value: string) {
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

function createFieldPreviewCard(
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

function animateAppliedField(
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

export function initPromptAssist(config: PromptAssistConfig) {
  const { root, target, fields, beforeApplyField } = config;
  if (!root) {
    return;
  }

  const panelId = `promptAssistPanel-${target}`;
  root.innerHTML = createPromptAssistMarkup(panelId, target);

  const actionButtons = Array.from(
    root.querySelectorAll<HTMLButtonElement>("[data-assist-action]")
  );
  const containerEl = root.querySelector<HTMLElement>(".prompt-assist");
  const toggleButton = root.querySelector<HTMLButtonElement>("[data-assist-toggle]");
  const closeButton = root.querySelector<HTMLButtonElement>("[data-assist-close]");
  const panelEl = root.querySelector<HTMLElement>("[data-assist-panel]");
  const meterFillEl = root.querySelector<HTMLElement>("[data-assist-meter-fill]");
  const meterLabelEl = root.querySelector<HTMLElement>("[data-assist-meter-label]");
  const lastActionEl = root.querySelector<HTMLElement>("[data-assist-last-action]");
  const stateListEl = root.querySelector<HTMLElement>("[data-assist-state-list]");
  const loadingEl = root.querySelector<HTMLElement>("[data-assist-loading]");
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
    !meterFillEl ||
    !meterLabelEl ||
    !lastActionEl ||
    !stateListEl ||
    !loadingEl ||
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
  let latestSuggestionModes: Partial<Record<PromptAssistFieldName, PromptAssistSuggestionMode>> = {};
  let isExpanded = false;
  let requestVersion = 0;

  const syncExpandedState = (expanded: boolean) => {
    isExpanded = expanded;
    containerEl.classList.toggle("is-open", expanded);
    panelEl.hidden = !expanded;
    toggleButton.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggleButton.title = expanded ? "AI補助を閉じる" : PROMPT_ASSIST_TARGET_META[target].toggleLabel;
  };

  const setLoading = (loading: boolean) => {
    containerEl.classList.toggle("is-loading", loading);
    loadingEl.hidden = !loading;
    actionButtons.forEach((button) => {
      button.disabled = loading;
      button.classList.toggle("is-loading", loading);
    });
    applyAllButton.disabled = loading;
  };

  const setPendingAction = (action: PromptAssistAction | null) => {
    actionButtons.forEach((button) => {
      const isActive = Boolean(action && button.dataset.assistAction === action);
      button.classList.toggle("is-active", isActive);
      if (isActive) {
        button.setAttribute("aria-busy", "true");
      } else {
        button.removeAttribute("aria-busy");
      }
    });

    if (!lastActionEl) {
      return;
    }
    lastActionEl.textContent = action
      ? `${PROMPT_ASSIST_ACTION_META[action].label} を生成中`
      : "入力を確認中";
  };

  const setStatus = (message: string, variant: "info" | "error" | "success") => {
    statusEl.hidden = !message;
    statusEl.textContent = message;
    statusEl.dataset.variant = variant;
  };

  const collectFieldValues = () => {
    const collected: Partial<Record<PromptAssistFieldName, string>> = {};
    Object.entries(fields).forEach(([fieldName, fieldConfig]) => {
      if (!fieldConfig?.element && !fieldConfig?.getValue) {
        return;
      }
      const value = fieldConfig.getValue
        ? fieldConfig.getValue()
        : fieldConfig.element?.value || "";
      collected[fieldName as PromptAssistFieldName] = value.trim();
    });
    return collected;
  };

  const renderFieldStateSummary = () => {
    const values = collectFieldValues();
    const entries = Object.entries(fields).filter(([, fieldConfig]) =>
      Boolean(fieldConfig?.element || fieldConfig?.getValue)
    ) as [PromptAssistFieldName, PromptAssistFieldConfig][];

    const filledCount = entries.filter(([fieldName]) => Boolean(values[fieldName])).length;
    const totalCount = entries.length;
    const progress = totalCount ? Math.round((filledCount / totalCount) * 100) : 0;

    meterFillEl.style.width = `${progress}%`;
    meterLabelEl.textContent = `${filledCount}/${totalCount} フィールド準備済み`;

    stateListEl.innerHTML = "";
    entries.forEach(([fieldName, fieldConfig]) => {
      stateListEl.append(createStateCard(fieldConfig.label, values[fieldName] || ""));
    });
  };

  const invalidatePendingResponse = () => {
    requestVersion += 1;
    setLoading(false);
    setPendingAction(null);
  };

  const openPanel = () => {
    syncExpandedState(true);
  };

  const closePanel = () => {
    invalidatePendingResponse();
    syncExpandedState(false);
  };

  const clearPreview = () => {
    latestSuggestion = {};
    latestSuggestionModes = {};
    previewEl.hidden = true;
    fieldListEl.innerHTML = "";
    warningsEl.innerHTML = "";
    warningsEl.hidden = true;
    summaryEl.textContent = "";
  };

  const reset = () => {
    invalidatePendingResponse();
    clearPreview();
    setStatus("", "info");
    renderFieldStateSummary();
    closePanel();
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
    animateAppliedField(fieldConfig);
    renderFieldStateSummary();
  };

  const renderPreview = (
    response: PromptAssistResponse,
    currentValues: Partial<Record<PromptAssistFieldName, string>>
  ) => {
    openPanel();
    latestSuggestion = response.suggested_fields || {};
    latestSuggestionModes = response.suggestion_modes || {};
    fieldListEl.innerHTML = "";

    Object.entries(latestSuggestion).forEach(([fieldName, fieldValue]) => {
      if (!fieldValue) {
        return;
      }
      const typedFieldName = fieldName as PromptAssistFieldName;
      const fieldConfig = fields[typedFieldName];
      if (!fieldConfig) {
        return;
      }

      const currentValue = currentValues[typedFieldName] || "";
      const mode =
        response.suggestion_modes?.[typedFieldName] ||
        (currentValue ? "refine" : "create");

      fieldListEl.append(
        createFieldPreviewCard(
          typedFieldName,
          fieldConfig.label,
          currentValue,
          fieldValue,
          mode
        )
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
    setStatus("提案を確認して、必要な項目だけ滑らかに反映できます。", "success");
    previewEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const runPromptAssist = async (action: PromptAssistAction) => {
    const currentValues = collectFieldValues();
    const currentRequestVersion = ++requestVersion;

    openPanel();
    setPendingAction(action);
    setLoading(true);
    setStatus("AIが提案を生成しています...", "info");

    try {
      const response = await fetch("/api/prompt-assist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target,
          action,
          fields: currentValues,
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as PromptAssistResponse & {
        error?: string;
      };

      if (currentRequestVersion !== requestVersion) {
        return;
      }

      if (!response.ok || payload.error) {
        throw new Error(payload.error || "AI補助の取得に失敗しました。");
      }

      renderPreview(payload, currentValues);
    } catch (error) {
      if (currentRequestVersion !== requestVersion) {
        return;
      }
      clearPreview();
      setStatus(
        error instanceof Error ? error.message : "AI補助の取得に失敗しました。",
        "error"
      );
    } finally {
      if (currentRequestVersion !== requestVersion) {
        return;
      }
      setLoading(false);
      setPendingAction(null);
      renderFieldStateSummary();
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
    const mode = latestSuggestionModes[fieldName];
    const suffix = mode === "create" ? "を補完しました。" : "へ提案を反映しました。";
    setStatus(`${fields[fieldName]?.label || "項目"}${suffix}`, "success");
  });

  Object.values(fields).forEach((fieldConfig) => {
    const element = fieldConfig?.element;
    if (!element) {
      return;
    }
    const syncState = () => {
      renderFieldStateSummary();
    };
    element.addEventListener("input", syncState);
    element.addEventListener("change", syncState);
  });

  renderFieldStateSummary();

  return { reset };
}
