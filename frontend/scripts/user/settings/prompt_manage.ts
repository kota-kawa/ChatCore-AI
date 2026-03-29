import { toPromptRecord } from "./types";
import { confirmAndDelete } from "../../core/api_actions";
import { buildPromptCard } from "../../core/prompt_card";
import { fetchJsonOrThrow } from "../../core/runtime_validation";
import { truncateTitle } from "./utils";

export function setupPromptManageModule() {

  function attachEventHandlers(loadMyPrompts: () => void) {
    document.querySelectorAll<HTMLButtonElement>(".edit-btn").forEach((btn) => {
      btn.addEventListener("click", function () {
        const promptId = this.dataset.id;
        const card = this.closest(".prompt-card") as HTMLElement | null;
        if (!card || !promptId) return;

        const title = card.dataset.fullTitle || card.querySelector("h3")?.textContent || "";
        const content = card.dataset.fullContent || card.querySelector("p")?.textContent || "";
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
        await confirmAndDelete({
          message: "このプロンプトを削除しますか？",
          url: `/prompt_manage/api/prompts/${promptId}`,
          successMessage: "削除しました。",
          errorMessage: "プロンプトの削除に失敗しました。",
          onSuccess: () => {
            loadMyPrompts();
          }
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
            const card = buildPromptCard(
              {
                id: prompt.id,
                title: truncateTitle(prompt.title),
                content: prompt.content,
                category: prompt.category,
                createdAt: prompt.createdAt ? new Date(prompt.createdAt).toLocaleString() : "",
                inputExamples: prompt.inputExamples || "",
                outputExamples: prompt.outputExamples || ""
              },
              {
                buttons: [
                  {
                    label: "編集",
                    iconClass: "bi-pencil",
                    btnClass: "btn btn-sm btn-warning edit-btn"
                  },
                  {
                    label: "削除",
                    iconClass: "bi-trash",
                    btnClass: "btn btn-sm btn-danger delete-btn"
                  }
                ],
                fullContent: {
                  title: prompt.title,
                  content: prompt.content
                }
              }
            );
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
