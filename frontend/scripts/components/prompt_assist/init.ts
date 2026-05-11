import { animateAppliedField } from "./animation";
import { createSuggestionRow } from "./cards";
import { PROMPT_ASSIST_PRIMARY_FIELDS, PROMPT_ASSIST_SKILL_META, PROMPT_ASSIST_TARGET_META } from "./constants";
import { createPromptAssistMarkup } from "./markup";
import { fetchJsonOrThrow } from "../../core/runtime_validation";
import type {
  PromptAssistConfig,
  PromptAssistFieldName,
  PromptAssistResponse,
} from "./types";

const PRIMARY_FIELD_LIST = PROMPT_ASSIST_PRIMARY_FIELDS as readonly string[];

function primaryFieldRank(fieldName: PromptAssistFieldName) {
  const index = PRIMARY_FIELD_LIST.indexOf(fieldName);
  return index === -1 ? PRIMARY_FIELD_LIST.length + 1 : index;
}

export function initPromptAssist(config: PromptAssistConfig) {
  const { root, target, fields, beforeApplyField } = config;
  if (!root) {
    return;
  }

  // 同一テンプレートを描画する（中身は固定文字列で、ユーザー入力は含まない）
  // Render a fixed template (string is static; no user input is interpolated).
  root.replaceChildren();
  root.insertAdjacentHTML("afterbegin", createPromptAssistMarkup(target));

  const containerEl = root.querySelector<HTMLElement>(".prompt-assist");
  const briefEl = root.querySelector<HTMLTextAreaElement>("[data-assist-brief]");
  const runButton = root.querySelector<HTMLButtonElement>("[data-assist-run]");
  const loadingEl = root.querySelector<HTMLElement>("[data-assist-loading]");
  const statusEl = root.querySelector<HTMLElement>("[data-assist-status]");
  const previewEl = root.querySelector<HTMLElement>("[data-assist-preview]");
  const summaryEl = root.querySelector<HTMLElement>("[data-assist-summary]");
  const warningsEl = root.querySelector<HTMLElement>("[data-assist-warnings]");
  const resultEl = root.querySelector<HTMLElement>("[data-assist-result]");
  const applyButton = root.querySelector<HTMLButtonElement>("[data-assist-apply]");
  const retryButton = root.querySelector<HTMLButtonElement>("[data-assist-retry]");
  const titleEl = root.querySelector<HTMLElement>("[data-assist-title]");
  const leadEl = root.querySelector<HTMLElement>("[data-assist-lead]");
  const briefLabelEl = root.querySelector<HTMLElement>("[data-assist-brief-label]");

  if (
    !containerEl ||
    !briefEl ||
    !runButton ||
    !loadingEl ||
    !statusEl ||
    !previewEl ||
    !summaryEl ||
    !warningsEl ||
    !resultEl ||
    !applyButton ||
    !retryButton
  ) {
    return;
  }

  let latestSuggestion: Partial<Record<PromptAssistFieldName, string>> = {};
  let requestVersion = 0;

  const setLoading = (loading: boolean) => {
    containerEl.classList.toggle("is-loading", loading);
    loadingEl.hidden = !loading;
    runButton.disabled = loading;
    applyButton.disabled = loading;
    retryButton.disabled = loading;
  };

  const setStatus = (message: string, variant: "info" | "error" | "success") => {
    statusEl.hidden = !message;
    statusEl.textContent = message;
    statusEl.dataset.variant = variant;
  };

  const fieldLabel = (fieldName: PromptAssistFieldName) => fields[fieldName]?.label || "項目";

  const collectFieldValues = () => {
    const collected: Partial<Record<PromptAssistFieldName, string>> = {};
    Object.entries(fields).forEach(([fieldName, fieldConfig]) => {
      if (!fieldConfig?.element && !fieldConfig?.getValue) {
        return;
      }
      const value = fieldConfig.getValue ? fieldConfig.getValue() : fieldConfig.element?.value || "";
      collected[fieldName as PromptAssistFieldName] = value.trim();
    });
    return collected;
  };

  const orderedSuggestionEntries = (): [PromptAssistFieldName, string][] => {
    const entries = Object.entries(latestSuggestion).filter(
      (entry): entry is [PromptAssistFieldName, string] =>
        Boolean(entry[1]) && Boolean(fields[entry[0] as PromptAssistFieldName]),
    );
    return entries.sort(([a], [b]) => primaryFieldRank(a) - primaryFieldRank(b));
  };

  const clearPreview = () => {
    latestSuggestion = {};
    previewEl.hidden = true;
    resultEl.replaceChildren();
    warningsEl.replaceChildren();
    warningsEl.hidden = true;
    summaryEl.textContent = "";
  };

  const invalidatePendingResponse = () => {
    // requestVersion を進めて古い非同期レスポンスを無効化する
    // Bump requestVersion so stale async responses are ignored.
    requestVersion += 1;
    setLoading(false);
  };

  const reset = () => {
    invalidatePendingResponse();
    clearPreview();
    setStatus("", "info");
    briefEl.value = "";
  };

  const applyFieldValue = (fieldName: PromptAssistFieldName) => {
    const fieldConfig = fields[fieldName];
    const nextValue = latestSuggestion[fieldName];
    if (!fieldConfig || typeof nextValue !== "string") {
      return;
    }
    if (!fieldConfig.element && !fieldConfig.setValue) {
      return;
    }
    beforeApplyField?.(fieldName);
    if (fieldConfig.setValue) {
      fieldConfig.setValue(nextValue);
      if (fieldConfig.element) {
        fieldConfig.element.value = nextValue;
        animateAppliedField(fieldConfig);
      }
    } else if (fieldConfig.element) {
      fieldConfig.element.value = nextValue;
      fieldConfig.element.dispatchEvent(new Event("input", { bubbles: true }));
      fieldConfig.element.dispatchEvent(new Event("change", { bubbles: true }));
      animateAppliedField(fieldConfig);
    }
  };

  const renderPreview = (response: PromptAssistResponse) => {
    // 反映できるフィールドだけを残し、本文を先頭にして1ブロックで提示する
    // Keep only applicable fields, render them as one block with the body first.
    latestSuggestion = {};
    Object.entries(response.suggested_fields || {}).forEach(([fieldName, value]) => {
      const typed = fieldName as PromptAssistFieldName;
      if (value && fields[typed]) {
        latestSuggestion[typed] = value;
      }
    });

    const entries = orderedSuggestionEntries();
    resultEl.replaceChildren();
    if (!entries.length) {
      clearPreview();
      setStatus("AIから反映できる内容を取得できませんでした。もう一度お試しください。", "error");
      return;
    }

    entries.forEach(([fieldName, value], index) => {
      const isPrimary = index === 0 && PRIMARY_FIELD_LIST.includes(fieldName);
      resultEl.append(createSuggestionRow(fieldLabel(fieldName), value, isPrimary));
    });

    summaryEl.textContent = response.summary || "AIがプロンプトの下書きを作成しました。";

    const warnings = Array.isArray(response.warnings) ? response.warnings.filter(Boolean) : [];
    warningsEl.replaceChildren();
    warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      warningsEl.append(item);
    });
    warningsEl.hidden = warnings.length === 0;

    previewEl.hidden = false;
    setStatus("内容を確認して「反映する」を押すと、フォームに入ります。", "success");
    previewEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const runPromptAssist = async () => {
    // 現在フォームのスナップショットと自由記述を送り、最新リクエストのみ反映する
    // Submit the current form snapshot plus the free-text brief; apply only the latest result.
    const currentValues = collectFieldValues();
    const instruction = briefEl.value.trim();
    const currentRequestVersion = ++requestVersion;

    clearPreview();
    setLoading(true);
    setStatus("AIがプロンプトを作成しています…", "info");

    try {
      const { payload } = await fetchJsonOrThrow<PromptAssistResponse & { error?: string }>(
        "/api/prompt-assist",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            target,
            action: "generate_draft",
            instruction,
            fields: currentValues,
          }),
        },
        {
          defaultMessage: "AIによる作成に失敗しました。",
        },
      );

      if (currentRequestVersion !== requestVersion) {
        return;
      }
      renderPreview(payload);
    } catch (error) {
      if (currentRequestVersion !== requestVersion) {
        return;
      }
      clearPreview();
      setStatus(error instanceof Error ? error.message : "AIによる作成に失敗しました。", "error");
    } finally {
      if (currentRequestVersion === requestVersion) {
        setLoading(false);
      }
    }
  };

  runButton.addEventListener("click", () => {
    void runPromptAssist();
  });

  applyButton.addEventListener("click", () => {
    const entries = orderedSuggestionEntries();
    if (!entries.length) {
      return;
    }
    entries.forEach(([fieldName]) => {
      applyFieldValue(fieldName);
    });
    const labels = entries.map(([fieldName]) => fieldLabel(fieldName)).join("・");
    setStatus(`${labels}をフォームに反映しました。`, "success");
  });

  retryButton.addEventListener("click", () => {
    clearPreview();
    setStatus("", "info");
    briefEl.focus();
  });

  const updateForPromptType = (promptType: string) => {
    if (target !== "shared_prompt_modal") return;
    const meta = promptType === "skill" ? PROMPT_ASSIST_SKILL_META : PROMPT_ASSIST_TARGET_META[target];
    if (titleEl) titleEl.textContent = meta.title;
    if (leadEl) leadEl.textContent = meta.lead;
    if (briefLabelEl) briefLabelEl.textContent = meta.briefLabel;
    briefEl.placeholder = meta.briefPlaceholder;
  };

  return { reset, updateForPromptType };
}
