// prompt_manage.ts
import { confirmAndDelete } from "../core/api_actions";
import { buildPromptCard } from "../core/prompt_card";
import { fetchJsonOrThrow } from "../core/runtime_validation";

const initPromptManage = () => {
  const TITLE_CHAR_LIMIT = 17;
  const CONTENT_CHAR_LIMIT = 160;

  function truncateText(text: string, limit: number) {
    const safeText = text || "";
    const chars = Array.from(safeText);
    return chars.length > limit ? chars.slice(0, limit).join("") + "..." : safeText;
  }

  function truncateTitle(title: string) {
    return truncateText(title, TITLE_CHAR_LIMIT);
  }

  function truncateContent(content: string) {
    return truncateText(content, CONTENT_CHAR_LIMIT);
  }

  type PromptRecord = {
    id?: string | number;
    title: string;
    content: string;
    category: string;
    inputExamples: string;
    outputExamples: string;
    createdAt?: string;
  };

  const asString = (value: unknown) => {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    return String(value);
  };

  const asId = (value: unknown) => {
    if (typeof value === "string" || typeof value === "number") return value;
    return undefined;
  };

  const toPromptRecord = (raw: unknown): PromptRecord => {
    const obj = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
    return {
      id: asId(obj.id),
      title: asString(obj.title),
      content: asString(obj.content),
      category: asString(obj.category),
      inputExamples: asString(obj.input_examples),
      outputExamples: asString(obj.output_examples),
      createdAt: asString(obj.created_at) || undefined
    };
  };

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
            const truncatedContent = truncateContent(prompt.content);
            const card = buildPromptCard(
              {
                id: prompt.id,
                title: truncateTitle(prompt.title),
                content: truncatedContent,
                category: prompt.category,
                createdAt: prompt.createdAt ? new Date(prompt.createdAt).toLocaleString() : "",
                inputExamples: prompt.inputExamples || "",
                outputExamples: prompt.outputExamples || ""
              },
              {
                contentClass: "prompt-card__content",
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
          attachEventHandlers();
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

  // 各カードの「編集」「削除」ボタンにイベントを付与する関数
  function attachEventHandlers() {
    // 削除ボタンのイベント
    const deleteButtons = document.querySelectorAll<HTMLButtonElement>(".delete-btn");
    deleteButtons.forEach((btn) => {
      btn.addEventListener("click", async function () {
        const promptId = this.getAttribute("data-id");
        if (!promptId) return;
        await confirmAndDelete({
          message: "本当にこのプロンプトを削除しますか？",
          url: `/prompt_manage/api/prompts/${promptId}`,
          init: {
            headers: {
              "Content-Type": "application/json"
            }
          },
          successMessage: "削除しました。",
          errorMessage: "プロンプトの削除に失敗しました。",
          onSuccess: () => {
            loadMyPrompts();
          }
        });
      });
    });

    // 編集ボタンのイベント
    const editButtons = document.querySelectorAll<HTMLButtonElement>(".edit-btn");
    editButtons.forEach((btn) => {
      btn.addEventListener("click", function () {
        const promptId = this.getAttribute("data-id");
        const card = this.closest(".prompt-card") as HTMLElement | null;
        if (!card || !promptId) return;
        const titleElem = card.querySelector("h3");
        const contentElem = card.querySelector("p");
        const title = card.dataset.fullTitle || titleElem?.textContent || "";
        const content = card.dataset.fullContent || contentElem?.textContent || "";
        // 「カテゴリ: ○○」というテキストからカテゴリ部分を抽出
        const categoryText = card.querySelector(".meta span")?.textContent || "";
        const category = categoryText.replace("カテゴリ: ", "");
        const inputExamples = card.querySelector(".input-examples")?.textContent || "";
        const outputExamples = card.querySelector(".output-examples")?.textContent || "";

        // 編集フォームに現在値をセット
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

        // Bootstrap の Modal を利用してモーダル表示
        const editModalEl = document.getElementById("editModal");
        if (editModalEl) {
          const editModal = new bootstrap.Modal(editModalEl);
          editModal.show();
        }
      });
    });
  }

  // 編集フォームの送信（更新）処理
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
        // モーダルを閉じて一覧を再読み込み
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

  // 初期ロード
  loadMyPrompts();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPromptManage);
} else {
  initPromptManage();
}

export {};
