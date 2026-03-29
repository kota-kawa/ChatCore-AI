import { toPromptRecord } from "./types";
import { showConfirmModal } from "../../core/alert_modal";
import { fetchJsonOrThrow } from "../../core/runtime_validation";
import { escapeHtml, truncateTitle } from "./utils";

export function setupPromptManageModule() {

  function attachEventHandlers(loadMyPrompts: () => void) {
    document.querySelectorAll<HTMLButtonElement>(".edit-btn").forEach((btn) => {
      btn.addEventListener("click", function () {
        const promptId = this.dataset.id;
        const card = this.closest(".prompt-card");
        if (!card || !promptId) return;

        const title = card.querySelector("h3")?.textContent || "";
        const content = card.querySelector("p")?.textContent || "";
        const metaSpans = card.querySelectorAll(".meta span");
        const category = metaSpans[0]?.textContent?.replace("カテゴリ: ", "") || "";
        const inputExamples = card.querySelector(".input-examples")?.textContent || "";
        const outputExamples = card.querySelector(".output-examples")?.textContent || "";

        const editPromptId = document.getElementById("editPromptId") as HTMLInputElement | null;
        const editTitle = document.getElementById("editTitle") as HTMLInputElement | null;
        const editCategory = document.getElementById("editCategory") as HTMLInputElement | null;
        const editContent = document.getElementById("editContent") as HTMLTextAreaElement | null;
        const editInputExamples = document.getElementById("editInputExamples") as HTMLTextAreaElement | null;
        const editOutputExamples = document.getElementById("editOutputExamples") as HTMLTextAreaElement | null;
        if (!editPromptId || !editTitle || !editCategory || !editContent || !editInputExamples || !editOutputExamples) {
          alert("編集フォームが見つかりませんでした。");
          return;
        }
        editPromptId.value = promptId;
        editTitle.value = title;
        editCategory.value = category;
        editContent.value = content;
        editInputExamples.value = inputExamples;
        editOutputExamples.value = outputExamples;

        const editModalEl = document.getElementById("editModal");
        if (editModalEl) {
          const editModal = new bootstrap.Modal(editModalEl);
          editModal.show();
        }
      });
    });

    document.querySelectorAll<HTMLButtonElement>(".delete-btn").forEach((btn) => {
      btn.addEventListener("click", async function () {
        const promptId = this.dataset.id;
        if (!promptId) return;
        const confirmed = await showConfirmModal("このプロンプトを削除しますか？");
        if (!confirmed) return;

        fetchJsonOrThrow<Record<string, unknown>>(`/prompt_manage/api/prompts/${promptId}`, {
          method: "DELETE"
        })
          .then(({ payload: result }) => {
            alert(typeof result.message === "string" ? result.message : "削除しました。");
            loadMyPrompts();
          })
          .catch((err) => {
            console.error("削除中のエラー:", err);
            alert(err instanceof Error ? err.message : "プロンプトの削除に失敗しました。");
          });
      });
    });
  }

  function loadMyPrompts() {
    fetchJsonOrThrow<{ prompts?: unknown[] }>("/prompt_manage/api/my_prompts", undefined, {
      defaultMessage: "プロンプトの取得に失敗しました。"
    })
      .then(({ payload: data }) => {
        const promptList = document.getElementById("promptList");
        if (!promptList) return;
        promptList.innerHTML = "";
        const prompts = Array.isArray(data.prompts) ? data.prompts : [];
        if (prompts.length > 0) {
          prompts.forEach((rawPrompt: unknown) => {
            const prompt = toPromptRecord(rawPrompt);
            const card = document.createElement("div");
            card.classList.add("prompt-card");
            const safeTitle = escapeHtml(truncateTitle(prompt.title));
            const safeContent = escapeHtml(prompt.content);
            const safeCategory = escapeHtml(prompt.category);
            const safeCreatedAt = escapeHtml(prompt.createdAt ? new Date(prompt.createdAt).toLocaleString() : "");
            const safeInputExamples = escapeHtml(prompt.inputExamples || "");
            const safeOutputExamples = escapeHtml(prompt.outputExamples || "");
            const safePromptId = escapeHtml(prompt.id ?? "");

            card.innerHTML = `
              <h3>${safeTitle}</h3>
              <p>${safeContent}</p>
              <div class="meta">
                <span>カテゴリ: ${safeCategory}</span><br>
                <span>投稿日: ${safeCreatedAt}</span>
              </div>
              <!-- 隠し要素として入力例と出力例を保持 -->
              <p class="d-none input-examples">${safeInputExamples}</p>
              <p class="d-none output-examples">${safeOutputExamples}</p>
              <div class="btn-group">
                <button class="btn btn-sm btn-warning edit-btn" data-id="${safePromptId}">
                  <i class="bi bi-pencil"></i> 編集
                </button>
                <button class="btn btn-sm btn-danger delete-btn" data-id="${safePromptId}">
                  <i class="bi bi-trash"></i> 削除
                </button>
              </div>
            `;
            promptList.appendChild(card);
          });
          attachEventHandlers(loadMyPrompts);
        } else {
          promptList.innerHTML = "<p>プロンプトが存在しません。</p>";
        }
      })
      .catch((err) => {
        console.error("プロンプト取得エラー:", err);
        const promptList = document.getElementById("promptList");
        if (promptList) {
          promptList.innerHTML = "<p>プロンプトの読み込み中にエラーが発生しました。</p>";
        }
      });
  }

  const editForm = document.getElementById("editForm") as HTMLFormElement | null;
  editForm?.addEventListener("submit", function (e) {
    e.preventDefault();
    const promptId = (document.getElementById("editPromptId") as HTMLInputElement | null)?.value;
    const title = (document.getElementById("editTitle") as HTMLInputElement | null)?.value;
    const category = (document.getElementById("editCategory") as HTMLInputElement | null)?.value;
    const content = (document.getElementById("editContent") as HTMLTextAreaElement | null)?.value;
    const inputExamples = (document.getElementById("editInputExamples") as HTMLTextAreaElement | null)?.value;
    const outputExamples = (document.getElementById("editOutputExamples") as HTMLTextAreaElement | null)?.value;
    if (!promptId || !title || !category || !content || inputExamples === undefined || outputExamples === undefined) {
      alert("編集フォームの値が不足しています。");
      return;
    }

    fetchJsonOrThrow<Record<string, unknown>>(`/prompt_manage/api/prompts/${promptId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        title,
        category,
        content,
        input_examples: inputExamples,
        output_examples: outputExamples
      })
    })
      .then(({ payload: result }) => {
        alert(typeof result.message === "string" ? result.message : "更新しました。");
        const editModalEl = document.getElementById("editModal");
        const modal = bootstrap.Modal.getInstance(editModalEl);
        modal?.hide();
        loadMyPrompts();
      })
      .catch((err) => {
        console.error("更新中のエラー:", err);
        alert(err instanceof Error ? err.message : "プロンプトの更新に失敗しました。");
      });
  });

  return {
    loadMyPrompts
  };
}
