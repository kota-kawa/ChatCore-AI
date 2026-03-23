import { removePromptBookmark, savePromptBookmark, savePromptToList } from "./api";
import {
  escapeHtml,
  formatPromptDate,
  getBookmarkButtonMarkup,
  getPromptTypeIconClass,
  getPromptTypeLabel,
  normalizePromptData,
  normalizePromptType,
  truncateContent,
  truncateTitle
} from "./formatters";
import type { PromptData } from "./types";

type RenderPromptCardsOptions = {
  emptyMessage?: string;
  countLabel?: string;
};

type InitPromptCardsOptions = {
  promptContainer: HTMLElement;
  setPromptCountMeta: (text: string) => void;
  getIsLoggedIn: () => boolean;
  onOpenPromptShareDialog: (prompt: PromptData, event?: Event) => void;
  onShowPromptDetailModal: (prompt: PromptData) => void;
};

export function initPromptCards(options: InitPromptCardsOptions) {
  const {
    promptContainer,
    setPromptCountMeta,
    getIsLoggedIn,
    onOpenPromptShareDialog,
    onShowPromptDetailModal
  } = options;

  function closeAllDropdowns(exceptCard?: HTMLElement | null) {
    const openMenus = document.querySelectorAll<HTMLElement>(".prompt-actions-dropdown.is-open");
    openMenus.forEach((menu) => {
      if (exceptCard && exceptCard.contains(menu)) {
        return;
      }
      menu.classList.remove("is-open");
      const trigger = menu.parentElement?.querySelector(".meatball-menu") as HTMLElement | null;
      if (trigger) {
        trigger.setAttribute("aria-expanded", "false");
      }
      const parentCard = menu.closest(".prompt-card");
      if (parentCard) {
        parentCard.classList.remove("menu-open");
      }
    });
  }

  if (document.body && document.body.dataset.psDropdownListener !== "true") {
    document.body.dataset.psDropdownListener = "true";
    document.addEventListener("click", () => closeAllDropdowns());
  }

  function renderPromptStatusMessage(message: string, variant: "empty" | "error" = "empty") {
    promptContainer.innerHTML = `<p class="prompt-feedback prompt-feedback--${variant}">${escapeHtml(message)}</p>`;
  }

  function updateBookmarkButtonState(button: HTMLButtonElement | null, isBookmarked: boolean) {
    if (!button) return;
    button.classList.toggle("bookmarked", isBookmarked);
    button.setAttribute("aria-pressed", isBookmarked ? "true" : "false");
    button.setAttribute("data-tooltip", isBookmarked ? "保存を解除" : "このプロンプトを保存");
    button.innerHTML = getBookmarkButtonMarkup(isBookmarked);
  }

  function createPromptCardElement(prompt: PromptData) {
    const card = document.createElement("div");
    card.classList.add("prompt-card");
    if (prompt.category) {
      card.setAttribute("data-category", prompt.category);
    }

    const promptType = normalizePromptType(prompt.prompt_type);
    const isBookmarked = Boolean(prompt.bookmarked);
    const isSavedToList = Boolean(prompt.saved_to_list);
    const truncatedContent = truncateContent(prompt.content);
    const safeTitle = escapeHtml(truncateTitle(prompt.title));
    const safeContent = escapeHtml(truncatedContent);
    const safeCategory = escapeHtml(prompt.category || "未分類");
    const safeAuthor = escapeHtml(prompt.author || "匿名ユーザー");
    const safeCreatedAt = escapeHtml(formatPromptDate(prompt.created_at) || "日付未設定");
    const safePromptTypeLabel = escapeHtml(getPromptTypeLabel(promptType));
    const promptTypeIconClass = getPromptTypeIconClass(promptType);
    const bookmarkIcon = getBookmarkButtonMarkup(isBookmarked);
    const referenceImageMarkup = prompt.reference_image_url
      ? `
        <div class="prompt-card__image">
          <img src="${escapeHtml(prompt.reference_image_url)}" alt="${safeTitle} の作例画像" loading="lazy" decoding="async" />
        </div>
      `
      : "";

    card.innerHTML = `
      <div class="prompt-card__header">
        <div class="prompt-card__badges">
          <span class="prompt-card__category-pill">
            <i class="bi bi-hash"></i>
            <span>${safeCategory}</span>
          </span>
          <span class="prompt-card__type-pill prompt-card__type-pill--${promptType}">
            <i class="bi ${promptTypeIconClass}"></i>
            <span>${safePromptTypeLabel}</span>
          </span>
        </div>
        <button class="meatball-menu" type="button" aria-label="その他の操作" aria-haspopup="true" aria-expanded="false" data-tooltip="その他の操作" data-tooltip-placement="left">
          <i class="bi bi-three-dots"></i>
        </button>
      </div>

      <div class="prompt-actions-dropdown" role="menu">
        <button class="dropdown-item" type="button" role="menuitem" data-action="share">
          共有する
        </button>
        <button class="dropdown-item" type="button" role="menuitem" data-action="save-to-list" ${isSavedToList ? "disabled" : ""}>
          ${isSavedToList ? "プロンプトリストに保存済み" : "プロンプトリストに保存"}
        </button>
        <button class="dropdown-item" type="button" role="menuitem">ミュート</button>
        <button class="dropdown-item" type="button" role="menuitem">報告する</button>
      </div>

      ${referenceImageMarkup}
      <h3>${safeTitle}</h3>
      <p class="prompt-card__content">${safeContent}</p>

      <div class="prompt-meta">
        <div class="prompt-meta-info">
          <span class="prompt-meta-pill">
            <i class="bi bi-person"></i>
            ${safeAuthor}
          </span>
          <span class="prompt-meta-pill">
            <i class="bi bi-calendar3"></i>
            ${safeCreatedAt}
          </span>
        </div>
        <div class="prompt-actions">
          <button class="prompt-action-btn comment-btn" type="button" aria-label="コメント" data-tooltip="コメント（準備中）" data-tooltip-placement="top">
            <i class="bi bi-chat-dots"></i>
          </button>
          <button class="prompt-action-btn like-btn" type="button" aria-label="いいね" aria-pressed="false" data-tooltip="このプロンプトにいいね" data-tooltip-placement="top">
            <i class="bi bi-heart"></i>
          </button>
          <button class="prompt-action-btn bookmark-btn ${isBookmarked ? "bookmarked" : ""}" type="button" aria-label="保存" aria-pressed="${isBookmarked ? "true" : "false"}" data-tooltip="${isBookmarked ? "保存を解除" : "このプロンプトを保存"}" data-tooltip-placement="top">
            ${bookmarkIcon}
          </button>
        </div>
      </div>
    `;

    card.dataset.fullTitle = prompt.title || "";
    card.dataset.fullContent = prompt.content || "";
    card.dataset.promptType = promptType;
    card.dataset.savedToList = isSavedToList ? "true" : "false";
    card.dataset.psBound = "true";

    const bookmarkBtn = card.querySelector(".bookmark-btn") as HTMLButtonElement | null;
    if (bookmarkBtn) {
      bookmarkBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!getIsLoggedIn()) {
          alert("ブックマークするにはログインが必要です。");
          return;
        }

        const shouldBookmark = !bookmarkBtn.classList.contains("bookmarked");
        bookmarkBtn.disabled = true;

        const request = shouldBookmark ? savePromptBookmark(prompt) : removePromptBookmark(prompt);

        request
          .then((result) => {
            updateBookmarkButtonState(bookmarkBtn, shouldBookmark);
            prompt.bookmarked = shouldBookmark;
            if (result && result.message) {
              console.log(result.message);
            }
          })
          .catch((err) => {
            console.error("ブックマーク操作エラー:", err);
            alert("ブックマークの更新中にエラーが発生しました。");
          })
          .finally(() => {
            bookmarkBtn.disabled = false;
          });
      });
      bookmarkBtn.dataset.bound = "true";
    }

    const commentBtn = card.querySelector(".comment-btn") as HTMLButtonElement | null;
    if (commentBtn) {
      commentBtn.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    }

    const likeBtn = card.querySelector(".like-btn") as HTMLButtonElement | null;
    if (likeBtn) {
      likeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const liked = likeBtn.classList.toggle("liked");
        likeBtn.setAttribute("aria-pressed", liked ? "true" : "false");
        const icon = likeBtn.querySelector("i");
        if (icon) {
          icon.classList.toggle("bi-heart");
          icon.classList.toggle("bi-heart-fill");
        }
      });
    }

    const meatballBtn = card.querySelector(".meatball-menu") as HTMLButtonElement | null;
    const dropdownMenu = card.querySelector(".prompt-actions-dropdown") as HTMLElement | null;
    if (meatballBtn && dropdownMenu) {
      meatballBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        const willOpen = !dropdownMenu.classList.contains("is-open");
        closeAllDropdowns(card);
        dropdownMenu.classList.toggle("is-open", willOpen);
        meatballBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
        card.classList.toggle("menu-open", willOpen);
      });

      dropdownMenu.addEventListener("click", (event) => {
        event.stopPropagation();
      });

      dropdownMenu.querySelectorAll<HTMLButtonElement>(".dropdown-item").forEach((item) => {
        item.addEventListener("click", (event) => {
          event.stopPropagation();
          dropdownMenu.classList.remove("is-open");
          meatballBtn.setAttribute("aria-expanded", "false");
          card.classList.remove("menu-open");
        });
      });

      const saveMenuItem = dropdownMenu.querySelector<HTMLButtonElement>('[data-action="save-to-list"]');
      const shareMenuItem = dropdownMenu.querySelector<HTMLButtonElement>('[data-action="share"]');
      if (shareMenuItem) {
        shareMenuItem.addEventListener("click", (event) => {
          onOpenPromptShareDialog(prompt, event);
        });
      }
      if (saveMenuItem) {
        saveMenuItem.addEventListener("click", () => {
          if (!getIsLoggedIn()) {
            alert("プロンプトを保存するにはログインが必要です。");
            return;
          }

          if (prompt.saved_to_list) {
            alert("このプロンプトはすでにプロンプトリストに保存されています。");
            return;
          }

          saveMenuItem.disabled = true;
          savePromptToList(prompt)
            .then((result) => {
              prompt.saved_to_list = true;
              card.dataset.savedToList = "true";
              saveMenuItem.textContent = "プロンプトリストに保存済み";
              saveMenuItem.disabled = true;
              if (result && result.message) {
                console.log(result.message);
              }
            })
            .catch((err) => {
              console.error("プロンプト保存中にエラーが発生しました:", err);
              alert("プロンプトリストへの保存中にエラーが発生しました。");
            })
            .finally(() => {
              if (!prompt.saved_to_list) {
                saveMenuItem.disabled = false;
              }
            });
        });
      }
    }

    card.addEventListener("click", function (e) {
      const target = e.target as Element | null;
      if (target?.closest(".prompt-action-btn") || target?.closest(".meatball-menu")) {
        return;
      }
      closeAllDropdowns();
      onShowPromptDetailModal(prompt);
    });

    return card;
  }

  function renderPromptCards(prompts: PromptData[], options?: RenderPromptCardsOptions) {
    const countLabel = options?.countLabel || "公開プロンプト";
    setPromptCountMeta(`${countLabel}: ${prompts.length}件`);
    promptContainer.innerHTML = "";
    if (!prompts.length) {
      renderPromptStatusMessage(options?.emptyMessage || "プロンプトが見つかりませんでした。");
      return;
    }

    const fragment = document.createDocumentFragment();
    prompts.forEach((prompt) => {
      fragment.appendChild(createPromptCardElement(normalizePromptData(prompt)));
    });
    promptContainer.appendChild(fragment);
  }

  return {
    closeAllDropdowns,
    renderPromptStatusMessage,
    renderPromptCards
  };
}
