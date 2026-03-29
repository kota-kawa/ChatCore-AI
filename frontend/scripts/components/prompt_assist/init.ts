import { animateAppliedField } from "./animation";
import { createFieldPreviewCard, createStateCard } from "./cards";
import { PROMPT_ASSIST_ACTION_META, PROMPT_ASSIST_TARGET_META } from "./constants";
import { createPromptAssistMarkup } from "./markup";
import { fetchJsonOrThrow } from "../../core/runtime_validation";
import type {
  PromptAssistAction,
  PromptAssistConfig,
  PromptAssistFieldConfig,
  PromptAssistFieldName,
  PromptAssistResponse,
  PromptAssistSuggestionMode,
} from "./types";

export function initPromptAssist(config: PromptAssistConfig) {
  const { root, target, fields, beforeApplyField } = config;
  if (!root) {
    return;
  }

  // マークアップは毎回同一テンプレートで差し込み、対象別に panelId を分離する
  // Inject a consistent template and isolate panel IDs per target context.
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
    // 開閉状態は DOM/class/aria を同時更新してアクセシビリティと表示を揃える
    // Keep DOM/class/aria in sync for consistent visibility and accessibility.
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
    // 入力状況を集計して進捗メーターと状態カードへ反映する
    // Aggregate current field fill state into progress meter and summary cards.
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
    // requestVersion を進めて古いレスポンスを無効化する
    // Bump requestVersion so stale async responses are ignored.
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
    // 既存値と提案値を比較カードで可視化し、部分適用可能な形で提示する
    // Visualize current vs suggested values as per-field cards for selective apply.
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
    // 現在フォームのスナップショットを送信し、結果は最新リクエストのみ反映する
    // Submit current field snapshot and apply only the latest request result.
    const currentValues = collectFieldValues();
    const currentRequestVersion = ++requestVersion;

    openPanel();
    setPendingAction(action);
    setLoading(true);
    setStatus("AIが提案を生成しています...", "info");

    try {
      const { payload } = await fetchJsonOrThrow<PromptAssistResponse & {
        error?: string;
      }>(
        "/api/prompt-assist",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            target,
            action,
            fields: currentValues,
          }),
        },
        {
          defaultMessage: "AI補助の取得に失敗しました。"
        }
      );

      if (currentRequestVersion !== requestVersion) {
        return;
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
