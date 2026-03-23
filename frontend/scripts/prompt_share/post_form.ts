import { initPromptAssist } from "../components/prompt_assist";
import { createPrompt } from "./api";
import {
  ACCEPTED_PROMPT_IMAGE_EXTENSIONS,
  ACCEPTED_PROMPT_IMAGE_TYPES,
  PROMPT_IMAGE_MAX_BYTES
} from "./constants";
import { normalizePromptType } from "./formatters";
import type { PromptType } from "./types";

type InitPostFormOptions = {
  loadPrompts: () => void;
  closeModal: (modal: HTMLElement, options?: { rotateTrigger?: boolean }) => void;
  setHasAutoFilledAuthor: (value: boolean) => void;
};

export function initPromptPostForm(options: InitPostFormOptions) {
  const { loadPrompts, closeModal, setHasAutoFilledAuthor } = options;

  const promptTypeInputs = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[name="prompt-type"]')
  );
  const imagePromptFields = document.getElementById("imagePromptFields") as HTMLElement | null;
  const referenceImageInput = document.getElementById("prompt-reference-image") as HTMLInputElement | null;
  const promptImagePreview = document.getElementById("promptImagePreview") as HTMLElement | null;
  const promptImagePreviewImg = document.getElementById("promptImagePreviewImg") as HTMLImageElement | null;
  const promptImagePreviewName = document.getElementById("promptImagePreviewName") as HTMLElement | null;
  const promptImageClearButton = document.getElementById("promptImageClearButton") as HTMLButtonElement | null;
  let promptImagePreviewUrl = "";

  const postForm = document.getElementById("postForm") as HTMLFormElement | null;
  const promptAssistRoot = document.getElementById("sharedPromptAssistRoot");
  const promptPostStatusEl = document.getElementById("promptPostStatus") as HTMLElement | null;
  const titleInput = document.getElementById("prompt-title") as HTMLInputElement | null;
  const categoryInput = document.getElementById("prompt-category") as HTMLSelectElement | null;
  const contentInput = document.getElementById("prompt-content") as HTMLTextAreaElement | null;
  const authorInput = document.getElementById("prompt-author") as HTMLInputElement | null;
  const aiModelInput = document.getElementById("prompt-ai-model") as HTMLSelectElement | null;
  const guardrailCheckbox = document.getElementById("guardrail-checkbox") as HTMLInputElement | null;
  const guardrailFields = document.getElementById("guardrail-fields") as HTMLElement | null;
  const inputExample = document.getElementById("prompt-input-example") as HTMLTextAreaElement | null;
  const outputExample = document.getElementById("prompt-output-example") as HTMLTextAreaElement | null;
  const postSubmitButton = postForm?.querySelector<HTMLButtonElement>('button[type="submit"]') || null;
  let isPostSubmitting = false;

  function getSelectedPromptType(): PromptType {
    const checked = promptTypeInputs.find((input) => input.checked);
    return normalizePromptType(checked?.value);
  }

  function revokePromptImagePreview() {
    if (!promptImagePreviewUrl) return;
    URL.revokeObjectURL(promptImagePreviewUrl);
    promptImagePreviewUrl = "";
  }

  function clearPromptImageSelection() {
    revokePromptImagePreview();
    if (referenceImageInput) {
      referenceImageInput.value = "";
    }
    if (promptImagePreviewImg) {
      promptImagePreviewImg.src = "";
    }
    if (promptImagePreviewName) {
      promptImagePreviewName.textContent = "";
    }
    if (promptImagePreview) {
      promptImagePreview.hidden = true;
    }
  }

  function validateReferenceImageFile(file: File | null) {
    if (!file) return null;
    const lowerName = file.name.toLowerCase();
    const hasAcceptedExtension = ACCEPTED_PROMPT_IMAGE_EXTENSIONS.some((ext) =>
      lowerName.endsWith(ext)
    );
    if (!ACCEPTED_PROMPT_IMAGE_TYPES.has(file.type) && !hasAcceptedExtension) {
      return "画像は PNG / JPG / WebP / GIF のいずれかを指定してください。";
    }
    if (file.size > PROMPT_IMAGE_MAX_BYTES) {
      return "画像サイズは5MB以下にしてください。";
    }
    return null;
  }

  function updatePromptImagePreview(file: File | null) {
    if (!file || !promptImagePreview || !promptImagePreviewImg || !promptImagePreviewName) {
      clearPromptImageSelection();
      return;
    }

    revokePromptImagePreview();
    promptImagePreviewUrl = URL.createObjectURL(file);
    promptImagePreviewImg.src = promptImagePreviewUrl;
    promptImagePreviewName.textContent = `${file.name} (${Math.max(1, Math.round(file.size / 1024))}KB)`;
    promptImagePreview.hidden = false;
  }

  function syncPromptTypeUI() {
    const selectedPromptType = getSelectedPromptType();
    promptTypeInputs.forEach((input) => {
      input.closest(".prompt-type-option")?.classList.toggle("prompt-type-option--active", input.checked);
    });
    if (imagePromptFields) {
      imagePromptFields.hidden = selectedPromptType !== "image";
    }
    if (selectedPromptType !== "image") {
      clearPromptImageSelection();
    }
  }

  const showGuardrailFields = (visible: boolean) => {
    if (!guardrailFields) {
      return;
    }
    guardrailFields.style.display = visible ? "block" : "none";
  };

  const setPromptPostStatus = (
    message: string,
    variant: "info" | "success" | "error" = "info"
  ) => {
    if (!promptPostStatusEl) {
      return;
    }
    promptPostStatusEl.hidden = !message;
    promptPostStatusEl.textContent = message;
    promptPostStatusEl.dataset.variant = variant;
  };

  const setPostSubmitting = (submitting: boolean) => {
    isPostSubmitting = submitting;
    const postModalElement = document.getElementById("postModal") as HTMLElement | null;
    if (postModalElement) {
      postModalElement.dataset.submitting = submitting ? "true" : "false";
    }
    if (!postSubmitButton) {
      return;
    }
    postSubmitButton.disabled = submitting;
    postSubmitButton.innerHTML = submitting
      ? '<i class="bi bi-stars"></i> 投稿を準備中...'
      : '<i class="bi bi-upload"></i> 投稿する';
  };

  authorInput?.addEventListener("input", () => {
    setHasAutoFilledAuthor(false);
  });

  const promptAssistController = initPromptAssist({
    root: promptAssistRoot,
    target: "shared_prompt_modal",
    fields: {
      title: { label: "タイトル", element: titleInput },
      category: { label: "カテゴリ", element: categoryInput },
      content: { label: "プロンプト内容", element: contentInput },
      author: { label: "投稿者名", element: authorInput },
      ai_model: { label: "使用AIモデル", element: aiModelInput },
      prompt_type: {
        label: "投稿タイプ",
        element: null,
        getValue: () => getSelectedPromptType()
      },
      input_examples: { label: "入力例", element: inputExample },
      output_examples: { label: "出力例", element: outputExample }
    },
    beforeApplyField: (fieldName) => {
      if ((fieldName === "input_examples" || fieldName === "output_examples") && guardrailCheckbox) {
        guardrailCheckbox.checked = true;
        showGuardrailFields(true);
      }
    }
  });

  [titleInput, categoryInput, contentInput, authorInput, aiModelInput, inputExample, outputExample].forEach(
    (field) => {
      field?.addEventListener("input", () => {
        if (promptPostStatusEl?.dataset.variant === "error") {
          setPromptPostStatus("", "info");
        }
      });
      field?.addEventListener("change", () => {
        if (promptPostStatusEl?.dataset.variant === "error") {
          setPromptPostStatus("", "info");
        }
      });
    }
  );

  if (promptTypeInputs.length > 0) {
    promptTypeInputs.forEach((input) => {
      input.addEventListener("change", syncPromptTypeUI);
    });
    syncPromptTypeUI();
  }

  if (referenceImageInput) {
    referenceImageInput.addEventListener("change", () => {
      const file = referenceImageInput.files?.[0] || null;
      const validationError = validateReferenceImageFile(file);
      if (validationError) {
        alert(validationError);
        clearPromptImageSelection();
        return;
      }
      updatePromptImagePreview(file);
    });
  }

  if (promptImageClearButton) {
    promptImageClearButton.addEventListener("click", () => {
      clearPromptImageSelection();
    });
  }

  if (postForm) {
    postForm.addEventListener("submit", async function (e) {
      e.preventDefault();

      if (!titleInput || !categoryInput || !contentInput || !authorInput) {
        setPromptPostStatus("フォーム要素が見つかりませんでした。ページを再読み込みしてください。", "error");
        return;
      }
      if (isPostSubmitting) {
        return;
      }

      const promptType = getSelectedPromptType();
      const title = titleInput.value;
      const category = categoryInput.value;
      const content = contentInput.value;
      const author = authorInput.value;
      const ai_model = aiModelInput ? aiModelInput.value : "";
      const referenceImageFile = referenceImageInput?.files?.[0] || null;
      const referenceImageError = validateReferenceImageFile(referenceImageFile);
      if (referenceImageError) {
        setPromptPostStatus(referenceImageError, "error");
        return;
      }

      // ガードレール使用のチェックと値取得
      const useGuardrail = guardrailCheckbox ? guardrailCheckbox.checked : false;
      let input_examples = "";
      let output_examples = "";
      if (useGuardrail) {
        input_examples = inputExample ? inputExample.value : "";
        output_examples = outputExample ? outputExample.value : "";
      }

      const postData = new FormData();
      postData.append("title", title);
      postData.append("category", category);
      postData.append("content", content);
      postData.append("author", author);
      postData.append("prompt_type", promptType);
      postData.append("input_examples", input_examples);
      postData.append("output_examples", output_examples);
      postData.append("ai_model", ai_model);
      if (promptType === "image" && referenceImageFile) {
        postData.append("reference_image", referenceImageFile);
      }

      setPostSubmitting(true);
      setPromptPostStatus("プロンプトを投稿しています...", "info");

      try {
        const result = await createPrompt(postData);

        if (result.message) {
          console.log(result.message);
        }
        setPromptPostStatus("プロンプトが投稿されました。公開一覧へ反映します。", "success");
        postForm.reset();
        clearPromptImageSelection();
        syncPromptTypeUI();
        showGuardrailFields(false);
        loadPrompts();

        window.setTimeout(() => {
          const postModalElement = document.getElementById("postModal") as HTMLElement | null;
          if (postModalElement) {
            closeModal(postModalElement, { rotateTrigger: true });
          }
        }, 550);
      } catch (err) {
        console.error("投稿エラー:", err);
        setPromptPostStatus(
          err instanceof Error ? err.message : "プロンプト投稿中にエラーが発生しました。",
          "error"
        );
        setPostSubmitting(false);
      }
    });
  }

  // ------------------------------
  // ガードレールの表示切替処理
  // ------------------------------
  if (guardrailCheckbox && guardrailFields) {
    guardrailCheckbox.addEventListener("change", function () {
      showGuardrailFields(guardrailCheckbox.checked);
    });
  }

  window.addEventListener("beforeunload", () => {
    revokePromptImagePreview();
  });

  return {
    getIsPostSubmitting: () => isPostSubmitting,
    resetPostModalState: () => {
      setPromptPostStatus("", "info");
      setPostSubmitting(false);
      promptAssistController?.reset();
    },
    setPromptPostStatus
  };
}
