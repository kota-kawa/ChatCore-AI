import { initPromptAssist } from "../components/prompt_assist";
import { invalidateTasksCache } from "./setup_tasks_cache";
import { loadTaskCards } from "./setup_task_cards";

function initNewPromptModal() {
  const openModalBtn = document.getElementById("openNewPromptModal") as HTMLButtonElement | null;
  const plusIcon = openModalBtn?.querySelector(".bi-plus-lg") as HTMLElement | null;
  const newPromptModal = document.getElementById("newPromptModal") as HTMLElement | null;
  const modalCloseBtn = document.getElementById("newModalCloseBtn") as HTMLButtonElement | null;
  const guardrailCheckbox = document.getElementById("new-guardrail-checkbox") as HTMLInputElement | null;
  const guardrailFields = document.getElementById("new-guardrail-fields") as HTMLElement | null;
  const newPostForm = document.getElementById("newPostForm") as HTMLFormElement | null;
  const promptAssistRoot = document.getElementById("newPromptAssistRoot");
  const submitStatusEl = document.getElementById("newPromptSubmitStatus") as HTMLElement | null;
  const titleInput = document.getElementById("new-prompt-title") as HTMLInputElement | null;
  const contentInput = document.getElementById("new-prompt-content") as HTMLTextAreaElement | null;
  const inputExampleEl = document.getElementById("new-prompt-input-example") as HTMLTextAreaElement | null;
  const outputExampleEl = document.getElementById("new-prompt-output-example") as HTMLTextAreaElement | null;
  const submitButton = newPostForm?.querySelector<HTMLButtonElement>('button[type="submit"]') || null;

  if (!newPromptModal || !newPostForm) {
    return;
  }

  let previouslyFocusedElement: HTMLElement | null = null;
  let isSubmitting = false;

  const showGuardrailFields = (visible: boolean) => {
    if (!guardrailFields) {
      return;
    }
    guardrailFields.style.display = visible ? "block" : "none";
  };

  const setComposerStatus = (
    message: string,
    variant: "info" | "success" | "error" = "info"
  ) => {
    if (!submitStatusEl) {
      return;
    }
    submitStatusEl.hidden = !message;
    submitStatusEl.textContent = message;
    submitStatusEl.dataset.variant = variant;
  };

  const setSubmitting = (submitting: boolean) => {
    isSubmitting = submitting;
    newPromptModal.dataset.submitting = submitting ? "true" : "false";
    if (submitButton) {
      submitButton.disabled = submitting;
      submitButton.innerHTML = submitting
        ? '<i class="bi bi-stars"></i> AIと投稿を準備中...'
        : '<i class="bi bi-upload"></i> 投稿する';
    }
  };

  const promptAssistController = initPromptAssist({
    root: promptAssistRoot,
    target: "task_modal",
    fields: {
      title: { label: "タイトル", element: titleInput },
      prompt_content: { label: "プロンプト内容", element: contentInput },
      input_examples: { label: "入力例", element: inputExampleEl },
      output_examples: { label: "出力例", element: outputExampleEl },
    },
    beforeApplyField: (fieldName) => {
      if ((fieldName === "input_examples" || fieldName === "output_examples") && guardrailCheckbox) {
        guardrailCheckbox.checked = true;
        showGuardrailFields(true);
      }
    },
  });

  const togglePlusRotation = (isRotated: boolean, options: { animate?: boolean } = {}) => {
    if (!openModalBtn) return;

    const { animate = true } = options;

    if (!animate && plusIcon) {
      plusIcon.classList.add("no-transition");
      openModalBtn.classList.toggle("is-rotated", Boolean(isRotated));

      requestAnimationFrame(() => {
        plusIcon.classList.remove("no-transition");
      });
      return;
    }

    openModalBtn.classList.toggle("is-rotated", Boolean(isRotated));
  };

  const resetComposer = () => {
    setComposerStatus("", "info");
    setSubmitting(false);
    promptAssistController?.reset();
  };

  const closeModal = (options: { skipRotation?: boolean; animateRotation?: boolean } = {}) => {
    if (!newPromptModal.classList.contains("show")) {
      return;
    }

    newPromptModal.classList.remove("show");
    newPromptModal.style.display = "none";
    document.body.classList.remove("new-prompt-modal-open");
    document.body.style.overflow = "";
    resetComposer();

    if (options.skipRotation) {
      if (openModalBtn) {
        openModalBtn.classList.remove("is-rotated");
      }
    } else {
      togglePlusRotation(false, { animate: Boolean(options.animateRotation) });
    }

    if (previouslyFocusedElement) {
      previouslyFocusedElement.focus();
    }
    previouslyFocusedElement = null;
  };

  const openModal = (options?: { animateRotation?: boolean }) => {
    previouslyFocusedElement = document.activeElement as HTMLElement | null;
    newPromptModal.style.display = "flex";
    newPromptModal.classList.add("show");
    document.body.classList.add("new-prompt-modal-open");
    document.body.style.overflow = "hidden";
    togglePlusRotation(true, { animate: Boolean(options?.animateRotation) });
    setComposerStatus("タイトルか本文がある状態で AI 補助を使うと、提案の精度が上がります。");
    requestAnimationFrame(() => {
      titleInput?.focus();
    });
  };

  if (newPromptModal) {
    newPromptModal.style.display = "none";
  }
  if (newPromptModal.classList.contains("show")) {
    closeModal({ skipRotation: true });
  } else if (openModalBtn) {
    openModalBtn.classList.remove("is-rotated");
  }

  if (openModalBtn) {
    openModalBtn.addEventListener("click", (event) => {
      event.preventDefault();
      if (newPromptModal.classList.contains("show")) {
        closeModal({ animateRotation: true });
      } else {
        openModal({ animateRotation: true });
      }
    });
  }

  if (modalCloseBtn) {
    modalCloseBtn.addEventListener("click", (event) => {
      event.preventDefault();
      closeModal();
    });
  }

  newPromptModal.addEventListener("click", (event) => {
    if (event.target === newPromptModal) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !newPromptModal.classList.contains("show") || isSubmitting) {
      return;
    }
    event.preventDefault();
    closeModal();
  });

  if (guardrailCheckbox) {
    guardrailCheckbox.addEventListener("change", () => {
      showGuardrailFields(guardrailCheckbox.checked);
    });
  }

  [titleInput, contentInput, inputExampleEl, outputExampleEl].forEach((field) => {
    field?.addEventListener("input", () => {
      if (submitStatusEl?.dataset.variant === "error") {
        setComposerStatus("", "info");
      }
    });
  });

  newPostForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!titleInput || !contentInput) {
      setComposerStatus("入力欄が見つかりませんでした。ページを再読み込みしてください。", "error");
      return;
    }

    if (isSubmitting) {
      return;
    }

    const data = {
      title: titleInput.value,
      prompt_content: contentInput.value,
      input_examples: guardrailCheckbox?.checked ? inputExampleEl?.value || "" : "",
      output_examples: guardrailCheckbox?.checked ? outputExampleEl?.value || "" : "",
    };

    setSubmitting(true);
    setComposerStatus("タスクを追加しています...", "info");

    try {
      const response = await fetch("/api/add_task", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      });
      const result = await response.json().catch(() => ({}));

      if (!response.ok || result.error) {
        throw new Error(result.error || "タスクの追加に失敗しました。");
      }

      setComposerStatus(result.message || "タスクが追加されました。", "success");
      newPostForm.reset();
      showGuardrailFields(false);
      invalidateTasksCache();
      loadTaskCards({ forceRefresh: true });

      window.setTimeout(() => {
        closeModal();
      }, 550);
    } catch (error) {
      setComposerStatus(
        error instanceof Error ? error.message : "エラーが発生しました。",
        "error"
      );
      setSubmitting(false);
    }
  });
}

export { initNewPromptModal };
