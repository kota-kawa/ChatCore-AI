import { toPromptListEntry } from "./types";
import { escapeHtml, truncateTitle } from "./utils";

type PromptListModuleOptions = {
  promptListEntriesEl: HTMLElement | null;
};

export function setupPromptListModule(options: PromptListModuleOptions) {
  const { promptListEntriesEl } = options;

  function attachPromptListHandlers(loadPromptList: () => void) {
    if (!promptListEntriesEl) return;

    promptListEntriesEl.querySelectorAll<HTMLButtonElement>(".remove-prompt-list-btn").forEach((btn) => {
      btn.addEventListener("click", function () {
        const entryId = this.dataset.id;
        if (!entryId) return;
        if (!confirm("プロンプトリストから削除しますか？")) return;

        fetch(`/prompt_manage/api/prompt_list/${entryId}`, {
          method: "DELETE",
          credentials: "same-origin"
        })
          .then((response) => response.json())
          .then((result) => {
            if (result.error) {
              alert("削除エラー: " + result.error);
            } else {
              alert(result.message || "プロンプトを削除しました。");
              loadPromptList();
            }
          })
          .catch((err) => {
            console.error("プロンプトリストの削除中にエラーが発生しました:", err);
            alert("プロンプトリストの削除中にエラーが発生しました。");
          });
      });
    });
  }

  function loadPromptList() {
    if (!promptListEntriesEl) return;

    promptListEntriesEl.innerHTML = "<p>読み込み中...</p>";

    fetch("/prompt_manage/api/prompt_list", {
      credentials: "same-origin"
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || "プロンプトリストの取得に失敗しました。");
        }
        return data;
      })
      .then((data) => {
        if (!data.prompts || data.prompts.length === 0) {
          promptListEntriesEl.innerHTML = "<p>プロンプトリストは存在しません。</p>";
          return;
        }

        promptListEntriesEl.innerHTML = "";
        const entries = Array.isArray(data.prompts) ? data.prompts : [];
        entries.forEach((rawEntry: unknown) => {
          const entry = toPromptListEntry(rawEntry);
          const card = document.createElement("div");
          card.classList.add("prompt-card");

          const createdAt = entry.createdAt ? new Date(entry.createdAt).toLocaleString() : "";
          const safeTitle = escapeHtml(truncateTitle(entry.title));
          const safeContent = escapeHtml(entry.content);
          const safeCategory = escapeHtml(entry.category);
          const safeInputExamples = escapeHtml(entry.inputExamples);
          const safeOutputExamples = escapeHtml(entry.outputExamples);
          const safeCreatedAt = escapeHtml(createdAt);
          const safeEntryId = escapeHtml(entry.id ?? "");
          const safeCategoryBlock = entry.category
            ? `<div class="meta"><strong>カテゴリ:</strong> ${safeCategory}</div>`
            : "";
          const safeInputBlock = entry.inputExamples
            ? `<div class="meta"><strong>入力例:</strong> ${safeInputExamples}</div>`
            : "";
          const safeOutputBlock = entry.outputExamples
            ? `<div class="meta"><strong>出力例:</strong> ${safeOutputExamples}</div>`
            : "";

          card.innerHTML = `
            <h3>${safeTitle}</h3>
            <p>${safeContent}</p>
            ${safeCategoryBlock}
            ${safeInputBlock}
            ${safeOutputBlock}
            <div class="meta">
              <span>保存日: ${safeCreatedAt}</span>
            </div>
            <div class="btn-group">
              <button class="btn btn-sm btn-danger remove-prompt-list-btn" data-id="${safeEntryId}">
                <i class="bi bi-trash"></i> 削除
              </button>
            </div>
          `;

          promptListEntriesEl.appendChild(card);
        });

        attachPromptListHandlers(loadPromptList);
      })
      .catch((err) => {
        console.error("プロンプトリスト取得エラー:", err);
        const message = err instanceof Error ? err.message : String(err);
        promptListEntriesEl.innerHTML = `<p>${escapeHtml(message)}</p>`;
      });
  }

  return {
    loadPromptList
  };
}
