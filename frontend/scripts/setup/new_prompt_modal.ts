import { initPromptAssist } from "../components/prompt_assist";

function initNewPromptModal() {
  const openModalBtn = document.getElementById("openNewPromptModal") as HTMLButtonElement | null;
  const plusIcon = openModalBtn?.querySelector(".bi-plus-lg") as HTMLElement | null;
  const newPromptModal = document.getElementById("newPromptModal");
  const modalCloseBtn = document.getElementById("newModalCloseBtn");
  const guardrailCheckbox = document.getElementById("new-guardrail-checkbox") as HTMLInputElement | null;
  const guardrailFields = document.getElementById("new-guardrail-fields");
  const newPostForm = document.getElementById("newPostForm") as HTMLFormElement | null;
  const promptAssistRoot = document.getElementById("newPromptAssistRoot");
  const titleInput = document.getElementById("new-prompt-title") as HTMLInputElement | null;
  const contentInput = document.getElementById("new-prompt-content") as HTMLTextAreaElement | null;
  const inputExampleEl = document.getElementById("new-prompt-input-example") as HTMLTextAreaElement | null;
  const outputExampleEl = document.getElementById("new-prompt-output-example") as HTMLTextAreaElement | null;

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
        if (guardrailFields) {
          guardrailFields.style.display = "block";
        }
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

  const closeModal = (options: { skipRotation?: boolean; animateRotation?: boolean } = {}) => {
    if (!newPromptModal) return;
    newPromptModal.classList.remove("show");
    (newPromptModal as HTMLElement).style.display = "none";
    promptAssistController?.reset();

    if (options.skipRotation) {
      if (openModalBtn) {
        openModalBtn.classList.remove("is-rotated");
      }
      return;
    }

    togglePlusRotation(false, { animate: Boolean(options.animateRotation) });
  };

  const openModal = (options?: { animateRotation?: boolean }) => {
    if (!newPromptModal) return;
    (newPromptModal as HTMLElement).style.display = "flex";
    newPromptModal.classList.add("show");
    togglePlusRotation(true, { animate: Boolean(options?.animateRotation) });
  };

  // 初期表示では回転アニメーションを発火させない
  if (newPromptModal) {
    (newPromptModal as HTMLElement).style.display = "none";
  }
  if (newPromptModal?.classList.contains("show")) {
    closeModal({ skipRotation: true });
  } else if (openModalBtn) {
    openModalBtn.classList.remove("is-rotated");
  }

  // ＋ボタンを押すとモーダル表示
  if (openModalBtn && newPromptModal) {
    openModalBtn.addEventListener("click", function (e) {
      e.preventDefault();
      if (newPromptModal.classList.contains("show")) {
        closeModal({ animateRotation: true });
      } else {
        openModal({ animateRotation: true });
      }
    });
  }

  // 閉じるボタンでモーダルを閉じる
  if (modalCloseBtn) {
    modalCloseBtn.addEventListener("click", function (e) {
      e.preventDefault();
      closeModal();
    });
  }

  // モーダル背景クリックで閉じる
  if (newPromptModal) {
    newPromptModal.addEventListener("click", function (e) {
      if (e.target === newPromptModal) {
        closeModal();
      }
    });
  }

  // ガードレールチェックボックスで入出力例部分の表示切替
  if (guardrailCheckbox && guardrailFields) {
    guardrailCheckbox.addEventListener("change", function () {
      guardrailFields.style.display = guardrailCheckbox.checked ? "block" : "none";
    });
  }

  // モーダル内フォームの送信
  if (newPostForm) {
    newPostForm.addEventListener("submit", function (e) {
      e.preventDefault();

      if (!titleInput || !contentInput) {
        alert("入力欄が見つかりませんでした。");
        return;
      }

      // 各入力項目の値を取得
      const title = titleInput.value;
      const content = contentInput.value;
      let inputExample = "";
      let outputExample = "";
      if (guardrailCheckbox?.checked) {
        inputExample = inputExampleEl ? inputExampleEl.value : "";
        outputExample = outputExampleEl ? outputExampleEl.value : "";
      }

      const data = {
        title: title,
        prompt_content: content,
        input_examples: inputExample,
        output_examples: outputExample
      };

      // POST リクエストでサーバーに送信
      fetch("/api/add_task", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(data)
      })
        .then((response) => response.json())
        .then((result) => {
          if (result.message) {
            alert(result.message);
            newPostForm.reset();
            if (guardrailFields) guardrailFields.style.display = "none";
            closeModal();
            if (window.invalidateTasksCache) window.invalidateTasksCache();

            // ここでタスク一覧を更新する
            if (window.loadTaskCards) window.loadTaskCards({ forceRefresh: true });
          } else {
            alert("エラー: " + result.error);
          }
        })
        .catch((error) => {
          alert("エラーが発生しました: " + error);
        });
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initNewPromptModal);
} else {
  initNewPromptModal();
}

export {};
