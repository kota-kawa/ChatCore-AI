import { initPromptAssist } from "../components/prompt_assist";

type PromptType = "text" | "image";

type PromptData = {
  id?: string | number;
  title: string;
  content: string;
  category?: string;
  author?: string;
  prompt_type?: PromptType | string;
  reference_image_url?: string;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  bookmarked?: boolean;
  saved_to_list?: boolean;
  created_at?: string;
};

type CurrentUserResponse = {
  logged_in?: boolean;
  user?: {
    id?: number;
    email?: string;
    username?: string;
  };
};

const AUTH_STATE_CACHE_KEY = "chatcore.auth.loggedIn";
const PROMPTS_CACHE_KEY = "prompt_share.prompts.v1";
const PROMPT_IMAGE_MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED_PROMPT_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif"
]);
const ACCEPTED_PROMPT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];
const PROMPT_SHARE_TITLE = "Chat Core 共有プロンプト";
const PROMPT_SHARE_TEXT = "このプロンプトを共有しました。";

function readCachedAuthState() {
  try {
    const cached = localStorage.getItem(AUTH_STATE_CACHE_KEY);
    if (cached === "1") return true;
    if (cached === "0") return false;
  } catch {
    // localStorage が使えない環境ではキャッシュを無視
  }
  return null;
}

function writeCachedAuthState(loggedIn: boolean) {
  try {
    localStorage.setItem(AUTH_STATE_CACHE_KEY, loggedIn ? "1" : "0");
  } catch {
    // localStorage が使えない環境では保存をスキップ
  }
}

function readPromptCache() {
  try {
    const raw = sessionStorage.getItem(PROMPTS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed as PromptData[];
  } catch {
    return null;
  }
}

function writePromptCache(prompts: PromptData[]) {
  try {
    sessionStorage.setItem(PROMPTS_CACHE_KEY, JSON.stringify(prompts));
  } catch {
    // sessionStorage が使えない環境では保存をスキップ
  }
}

function initPromptSharePage(attempt = 0) {
  const promptContainer = document.querySelector(".prompt-cards") as HTMLElement | null;
  if (!promptContainer) {
    if (attempt < 10) {
      requestAnimationFrame(() => initPromptSharePage(attempt + 1));
    }
    return;
  }
  if (promptContainer.dataset.psInitialized === "true") {
    return;
  }
  promptContainer.dataset.psInitialized = "true";
  const promptCountMeta = document.getElementById("promptCountMeta") as HTMLElement | null;
  const cachedPromptShareUrls = new Map<string, string>();
  let currentSharePrompt: PromptData | null = null;
  let hasAutoFilledAuthor = false;

  function setPromptCountMeta(text: string) {
    if (!promptCountMeta) return;
    promptCountMeta.textContent = text;
  }

  function applyDefaultAuthorName(user?: { username?: string } | null) {
    const authorInput = document.getElementById("prompt-author") as HTMLInputElement | null;
    if (!authorInput) {
      return;
    }

    const username = String(user?.username || "").trim();
    if (!username) {
      return;
    }

    const currentValue = authorInput.value.trim();
    const shouldAutofill =
      !currentValue || currentValue === "アイデア職人" || hasAutoFilledAuthor;

    if (!shouldAutofill) {
      return;
    }

    authorInput.value = username;
    hasAutoFilledAuthor = true;
  }

  // ログイン状態の確認とUI切り替え
  const userIcon = document.getElementById("userIcon");
  const authButtons = document.getElementById("auth-buttons");
  let isLoggedIn = false; // ログイン状態を保持

  const notifyAuthState = (loggedIn: boolean) => {
    window.loggedIn = loggedIn;
    document.dispatchEvent(
      new CustomEvent("authstatechange", {
        detail: { loggedIn }
      })
    );
  };

  const applyAuthUI = (loggedIn: boolean) => {
    if (loggedIn) {
      if (authButtons) authButtons.style.display = "none";
      if (userIcon) userIcon.style.display = "";
      return;
    }

    if (authButtons) authButtons.style.display = "";
    if (userIcon) userIcon.style.display = "none";
    const loginBtn = document.getElementById("login-btn");
    if (loginBtn) loginBtn.onclick = () => (window.location.href = "/login");
  };

  // 前回状態を先に反映してポップインを抑える
  const cachedAuthState = readCachedAuthState();
  if (cachedAuthState !== null) {
    isLoggedIn = cachedAuthState;
    notifyAuthState(cachedAuthState);
    applyAuthUI(cachedAuthState);
  }

  window.setTimeout(() => {
    fetch("/api/current_user")
      .then((res) => (res.ok ? res.json() : { logged_in: false }))
      .then((data: CurrentUserResponse) => {
        isLoggedIn = Boolean(data.logged_in);
        writeCachedAuthState(isLoggedIn);
        notifyAuthState(isLoggedIn);
        applyAuthUI(isLoggedIn);
        if (isLoggedIn) {
          applyDefaultAuthorName(data.user);
        }
      })
      .catch((err) => {
        console.error("Error checking login status:", err);
        notifyAuthState(false);
        applyAuthUI(false);
      });
  }, 0);

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

  function formatPromptDate(createdAt?: string) {
    if (!createdAt) return "";
    const parsedDate = new Date(createdAt);
    if (Number.isNaN(parsedDate.getTime())) return "";
    return new Intl.DateTimeFormat("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).format(parsedDate);
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

  function getBookmarkButtonMarkup(isBookmarked: boolean) {
    const iconClass = isBookmarked ? "bi-bookmark-check-fill" : "bi-bookmark";
    return `<i class="bi ${iconClass}"></i>`;
  }

  function normalizePromptType(value?: string): PromptType {
    return value === "image" ? "image" : "text";
  }

  function getPromptTypeLabel(promptType: PromptType) {
    return promptType === "image" ? "画像生成" : "通常";
  }

  function getPromptTypeIconClass(promptType: PromptType) {
    return promptType === "image" ? "bi-image" : "bi-chat-square-text";
  }

  function renderPromptStatusMessage(message: string, variant: "empty" | "error" = "empty") {
    if (!promptContainer) return;
    promptContainer.innerHTML = `<p class="prompt-feedback prompt-feedback--${variant}">${escapeHtml(message)}</p>`;
  }

  function updateBookmarkButtonState(button: HTMLButtonElement | null, isBookmarked: boolean) {
    if (!button) return;
    button.classList.toggle("bookmarked", isBookmarked);
    button.setAttribute("aria-pressed", isBookmarked ? "true" : "false");
    button.setAttribute("data-tooltip", isBookmarked ? "保存を解除" : "このプロンプトを保存");
    button.innerHTML = getBookmarkButtonMarkup(isBookmarked);
  }

  function sendBookmarkRequest(method: "POST" | "DELETE", payload: Record<string, unknown>) {
    return fetch("/prompt_share/api/bookmark", {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.error) {
        throw new Error(data.error || "操作に失敗しました。");
      }
      return data;
    });
  }

  function savePromptBookmark(prompt: PromptData) {
    return sendBookmarkRequest("POST", {
      title: prompt.title,
      content: prompt.content,
      input_examples: prompt.input_examples || "",
      output_examples: prompt.output_examples || ""
    });
  }

  function removePromptBookmark(prompt: PromptData) {
    return sendBookmarkRequest("DELETE", {
      title: prompt.title
    });
  }

  function savePromptToList(prompt: PromptData) {
    if (prompt.id === undefined || prompt.id === null) {
      return Promise.reject(new Error("保存対象のプロンプトIDが見つかりません。"));
    }

    return fetch("/prompt_share/api/prompt_list", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt_id: prompt.id
      })
    }).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.error) {
        throw new Error(data.error || "操作に失敗しました。");
      }
      return data;
    });
  }

  function getPromptShareKey(prompt: PromptData | null) {
    if (!prompt) return "";
    if (prompt.id === undefined || prompt.id === null) return "";
    return String(prompt.id);
  }

  function getPromptShareModalElements() {
    return {
      modal: document.getElementById("promptShareModal") as HTMLElement | null,
      closeBtn: document.getElementById("closePromptShareModal") as HTMLButtonElement | null,
      createBtn: document.getElementById("prompt-share-create-btn") as HTMLButtonElement | null,
      copyBtn: document.getElementById("prompt-share-copy-btn") as HTMLButtonElement | null,
      webShareBtn: document.getElementById("prompt-share-web-btn") as HTMLButtonElement | null,
      linkInput: document.getElementById("prompt-share-link-input") as HTMLInputElement | null,
      statusEl: document.getElementById("prompt-share-status") as HTMLElement | null,
      snsX: document.getElementById("prompt-share-sns-x") as HTMLAnchorElement | null,
      snsLine: document.getElementById("prompt-share-sns-line") as HTMLAnchorElement | null,
      snsFacebook: document.getElementById("prompt-share-sns-facebook") as HTMLAnchorElement | null
    };
  }

  function setPromptShareStatus(message: string, isError = false) {
    const { statusEl } = getPromptShareModalElements();
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle("prompt-share-dialog__status--error", isError);
  }

  function updatePromptShareSnsLinks(shareUrl: string) {
    const { snsX, snsLine, snsFacebook } = getPromptShareModalElements();
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(PROMPT_SHARE_TEXT);

    if (snsX) {
      snsX.href = `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
    }
    if (snsLine) {
      snsLine.href = `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`;
    }
    if (snsFacebook) {
      snsFacebook.href = `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
    }
  }

  function setPromptShareUrl(shareUrl: string) {
    const { linkInput } = getPromptShareModalElements();
    if (!linkInput) return;
    linkInput.value = shareUrl;
    updatePromptShareSnsLinks(shareUrl);
  }

  function setPromptShareActionLoading(isLoading: boolean) {
    const { createBtn, copyBtn, webShareBtn } = getPromptShareModalElements();
    if (createBtn) {
      createBtn.disabled = isLoading;
      createBtn.textContent = isLoading ? "準備中..." : "リンクを表示";
    }
    if (copyBtn) copyBtn.disabled = isLoading;
    if (webShareBtn) webShareBtn.disabled = isLoading;
  }

  function buildPromptShareUrl(prompt: PromptData | null) {
    const promptKey = getPromptShareKey(prompt);
    if (!promptKey) {
      throw new Error("共有対象のプロンプトIDが見つかりません。");
    }
    return `${window.location.origin}/shared/prompt/${encodeURIComponent(promptKey)}`;
  }

  async function createPromptShareLink(forceRefresh = false) {
    const prompt = currentSharePrompt;
    const promptKey = getPromptShareKey(prompt);
    if (!prompt || !promptKey) {
      setPromptShareUrl("");
      setPromptShareStatus("共有するプロンプトを選択してください。", true);
      return;
    }

    if (!forceRefresh && cachedPromptShareUrls.has(promptKey)) {
      setPromptShareUrl(cachedPromptShareUrls.get(promptKey) || "");
      setPromptShareStatus("共有リンクを表示しています。");
      return;
    }

    setPromptShareActionLoading(true);
    setPromptShareStatus("共有リンクを準備しています...");

    try {
      const shareUrl = buildPromptShareUrl(prompt);
      cachedPromptShareUrls.set(promptKey, shareUrl);
      setPromptShareUrl(shareUrl);
      setPromptShareStatus("共有リンクを表示しています。");
    } catch (error) {
      setPromptShareStatus(
        error instanceof Error ? error.message : String(error),
        true
      );
    } finally {
      setPromptShareActionLoading(false);
    }
  }

  async function copyPromptShareLink() {
    const { linkInput } = getPromptShareModalElements();
    const shareUrl = linkInput?.value.trim() || "";
    if (!shareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }

    try {
      if (window.copyTextToClipboard) {
        await window.copyTextToClipboard(shareUrl);
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        throw new Error("このブラウザではコピー機能が利用できません。");
      }
      setPromptShareStatus("リンクをコピーしました。");
    } catch (error) {
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  }

  async function sharePromptWithNativeSheet() {
    const { linkInput } = getPromptShareModalElements();
    const shareUrl = linkInput?.value.trim() || "";
    if (!shareUrl) {
      setPromptShareStatus("先に共有リンクを表示してください。", true);
      return;
    }
    if (!navigator.share) {
      setPromptShareStatus("このブラウザはネイティブ共有に対応していません。", true);
      return;
    }

    try {
      await navigator.share({
        title: PROMPT_SHARE_TITLE,
        text: PROMPT_SHARE_TEXT,
        url: shareUrl
      });
      setPromptShareStatus("共有シートを開きました。");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setPromptShareStatus(error instanceof Error ? error.message : String(error), true);
    }
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
        if (!isLoggedIn) {
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

    const openPromptShareDialog = (event?: Event) => {
      event?.stopPropagation();
      currentSharePrompt = prompt;
      const { modal, createBtn } = getPromptShareModalElements();
      if (modal) {
        openModal(modal, createBtn);
      }
      void createPromptShareLink(false);
    };

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
          openPromptShareDialog(event);
        });
      }
      if (saveMenuItem) {
        saveMenuItem.addEventListener("click", () => {
          if (!isLoggedIn) {
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
      showPromptDetailModal(prompt);
    });

    return card;
  }

  // ------------------------------
  // サーバーからプロンプト一覧を取得して表示する関数（Promise を返す）
  // ------------------------------
  function normalizePromptData(prompt: PromptData): PromptData {
    return {
      ...prompt,
      prompt_type: normalizePromptType(prompt.prompt_type),
      reference_image_url: prompt.reference_image_url || "",
      bookmarked: Boolean(prompt.bookmarked),
      saved_to_list: Boolean(prompt.saved_to_list)
    };
  }

  function renderPromptCards(
    prompts: PromptData[],
    options?: { emptyMessage?: string; countLabel?: string }
  ) {
    if (!promptContainer) return;

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

  function loadPrompts() {
    return fetch("/prompt_share/api/prompts")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
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

  // キャッシュがあれば先に描画してから、サーバーの最新データで更新する
  const cachedPrompts = readPromptCache();
  if (cachedPrompts && cachedPrompts.length > 0) {
    renderPromptCards(cachedPrompts, { countLabel: "公開プロンプト" });
  }
  void loadPrompts();

  // ------------------------------
  // 検索機能（サーバー側検索）
  // ------------------------------
  const searchInput = document.getElementById("searchInput") as HTMLInputElement | null;
  const searchButton = document.getElementById("searchButton");
  const promptCardsSection = promptContainer;
  const selectedCategoryTitle = document.getElementById("selected-category-title");

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

    fetch(`/search/prompts?q=${encodeURIComponent(query)}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
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

  if (searchButton && searchInput) {
    searchButton.addEventListener("click", searchPromptsServer);
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        searchPromptsServer();
      }
    });
  }

  // ------------------------------
  // カテゴリ選択と表示
  // ------------------------------
  const categoryCards = document.querySelectorAll<HTMLElement>(".category-card");
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

  // カテゴリフィルタを適用する関数
  function applyCategoryFilter(card: HTMLElement) {
    // 全カテゴリボタンの active クラスをリセット
    categoryCards.forEach((c) => c.classList.remove("active"));
    card.classList.add("active");

    const selectedCategory = card.getAttribute("data-category") || "all";
    selectedCategoryTitle!.textContent =
      selectedCategory === "all" ? "全てのプロンプト" : `${selectedCategory} のプロンプト`;

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

  // ------------------------------
  // 投稿フォームの送信処理
  // ------------------------------
  const promptTypeInputs = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[name="prompt-type"]')
  );
  const imagePromptFields = document.getElementById("imagePromptFields") as HTMLElement | null;
  const referenceImageInput = document.getElementById("prompt-reference-image") as HTMLInputElement | null;
  const promptImagePreview = document.getElementById("promptImagePreview") as HTMLElement | null;
  const promptImagePreviewImg = document.getElementById("promptImagePreviewImg") as HTMLImageElement | null;
  const promptImagePreviewName = document.getElementById("promptImagePreviewName") as HTMLElement | null;
  const promptImageClearButton = document.getElementById("promptImageClearButton") as HTMLButtonElement | null;
  let promptImagePreviewUrl = "";

  function getSelectedPromptType(): PromptType {
    const checked = promptTypeInputs.find((input) => input.checked);
    return normalizePromptType(checked?.value);
  }

  function revokePromptImagePreview() {
    if (!promptImagePreviewUrl) return;
    URL.revokeObjectURL(promptImagePreviewUrl);
    promptImagePreviewUrl = "";
  }

  function clearPromptImageSelection() {
    revokePromptImagePreview();
    if (referenceImageInput) {
      referenceImageInput.value = "";
    }
    if (promptImagePreviewImg) {
      promptImagePreviewImg.src = "";
    }
    if (promptImagePreviewName) {
      promptImagePreviewName.textContent = "";
    }
    if (promptImagePreview) {
      promptImagePreview.hidden = true;
    }
  }

  function validateReferenceImageFile(file: File | null) {
    if (!file) return null;
    const lowerName = file.name.toLowerCase();
    const hasAcceptedExtension = ACCEPTED_PROMPT_IMAGE_EXTENSIONS.some((ext) =>
      lowerName.endsWith(ext)
    );
    if (!ACCEPTED_PROMPT_IMAGE_TYPES.has(file.type) && !hasAcceptedExtension) {
      return "画像は PNG / JPG / WebP / GIF のいずれかを指定してください。";
    }
    if (file.size > PROMPT_IMAGE_MAX_BYTES) {
      return "画像サイズは5MB以下にしてください。";
    }
    return null;
  }

  function updatePromptImagePreview(file: File | null) {
    if (!file || !promptImagePreview || !promptImagePreviewImg || !promptImagePreviewName) {
      clearPromptImageSelection();
      return;
    }

    revokePromptImagePreview();
    promptImagePreviewUrl = URL.createObjectURL(file);
    promptImagePreviewImg.src = promptImagePreviewUrl;
    promptImagePreviewName.textContent = `${file.name} (${Math.max(1, Math.round(file.size / 1024))}KB)`;
    promptImagePreview.hidden = false;
  }

  function syncPromptTypeUI() {
    const selectedPromptType = getSelectedPromptType();
    promptTypeInputs.forEach((input) => {
      input.closest(".prompt-type-option")?.classList.toggle("prompt-type-option--active", input.checked);
    });
    if (imagePromptFields) {
      imagePromptFields.hidden = selectedPromptType !== "image";
    }
    if (selectedPromptType !== "image") {
      clearPromptImageSelection();
    }
  }

  if (promptTypeInputs.length > 0) {
    promptTypeInputs.forEach((input) => {
      input.addEventListener("change", syncPromptTypeUI);
    });
    syncPromptTypeUI();
  }

  if (referenceImageInput) {
    referenceImageInput.addEventListener("change", () => {
      const file = referenceImageInput.files?.[0] || null;
      const validationError = validateReferenceImageFile(file);
      if (validationError) {
        alert(validationError);
        clearPromptImageSelection();
        return;
      }
      updatePromptImagePreview(file);
    });
  }

  if (promptImageClearButton) {
    promptImageClearButton.addEventListener("click", () => {
      clearPromptImageSelection();
    });
  }

  const postForm = document.getElementById("postForm") as HTMLFormElement | null;
  const promptAssistRoot = document.getElementById("sharedPromptAssistRoot");
  const promptPostStatusEl = document.getElementById("promptPostStatus") as HTMLElement | null;
  const titleInput = document.getElementById("prompt-title") as HTMLInputElement | null;
  const categoryInput = document.getElementById("prompt-category") as HTMLSelectElement | null;
  const contentInput = document.getElementById("prompt-content") as HTMLTextAreaElement | null;
  const authorInput = document.getElementById("prompt-author") as HTMLInputElement | null;
  const aiModelInput = document.getElementById("prompt-ai-model") as HTMLSelectElement | null;
  const guardrailCheckbox = document.getElementById("guardrail-checkbox") as HTMLInputElement | null;
  const guardrailFields = document.getElementById("guardrail-fields") as HTMLElement | null;
  const inputExample = document.getElementById("prompt-input-example") as HTMLTextAreaElement | null;
  const outputExample = document.getElementById("prompt-output-example") as HTMLTextAreaElement | null;
  const postSubmitButton = postForm?.querySelector<HTMLButtonElement>('button[type="submit"]') || null;
  let isPostSubmitting = false;

  const showGuardrailFields = (visible: boolean) => {
    if (!guardrailFields) {
      return;
    }
    guardrailFields.style.display = visible ? "block" : "none";
  };

  const setPromptPostStatus = (
    message: string,
    variant: "info" | "success" | "error" = "info"
  ) => {
    if (!promptPostStatusEl) {
      return;
    }
    promptPostStatusEl.hidden = !message;
    promptPostStatusEl.textContent = message;
    promptPostStatusEl.dataset.variant = variant;
  };

  const setPostSubmitting = (submitting: boolean) => {
    isPostSubmitting = submitting;
    const postModalElement = document.getElementById("postModal") as HTMLElement | null;
    if (postModalElement) {
      postModalElement.dataset.submitting = submitting ? "true" : "false";
    }
    if (!postSubmitButton) {
      return;
    }
    postSubmitButton.disabled = submitting;
    postSubmitButton.innerHTML = submitting
      ? '<i class="bi bi-stars"></i> 投稿を準備中...'
      : '<i class="bi bi-upload"></i> 投稿する';
  };

  authorInput?.addEventListener("input", () => {
    hasAutoFilledAuthor = false;
  });

  const promptAssistController = initPromptAssist({
    root: promptAssistRoot,
    target: "shared_prompt_modal",
    fields: {
      title: { label: "タイトル", element: titleInput },
      category: { label: "カテゴリ", element: categoryInput },
      content: { label: "プロンプト内容", element: contentInput },
      author: { label: "投稿者名", element: authorInput },
      ai_model: { label: "使用AIモデル", element: aiModelInput },
      prompt_type: {
        label: "投稿タイプ",
        element: null,
        getValue: () => getSelectedPromptType(),
      },
      input_examples: { label: "入力例", element: inputExample },
      output_examples: { label: "出力例", element: outputExample },
    },
    beforeApplyField: (fieldName) => {
      if ((fieldName === "input_examples" || fieldName === "output_examples") && guardrailCheckbox) {
        guardrailCheckbox.checked = true;
        showGuardrailFields(true);
      }
    },
  });

  [titleInput, categoryInput, contentInput, authorInput, aiModelInput, inputExample, outputExample].forEach(
    (field) => {
      field?.addEventListener("input", () => {
        if (promptPostStatusEl?.dataset.variant === "error") {
          setPromptPostStatus("", "info");
        }
      });
      field?.addEventListener("change", () => {
        if (promptPostStatusEl?.dataset.variant === "error") {
          setPromptPostStatus("", "info");
        }
      });
    }
  );

  if (postForm) {
    postForm.addEventListener("submit", async function (e) {
      e.preventDefault();

      if (!titleInput || !categoryInput || !contentInput || !authorInput) {
        setPromptPostStatus("フォーム要素が見つかりませんでした。ページを再読み込みしてください。", "error");
        return;
      }
      if (isPostSubmitting) {
        return;
      }

      const promptType = getSelectedPromptType();
      const title = titleInput.value;
      const category = categoryInput.value;
      const content = contentInput.value;
      const author = authorInput.value;
      const ai_model = aiModelInput ? aiModelInput.value : "";
      const referenceImageFile = referenceImageInput?.files?.[0] || null;
      const referenceImageError = validateReferenceImageFile(referenceImageFile);
      if (referenceImageError) {
        setPromptPostStatus(referenceImageError, "error");
        return;
      }

      // ガードレール使用のチェックと値取得
      const useGuardrail = guardrailCheckbox ? guardrailCheckbox.checked : false;
      let input_examples = "";
      let output_examples = "";
      if (useGuardrail) {
        input_examples = inputExample ? inputExample.value : "";
        output_examples = outputExample ? outputExample.value : "";
      }

      const postData = new FormData();
      postData.append("title", title);
      postData.append("category", category);
      postData.append("content", content);
      postData.append("author", author);
      postData.append("prompt_type", promptType);
      postData.append("input_examples", input_examples);
      postData.append("output_examples", output_examples);
      postData.append("ai_model", ai_model);
      if (promptType === "image" && referenceImageFile) {
        postData.append("reference_image", referenceImageFile);
      }

      setPostSubmitting(true);
      setPromptPostStatus("プロンプトを投稿しています...", "info");

      try {
        const response = await fetch("/prompt_share/api/prompts", {
          method: "POST",
          body: postData
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok || result.error) {
          throw new Error(result.error || "プロンプト投稿中にエラーが発生しました。");
        }

        if (result.message) {
          console.log(result.message);
        }
        setPromptPostStatus("プロンプトが投稿されました。公開一覧へ反映します。", "success");
        postForm.reset();
        clearPromptImageSelection();
        syncPromptTypeUI();
        showGuardrailFields(false);
        loadPrompts();

        window.setTimeout(() => {
          const postModalElement = document.getElementById("postModal") as HTMLElement | null;
          if (postModalElement) {
            closeModal(postModalElement, { rotateTrigger: true });
          }
        }, 550);
      } catch (err) {
        console.error("投稿エラー:", err);
        setPromptPostStatus(
          err instanceof Error ? err.message : "プロンプト投稿中にエラーが発生しました。",
          "error"
        );
        setPostSubmitting(false);
      }
    });
  }

  // ------------------------------
  // 投稿モーダルの表示・非表示
  // ------------------------------
  const openModalBtn = document.getElementById("openPostModal");
  const heroOpenModalBtn = document.getElementById("heroOpenPostModal");
  const postModal = document.getElementById("postModal") as HTMLElement | null;
  const closeModalBtn = document.querySelector("#postModal .close-btn") as HTMLButtonElement | null;
  const promptDetailModal = document.getElementById("promptDetailModal") as HTMLElement | null;
  const closePromptDetailModalBtn = document.getElementById("closePromptDetailModal") as HTMLButtonElement | null;
  const promptShareModal = document.getElementById("promptShareModal") as HTMLElement | null;
  const promptShareCloseBtn = document.getElementById("closePromptShareModal") as HTMLButtonElement | null;
  const promptShareCreateBtn = document.getElementById("prompt-share-create-btn") as HTMLButtonElement | null;
  const promptShareCopyBtn = document.getElementById("prompt-share-copy-btn") as HTMLButtonElement | null;
  const promptShareWebBtn = document.getElementById("prompt-share-web-btn") as HTMLButtonElement | null;
  const postModalTitleInput = document.getElementById("prompt-title") as HTMLInputElement | null;
  const newPromptIcon = openModalBtn ? openModalBtn.querySelector("i") : null;
  let activeModal: HTMLElement | null = null;
  let previouslyFocusedElement: HTMLElement | null = null;
  let lockedScrollY = 0;

  function getModalFocusableElements(modal: HTMLElement) {
    const selector = [
      "a[href]",
      "area[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])"
    ].join(", ");

    return Array.from(modal.querySelectorAll<HTMLElement>(selector)).filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }

  function focusModal(modal: HTMLElement, preferredElement?: HTMLElement | null) {
    const fallbackTarget =
      modal.querySelector<HTMLElement>(".post-modal-content") || (modal as HTMLElement);
    const focusableElements = getModalFocusableElements(modal);
    const target =
      (preferredElement && getModalFocusableElements(modal).includes(preferredElement)
        ? preferredElement
        : null) ||
      focusableElements[0] ||
      fallbackTarget;

    window.requestAnimationFrame(() => {
      target.focus();
    });
  }

  function lockBackgroundInteraction() {
    if (document.body.classList.contains("ps-modal-open")) {
      return;
    }

    lockedScrollY = window.scrollY || window.pageYOffset || 0;
    document.documentElement.classList.add("ps-modal-open");
    document.body.classList.add("ps-modal-open");
    document.body.style.position = "fixed";
    document.body.style.top = `-${lockedScrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
  }

  function unlockBackgroundInteraction() {
    document.documentElement.classList.remove("ps-modal-open");
    document.body.classList.remove("ps-modal-open");
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";
    window.scrollTo(0, lockedScrollY);
  }

  function openModal(modal: HTMLElement, preferredElement?: HTMLElement | null) {
    previouslyFocusedElement = document.activeElement as HTMLElement | null;
    activeModal = modal;
    modal.classList.add("show");
    modal.setAttribute("aria-hidden", "false");
    lockBackgroundInteraction();
    focusModal(modal, preferredElement);
  }

  function closeModal(modal: HTMLElement, options?: { rotateTrigger?: boolean }) {
    if (!modal.classList.contains("show")) {
      return;
    }

    modal.classList.remove("show");
    modal.setAttribute("aria-hidden", "true");
    if (modal === postModal) {
      setPromptPostStatus("", "info");
      setPostSubmitting(false);
      promptAssistController?.reset();
    }
    if (options?.rotateTrigger) {
      triggerNewPromptIconRotation();
    }

    if (activeModal === modal) {
      activeModal = null;
    }

    const hasVisibleModal = Boolean(document.querySelector(".post-modal.show"));
    if (!hasVisibleModal) {
      unlockBackgroundInteraction();
      if (previouslyFocusedElement) {
        previouslyFocusedElement.focus();
      }
      previouslyFocusedElement = null;
    }
  }

  function handleModalKeydown(event: KeyboardEvent) {
    if (!activeModal || !activeModal.classList.contains("show")) {
      return;
    }

    if (event.key === "Escape") {
      if (activeModal === postModal && isPostSubmitting) {
        return;
      }
      event.preventDefault();
      closeModal(activeModal);
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusableElements = getModalFocusableElements(activeModal);
    if (focusableElements.length === 0) {
      event.preventDefault();
      const fallback = activeModal.querySelector<HTMLElement>(".post-modal-content");
      fallback?.focus();
      return;
    }

    const firstFocusable = focusableElements[0];
    const lastFocusable = focusableElements[focusableElements.length - 1];
    const currentElement = document.activeElement as HTMLElement | null;

    if (event.shiftKey) {
      if (!currentElement || currentElement === firstFocusable || !activeModal.contains(currentElement)) {
        event.preventDefault();
        lastFocusable.focus();
      }
      return;
    }

    if (!currentElement || currentElement === lastFocusable || !activeModal.contains(currentElement)) {
      event.preventDefault();
      firstFocusable.focus();
    }
  }

  const triggerNewPromptIconRotation = () => {
    if (!newPromptIcon) {
      return;
    }
    newPromptIcon.classList.remove("rotating");
    void (newPromptIcon as HTMLElement).offsetWidth;
    newPromptIcon.classList.add("rotating");
  };

  if (newPromptIcon) {
    newPromptIcon.addEventListener("animationend", () => {
      newPromptIcon.classList.remove("rotating");
    });
  }

  if (document.body && document.body.dataset.psModalKeydownListener !== "true") {
    document.body.dataset.psModalKeydownListener = "true";
    document.addEventListener("keydown", handleModalKeydown);
  }

  const openComposerModal = () => {
    if (!postModal) return;
    if (!isLoggedIn) {
      alert("プロンプトを投稿するにはログインが必要です。");
      return;
    }

    triggerNewPromptIconRotation();
    setPromptPostStatus("カテゴリやタイトルを軽く入れてから AI 補助を使うと、提案が安定します。");
    openModal(postModal, postModalTitleInput);
  };

  if (openModalBtn && postModal) {
    openModalBtn.addEventListener("click", openComposerModal);
  }

  if (heroOpenModalBtn && postModal) {
    heroOpenModalBtn.addEventListener("click", openComposerModal);
  }

  if (closeModalBtn && postModal) {
    closeModalBtn.addEventListener("click", function () {
      closeModal(postModal, { rotateTrigger: true });
    });
  }

  if (promptShareWebBtn && !navigator.share) {
    promptShareWebBtn.style.display = "none";
  }
  setPromptShareUrl("");
  setPromptShareStatus("共有するプロンプトを選択してください。");

  if (promptShareCreateBtn) {
    promptShareCreateBtn.addEventListener("click", () => {
      void createPromptShareLink(true);
    });
  }

  if (promptShareCopyBtn) {
    promptShareCopyBtn.addEventListener("click", () => {
      void copyPromptShareLink();
    });
  }

  if (promptShareWebBtn) {
    promptShareWebBtn.addEventListener("click", () => {
      void sharePromptWithNativeSheet();
    });
  }

  if (promptShareCloseBtn && promptShareModal) {
    promptShareCloseBtn.addEventListener("click", () => {
      closeModal(promptShareModal);
    });
  }

  if (promptShareModal) {
    promptShareModal.addEventListener("click", (event) => {
      if (event.target === promptShareModal) {
        closeModal(promptShareModal);
      }
    });
  }

  // 投稿モーダルは背景クリックでは閉じない（×ボタンのみ）

  // ------------------------------
  // ガードレールの表示切替処理
  // ------------------------------
  if (guardrailCheckbox && guardrailFields) {
    guardrailCheckbox.addEventListener("change", function () {
      showGuardrailFields(guardrailCheckbox.checked);
    });
  }

  // ------------------------------
  // プロンプト詳細モーダル機能
  // ------------------------------
  function showPromptDetailModal(prompt: PromptData) {
    const modal = document.getElementById("promptDetailModal");
    const modalTitle = document.getElementById("modalPromptTitle");
    const modalPromptType = document.getElementById("modalPromptType");
    const modalCategory = document.getElementById("modalPromptCategory");
    const modalContent = document.getElementById("modalPromptContent");
    const modalAuthor = document.getElementById("modalPromptAuthor");
    const modalInputExamples = document.getElementById("modalInputExamples");
    const modalOutputExamples = document.getElementById("modalOutputExamples");
    const modalInputExamplesGroup = document.getElementById("modalInputExamplesGroup");
    const modalOutputExamplesGroup = document.getElementById("modalOutputExamplesGroup");
    const modalAiModel = document.getElementById("modalAiModel");
    const modalAiModelGroup = document.getElementById("modalAiModelGroup");
    const modalReferenceImage = document.getElementById("modalReferenceImage") as HTMLImageElement | null;
    const modalReferenceImageGroup = document.getElementById("modalReferenceImageGroup");

    if (!modal || !modalTitle || !modalPromptType || !modalCategory || !modalContent || !modalAuthor) return;

    // モーダルにデータを設定
    const promptType = normalizePromptType(prompt.prompt_type);
    modalTitle.textContent = prompt.title;
    modalPromptType.textContent = getPromptTypeLabel(promptType);
    modalCategory.textContent = prompt.category || "";
    modalContent.textContent = prompt.content;
    modalAuthor.textContent = prompt.author || "";

    // 使用AIモデルがある場合のみ表示
    if (prompt.ai_model && modalAiModel && modalAiModelGroup) {
      modalAiModel.textContent = prompt.ai_model;
      modalAiModelGroup.style.display = "block";
    } else if (modalAiModelGroup) {
      modalAiModelGroup.style.display = "none";
    }

    // 入力例・出力例がある場合のみ表示
    if (prompt.input_examples && modalInputExamples && modalInputExamplesGroup) {
      modalInputExamples.textContent = prompt.input_examples;
      modalInputExamplesGroup.style.display = "block";
    } else if (modalInputExamplesGroup) {
      modalInputExamplesGroup.style.display = "none";
    }

    if (prompt.output_examples && modalOutputExamples && modalOutputExamplesGroup) {
      modalOutputExamples.textContent = prompt.output_examples;
      modalOutputExamplesGroup.style.display = "block";
    } else if (modalOutputExamplesGroup) {
      modalOutputExamplesGroup.style.display = "none";
    }

    if (prompt.reference_image_url && modalReferenceImage && modalReferenceImageGroup) {
      modalReferenceImage.src = prompt.reference_image_url;
      modalReferenceImage.alt = `${prompt.title} の作例画像`;
      modalReferenceImageGroup.style.display = "block";
    } else if (modalReferenceImage && modalReferenceImageGroup) {
      modalReferenceImage.src = "";
      modalReferenceImage.alt = "";
      modalReferenceImageGroup.style.display = "none";
    }

    // モーダルを表示
    openModal(modal, closePromptDetailModalBtn);
  }

  // 閉じるボタンでモーダルを閉じる
  if (closePromptDetailModalBtn && promptDetailModal) {
    closePromptDetailModalBtn.addEventListener("click", function () {
      closeModal(promptDetailModal);
    });
  }

  // モーダル背景クリックで閉じる
  if (promptDetailModal) {
    promptDetailModal.addEventListener("click", function (e) {
      if (e.target === promptDetailModal) {
        closeModal(promptDetailModal);
      }
    });
  }

  window.addEventListener("beforeunload", () => {
    revokePromptImagePreview();
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => initPromptSharePage());
} else {
  initPromptSharePage();
}

export {};
