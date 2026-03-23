import type { PromptData } from "./types";
import { getPromptTypeLabel, normalizePromptType } from "./formatters";

export function initPromptDetailModal(options: {
  openModal: (modal: HTMLElement, preferredElement?: HTMLElement | null) => void;
  closeModal: (modal: HTMLElement) => void;
}) {
  const { openModal, closeModal } = options;
  const promptDetailModal = document.getElementById("promptDetailModal") as HTMLElement | null;
  const closePromptDetailModalBtn = document.getElementById(
    "closePromptDetailModal"
  ) as HTMLButtonElement | null;

  function showPromptDetailModal(prompt: PromptData) {
    const modal = document.getElementById("promptDetailModal");
    const modalTitle = document.getElementById("modalPromptTitle");
    const modalPromptType = document.getElementById("modalPromptType");
    const modalCategory = document.getElementById("modalPromptCategory");
    const modalContent = document.getElementById("modalPromptContent");
    const modalAuthor = document.getElementById("modalPromptAuthor");
    const modalInputExamples = document.getElementById("modalInputExamples");
    const modalOutputExamples = document.getElementById("modalOutputExamples");
    const modalInputExamplesGroup = document.getElementById("modalInputExamplesGroup");
    const modalOutputExamplesGroup = document.getElementById("modalOutputExamplesGroup");
    const modalAiModel = document.getElementById("modalAiModel");
    const modalAiModelGroup = document.getElementById("modalAiModelGroup");
    const modalReferenceImage = document.getElementById("modalReferenceImage") as HTMLImageElement | null;
    const modalReferenceImageGroup = document.getElementById("modalReferenceImageGroup");

    if (!modal || !modalTitle || !modalPromptType || !modalCategory || !modalContent || !modalAuthor) return;

    // モーダルにデータを設定
    const promptType = normalizePromptType(prompt.prompt_type);
    modalTitle.textContent = prompt.title;
    modalPromptType.textContent = getPromptTypeLabel(promptType);
    modalCategory.textContent = prompt.category || "";
    modalContent.textContent = prompt.content;
    modalAuthor.textContent = prompt.author || "";

    // 使用AIモデルがある場合のみ表示
    if (prompt.ai_model && modalAiModel && modalAiModelGroup) {
      modalAiModel.textContent = prompt.ai_model;
      modalAiModelGroup.style.display = "block";
    } else if (modalAiModelGroup) {
      modalAiModelGroup.style.display = "none";
    }

    // 入力例・出力例がある場合のみ表示
    if (prompt.input_examples && modalInputExamples && modalInputExamplesGroup) {
      modalInputExamples.textContent = prompt.input_examples;
      modalInputExamplesGroup.style.display = "block";
    } else if (modalInputExamplesGroup) {
      modalInputExamplesGroup.style.display = "none";
    }

    if (prompt.output_examples && modalOutputExamples && modalOutputExamplesGroup) {
      modalOutputExamples.textContent = prompt.output_examples;
      modalOutputExamplesGroup.style.display = "block";
    } else if (modalOutputExamplesGroup) {
      modalOutputExamplesGroup.style.display = "none";
    }

    if (prompt.reference_image_url && modalReferenceImage && modalReferenceImageGroup) {
      modalReferenceImage.src = prompt.reference_image_url;
      modalReferenceImage.alt = `${prompt.title} の作例画像`;
      modalReferenceImageGroup.style.display = "block";
    } else if (modalReferenceImage && modalReferenceImageGroup) {
      modalReferenceImage.src = "";
      modalReferenceImage.alt = "";
      modalReferenceImageGroup.style.display = "none";
    }

    // モーダルを表示
    openModal(modal, closePromptDetailModalBtn);
  }

  // 閉じるボタンでモーダルを閉じる
  if (closePromptDetailModalBtn && promptDetailModal) {
    closePromptDetailModalBtn.addEventListener("click", function () {
      closeModal(promptDetailModal);
    });
  }

  // モーダル背景クリックで閉じる
  if (promptDetailModal) {
    promptDetailModal.addEventListener("click", function (e) {
      if (e.target === promptDetailModal) {
        closeModal(promptDetailModal);
      }
    });
  }

  return { showPromptDetailModal };
}
