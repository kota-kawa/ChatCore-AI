import { toPromptListEntry } from "./types";
import { confirmAndDelete } from "../../core/api_actions";
import { buildPromptCard } from "../../core/prompt_card";
import { fetchJsonOrThrow } from "../../core/runtime_validation";
import { escapeHtml, truncateTitle } from "./utils";

type PromptListModuleOptions = {
  promptListEntriesEl: HTMLElement | null;
};

export function setupPromptListModule(options: PromptListModuleOptions) {
  const { promptListEntriesEl } = options;

  function attachPromptListHandlers(loadPromptList: () => void) {
    if (!promptListEntriesEl) return;

    promptListEntriesEl.querySelectorAll<HTMLButtonElement>(".remove-prompt-list-btn").forEach((btn) => {
      btn.addEventListener("click", async function () {
        const entryId = this.dataset.id;
        if (!entryId) return;
        await confirmAndDelete({
          message: "プロンプトリストから削除しますか？",
          url: `/prompt_manage/api/prompt_list/${entryId}`,
          init: {
            credentials: "same-origin"
          },
          successMessage: "プロンプトを削除しました。",
          errorMessage: "プロンプトリストの削除に失敗しました。",
          onSuccess: () => {
            loadPromptList();
          }
        });
      });
    });
  }

  function loadPromptList() {
    if (!promptListEntriesEl) return;

    promptListEntriesEl.innerHTML = "<p>読み込み中...</p>";

    fetchJsonOrThrow<{ prompts?: unknown[] }>(
      "/prompt_manage/api/prompt_list",
      {
        credentials: "same-origin"
      },
      {
        defaultMessage: "プロンプトリストの取得に失敗しました。"
      }
    )
      .then(({ payload: data }) => data)
      .then((data) => {
        if (!data.prompts || data.prompts.length === 0) {
          promptListEntriesEl.innerHTML = "<p>プロンプトリストは存在しません。</p>";
          return;
        }

        promptListEntriesEl.innerHTML = "";
        const entries = Array.isArray(data.prompts) ? data.prompts : [];
        entries.forEach((rawEntry: unknown) => {
          const entry = toPromptListEntry(rawEntry);
          const createdAt = entry.createdAt ? new Date(entry.createdAt).toLocaleString() : "";
          const card = buildPromptCard(
            {
              id: entry.id,
              title: truncateTitle(entry.title),
              content: entry.content,
              category: entry.category,
              createdAt,
              inputExamples: entry.inputExamples,
              outputExamples: entry.outputExamples
            },
            {
              inlineMeta: true,
              dateLabel: "保存日",
              buttons: [
                {
                  label: "削除",
                  iconClass: "bi-trash",
                  btnClass: "btn btn-sm btn-danger remove-prompt-list-btn"
                }
              ]
            }
          );

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
