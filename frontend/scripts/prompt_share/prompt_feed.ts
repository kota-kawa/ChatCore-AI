import { fetchPromptList, fetchPromptSearchResults } from "./api";
import { normalizePromptData } from "./formatters";
import { readPromptCache, writePromptCache } from "./storage";
import type { PromptData } from "./types";

type InitPromptFeedOptions = {
  promptContainer: HTMLElement;
  setPromptCountMeta: (text: string) => void;
  renderPromptCards: (
    prompts: PromptData[],
    options?: { emptyMessage?: string; countLabel?: string }
  ) => void;
  renderPromptStatusMessage: (message: string, variant?: "empty" | "error") => void;
};

export function initPromptFeed(options: InitPromptFeedOptions) {
  const { promptContainer, setPromptCountMeta, renderPromptCards, renderPromptStatusMessage } = options;
  const searchInput = document.getElementById("searchInput") as HTMLInputElement | null;
  const searchButton = document.getElementById("searchButton");
  const promptCardsSection = promptContainer;
  const selectedCategoryTitle = document.getElementById("selected-category-title");
  const categoryCards = document.querySelectorAll<HTMLElement>(".category-card");

  function loadPrompts() {
    return fetchPromptList()
      .then((data) => {
        const prompts = Array.isArray(data.prompts) ? data.prompts.map(normalizePromptData) : [];
        writePromptCache(prompts);
        renderPromptCards(prompts, { countLabel: "公開プロンプト" });
        const activeCategoryCard = document.querySelector<HTMLElement>(".category-card.active");
        if (activeCategoryCard) {
          applyCategoryFilter(activeCategoryCard);
        }
      })
      .catch((err) => {
        console.error("プロンプト取得エラー:", err);
        const message = err instanceof Error ? err.message : String(err);
        setPromptCountMeta("読み込みに失敗しました");
        renderPromptStatusMessage(`エラーが発生しました: ${message}`, "error");
      });
  }

  function searchPromptsServer() {
    if (!searchInput || !promptCardsSection || !selectedCategoryTitle) {
      return;
    }
    const query = searchInput.value.trim();

    // クエリが空の場合は、全プロンプトを再表示
    if (!query) {
      loadPrompts();
      selectedCategoryTitle.textContent = "全てのプロンプト";
      return;
    }

    // ヘッダーを検索結果用に更新
    selectedCategoryTitle.textContent = `検索結果: 「${query}」`;

    fetchPromptSearchResults(query)
      .then((data) => {
        const searchResults = Array.isArray(data.prompts)
          ? data.prompts.map(normalizePromptData)
          : [];
        renderPromptCards(searchResults, {
          countLabel: "検索結果",
          emptyMessage: "該当するプロンプトが見つかりませんでした。"
        });
      })
      .catch((err) => {
        console.error("検索エラー:", err);
        const message = err instanceof Error ? err.message : String(err);
        setPromptCountMeta("検索に失敗しました");
        renderPromptStatusMessage(`エラーが発生しました: ${message}`, "error");
      });
  }

  function applyCategoryFilter(card: HTMLElement) {
    // 全カテゴリボタンの active クラスをリセット
    categoryCards.forEach((c) => c.classList.remove("active"));
    card.classList.add("active");

    const selectedCategory = card.getAttribute("data-category") || "all";
    if (selectedCategoryTitle) {
      selectedCategoryTitle.textContent =
        selectedCategory === "all" ? "全てのプロンプト" : `${selectedCategory} のプロンプト`;
    }

    // 表示中のプロンプトカードにフィルタを適用
    const promptCards = document.querySelectorAll<HTMLElement>(".prompt-card");
    promptCards.forEach((prompt) => {
      const promptCategory = prompt.getAttribute("data-category");
      prompt.style.display =
        selectedCategory === "all" || promptCategory === selectedCategory ? "" : "none";
    });

    const visibleCount = Array.from(promptCards).filter(
      (prompt) => prompt.style.display !== "none"
    ).length;
    const countLabel = selectedCategory === "all" ? "公開プロンプト" : `${selectedCategory}`;
    setPromptCountMeta(`${countLabel}: ${visibleCount}件`);
  }

  // キャッシュがあれば先に描画してから、サーバーの最新データで更新する
  const cachedPrompts = readPromptCache();
  if (cachedPrompts && cachedPrompts.length > 0) {
    renderPromptCards(cachedPrompts, { countLabel: "公開プロンプト" });
  }
  void loadPrompts();

  if (searchButton && searchInput) {
    searchButton.addEventListener("click", searchPromptsServer);
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        searchPromptsServer();
      }
    });
  }

  if (categoryCards.length > 0 && selectedCategoryTitle) {
    categoryCards.forEach((card) => {
      card.addEventListener("click", () => {
        // 検索結果状態の場合は、検索入力をクリアし最新の全プロンプトを再取得
        if (searchInput && searchInput.value.trim() !== "") {
          searchInput.value = "";
          loadPrompts().then(() => {
            applyCategoryFilter(card);
          });
        } else {
          applyCategoryFilter(card);
        }
      });
    });
  }

  return {
    loadPrompts
  };
}
