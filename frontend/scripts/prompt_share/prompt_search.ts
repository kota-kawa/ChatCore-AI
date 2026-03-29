import { escapeHtml } from "../core/html";
import { fetchJsonOrThrow } from "../core/runtime_validation";

const initPromptSearch = () => {
  const searchButton = document.getElementById("searchButton");
  const searchInput = document.getElementById("searchInput") as HTMLInputElement | null;
  const promptCardsSection = document.querySelector(".prompt-cards") as HTMLElement | null;
  const selectedCategoryTitle = document.getElementById("selected-category-title");

  if (!searchInput || !promptCardsSection || !selectedCategoryTitle) {
    return;
  }
  const searchInputEl = searchInput;
  const promptCardsSectionEl = promptCardsSection;
  const selectedCategoryTitleEl = selectedCategoryTitle;

  // オリジナルの状態を保持しておく（検索クエリが空の場合に復元）
  const originalCardsHTML = promptCardsSectionEl.innerHTML;
  const originalHeaderText = selectedCategoryTitleEl.textContent || "";

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

  type PromptSearchRecord = {
    title: string;
    content: string;
    category: string;
    author: string;
  };

  const asString = (value: unknown) => {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    return String(value);
  };

  const toPromptSearchRecord = (raw: unknown): PromptSearchRecord => {
    const obj = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
    return {
      title: asString(obj.title),
      content: asString(obj.content),
      category: asString(obj.category),
      author: asString(obj.author)
    };
  };

  function searchPromptsServer() {
    const query = searchInputEl.value.trim();

    // クエリが空の場合は、オリジナルのカードとヘッダーを復元
    if (!query) {
      promptCardsSectionEl.innerHTML = originalCardsHTML;
      selectedCategoryTitleEl.textContent = originalHeaderText;
      return;
    }

    // ヘッダーを更新して検索結果を上部に表示
    selectedCategoryTitleEl.textContent = `検索結果: 「${query}」`;

    fetchJsonOrThrow<{ prompts?: unknown[] }>(
      `/search/prompts?q=${encodeURIComponent(query)}`,
      undefined,
      {
        defaultMessage: "検索に失敗しました。"
      }
    )
      .then(({ payload: data }) => {
        // .prompt-cards 内をクリアして検索結果を表示
        promptCardsSectionEl.innerHTML = "";
        const prompts = Array.isArray(data.prompts) ? data.prompts : [];
        if (prompts.length > 0) {
          prompts.forEach((rawPrompt: unknown) => {
            const prompt = toPromptSearchRecord(rawPrompt);
            const card = document.createElement("div");
            card.classList.add("prompt-card");
            // カテゴリフィルタ用に data-category 属性を設定
            card.setAttribute("data-category", prompt.category);
            const truncatedContent = truncateContent(prompt.content);
            const safeTitle = escapeHtml(truncateTitle(prompt.title));
            const safeContent = escapeHtml(truncatedContent);
            const safeCategory = escapeHtml(prompt.category);
            const safeAuthor = escapeHtml(prompt.author);

            card.innerHTML = `
              <h3>${safeTitle}</h3>
              <p class="prompt-card__content">${safeContent}</p>
              <div class="prompt-meta">
                <span>カテゴリ: ${safeCategory}</span>
                <span>投稿者: ${safeAuthor}</span>
              </div>
            `;
            card.dataset.fullTitle = prompt.title;
            card.dataset.fullContent = prompt.content;
            promptCardsSectionEl.appendChild(card);
          });
        } else {
          promptCardsSectionEl.innerHTML = "<p>該当するプロンプトが見つかりませんでした。</p>";
        }
      })
      .catch((err) => {
        console.error("検索エラー:", err);
        const message = err instanceof Error ? err.message : String(err);
        promptCardsSectionEl.innerHTML = `<p>エラーが発生しました: ${escapeHtml(message)}</p>`;
      });
  }

  searchButton?.addEventListener("click", searchPromptsServer);
  searchInputEl.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      searchPromptsServer();
    }
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPromptSearch);
} else {
  initPromptSearch();
}

export {};
