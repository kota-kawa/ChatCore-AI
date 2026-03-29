// prompt_manage.ts
import { showConfirmModal } from "../core/alert_modal";
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

  function escapeHtml(value: unknown) {
    const text = value === null || value === undefined ? "" : String(value);
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
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
            const card = document.createElement("div");
            card.classList.add("prompt-card");
            const truncatedContent = truncateContent(prompt.content);
            const safeTitle = escapeHtml(truncateTitle(prompt.title));
            const safeContent = escapeHtml(truncatedContent);
            const safeCategory = escapeHtml(prompt.category);
            const safeCreatedAt = escapeHtml(prompt.createdAt ? new Date(prompt.createdAt).toLocaleString() : "");
            const safeInputExamples = escapeHtml(prompt.inputExamples || "");
            const safeOutputExamples = escapeHtml(prompt.outputExamples || "");
            const safePromptId = escapeHtml(prompt.id ?? "");

            card.innerHTML = `
              <h3>${safeTitle}</h3>
              <p class="prompt-card__content">${safeContent}</p>
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
            card.dataset.fullTitle = prompt.title || "";
            card.dataset.fullContent = prompt.content || "";
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
        const confirmed = await showConfirmModal("本当にこのプロンプトを削除しますか？");
        if (!confirmed) return;

        fetchJsonOrThrow<Record<string, unknown>>(`/prompt_manage/api/prompts/${promptId}`, {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json"
          }
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
