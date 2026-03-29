import { setLoggedInState } from "../core/app_state";
import { formatLLMOutput } from "../chat/chat_ui";
import { copyTextToClipboard, renderSanitizedHTML } from "../chat/message_utils";
import { fetchJsonOrThrow } from "../core/runtime_validation";

const MEMO_SHARE_TITLE = "Chat Core 共有メモ";
const MEMO_SHARE_TEXT = "このメモを共有しました。";

const setupMemoModal = () => {
  const modal = document.getElementById("memoModal") as HTMLElement | null;
  const shareModal = document.getElementById("memoShareModal") as HTMLElement | null;
  if (!modal) {
    return;
  }

  const authButtons = document.getElementById("auth-buttons");
  const userIcon = document.getElementById("userIcon");
  const loginBtn = document.getElementById("login-btn");
  const closeTargets = modal.querySelectorAll("[data-close-modal]");
  const shareCloseTargets = shareModal?.querySelectorAll("[data-close-share-modal]") || [];
  const titleEl = modal.querySelector("[data-modal-title]");
  const dateEl = modal.querySelector("[data-modal-date]");
  const tagsEl = modal.querySelector("[data-modal-tags]");
  const inputEl = modal.querySelector("[data-modal-input]");
  const responseEl = modal.querySelector("[data-modal-response]");
  const shareLinkInput = document.getElementById("memo-share-link-input") as HTMLInputElement | null;
  const shareStatusEl = document.getElementById("memo-share-status");
  const shareCopyBtn = document.getElementById("memo-share-copy-btn") as HTMLButtonElement | null;
  const shareWebBtn = document.getElementById("memo-share-web-btn") as HTMLButtonElement | null;
  const shareSnsX = document.getElementById("memo-share-sns-x") as HTMLAnchorElement | null;
  const shareSnsLine = document.getElementById("memo-share-sns-line") as HTMLAnchorElement | null;
  const shareSnsFacebook = document.getElementById("memo-share-sns-facebook") as HTMLAnchorElement | null;
  const cachedShareUrls = new Map<string, string>();
  let currentShareMemoId = "";

  const notifyAuthState = (loggedIn: boolean) => {
    setLoggedInState(loggedIn);
  };

  const applyAuthUI = (loggedIn: boolean) => {
    if (authButtons) {
      authButtons.style.display = loggedIn ? "none" : "";
    }
    if (userIcon) {
      userIcon.style.display = loggedIn ? "" : "none";
    }
    if (!loggedIn && loginBtn) {
      loginBtn.onclick = () => {
        window.location.href = "/login";
      };
    }
  };

  const syncBodyModalOpen = () => {
    const isVisible =
      modal.classList.contains("is-visible") || Boolean(shareModal?.classList.contains("is-visible"));
    document.body.classList.toggle("modal-open", isVisible);
  };

  fetch("/api/current_user")
    .then((res) => {
      if (!res.ok) {
        return { logged_in: false };
      }
      return res.json();
    })
    .then((data) => {
      const loggedIn = Boolean(data.logged_in);
      notifyAuthState(loggedIn);
      applyAuthUI(loggedIn);
    })
    .catch(() => {
      notifyAuthState(false);
      applyAuthUI(false);
    });

  const clearModal = () => {
    if (titleEl) titleEl.textContent = "保存したメモ";
    if (dateEl) dateEl.textContent = "";
    if (tagsEl) tagsEl.innerHTML = "";
    if (inputEl) inputEl.innerHTML = "";
    if (responseEl) responseEl.innerHTML = "";
  };

  const renderTags = (tags: string[]) => {
    if (!tagsEl) return;
    tagsEl.innerHTML = "";
    if (!tags || tags.length === 0) {
      const emptyTag = document.createElement("span");
      emptyTag.className = "memo-tag memo-tag--muted";
      emptyTag.textContent = "タグなし";
      tagsEl.appendChild(emptyTag);
      return;
    }

    tags.forEach((tag) => {
      if (!tag) return;
      const chip = document.createElement("span");
      chip.className = "memo-tag";
      chip.textContent = tag;
      tagsEl.appendChild(chip);
    });
  };

  const openModal = (memo: {
    title?: string;
    date?: string;
    tags?: string[];
    input?: string;
    response?: string;
  }) => {
    clearModal();
    if (titleEl) titleEl.textContent = memo.title || "保存したメモ";
    if (dateEl) dateEl.textContent = memo.date || "";
    renderTags(memo.tags || []);
    const renderContent = (el: Element, text: string) => {
      renderSanitizedHTML(el as HTMLElement, formatLLMOutput(text));
    };
    if (inputEl) renderContent(inputEl, memo.input || "");
    if (responseEl) renderContent(responseEl, memo.response || "");
    modal.classList.add("is-visible");
    syncBodyModalOpen();
  };

  const closeModal = () => {
    modal.classList.remove("is-visible");
    syncBodyModalOpen();
    setTimeout(clearModal, 200);
  };

  const setShareStatus = (message: string, isError = false) => {
    if (!shareStatusEl) return;
    shareStatusEl.textContent = message;
    shareStatusEl.classList.toggle("memo-share-modal__status--error", isError);
  };

  const updateShareSnsLinks = (shareUrl: string) => {
    const encodedUrl = encodeURIComponent(shareUrl);
    const encodedText = encodeURIComponent(MEMO_SHARE_TEXT);
    if (shareSnsX) {
      shareSnsX.href = `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
    }
    if (shareSnsLine) {
      shareSnsLine.href = `https://social-plugins.line.me/lineit/share?url=${encodedUrl}`;
    }
    if (shareSnsFacebook) {
      shareSnsFacebook.href = `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`;
    }
  };

  const setShareUrl = (shareUrl: string) => {
    if (!shareLinkInput) return;
    shareLinkInput.value = shareUrl;
    updateShareSnsLinks(shareUrl);
  };

  const setShareActionLoading = (isLoading: boolean) => {
    if (shareCopyBtn) shareCopyBtn.disabled = isLoading;
    if (shareWebBtn) shareWebBtn.disabled = isLoading;
  };

  const openShareModal = (memoId: string) => {
    if (!shareModal) return;
    currentShareMemoId = memoId;
    shareModal.classList.add("is-visible");
    syncBodyModalOpen();
  };

  const closeShareModal = () => {
    if (!shareModal) return;
    shareModal.classList.remove("is-visible");
    syncBodyModalOpen();
  };

  const createShareLink = async (forceRefresh = false) => {
    if (!currentShareMemoId) {
      setShareUrl("");
      setShareStatus("共有するメモを選択してください。", true);
      return;
    }

    if (!forceRefresh && cachedShareUrls.has(currentShareMemoId)) {
      setShareUrl(cachedShareUrls.get(currentShareMemoId) || "");
      setShareStatus("共有リンクを表示しています。");
      return;
    }

    setShareActionLoading(true);
    setShareStatus("共有リンクを生成しています...");

    try {
      const { payload: data } = await fetchJsonOrThrow<Record<string, unknown>>(
        "/memo/api/share",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ memo_id: Number(currentShareMemoId) })
        },
        {
          defaultMessage: "共有リンクの作成に失敗しました。",
          hasApplicationError: (payload) => typeof payload.share_url !== "string" || !payload.share_url.trim()
        }
      );
      const shareUrl = typeof data.share_url === "string" ? data.share_url : "";

      cachedShareUrls.set(currentShareMemoId, shareUrl);
      setShareUrl(shareUrl);
      setShareStatus("共有リンクを作成しました。");
    } catch (error) {
      setShareStatus(error instanceof Error ? error.message : String(error), true);
    } finally {
      setShareActionLoading(false);
    }
  };

  const copyShareLink = async () => {
    const shareUrl = shareLinkInput?.value.trim() || "";
    if (!shareUrl) {
      setShareStatus("先に共有リンクを生成してください。", true);
      return;
    }

    try {
      await copyTextToClipboard(shareUrl);
      setShareStatus("リンクをコピーしました。");
    } catch (error) {
      setShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  };

  const shareWithNativeSheet = async () => {
    const shareUrl = shareLinkInput?.value.trim() || "";
    if (!shareUrl) {
      setShareStatus("先に共有リンクを生成してください。", true);
      return;
    }
    if (!navigator.share) {
      setShareStatus("このブラウザはネイティブ共有に対応していません。", true);
      return;
    }

    try {
      await navigator.share({
        title: MEMO_SHARE_TITLE,
        text: MEMO_SHARE_TEXT,
        url: shareUrl
      });
      setShareStatus("共有シートを開きました。");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setShareStatus(error instanceof Error ? error.message : String(error), true);
    }
  };

  setShareUrl("");
  setShareStatus("共有するメモを選択してください。");

  if (shareWebBtn && !navigator.share) {
    shareWebBtn.style.display = "none";
  }

  closeTargets.forEach((trigger) => {
    trigger.addEventListener("click", closeModal);
  });

  shareCloseTargets.forEach((trigger) => {
    trigger.addEventListener("click", closeShareModal);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (shareModal?.classList.contains("is-visible")) {
      closeShareModal();
      return;
    }
    if (modal.classList.contains("is-visible")) {
      closeModal();
    }
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  shareModal?.addEventListener("click", (event) => {
    if (event.target === shareModal) {
      closeShareModal();
    }
  });

  shareCopyBtn?.addEventListener("click", () => {
    void copyShareLink();
  });

  shareWebBtn?.addEventListener("click", () => {
    void shareWithNativeSheet();
  });

  const parseMemoText = (raw: string | undefined) => {
    if (!raw) return "";
    try {
      const parsed = JSON.parse(raw);
      return typeof parsed === "string" ? parsed : "";
    } catch {
      return raw;
    }
  };

  const openMemoDetail = (item: HTMLElement) => {
    const input = parseMemoText(item.dataset.input);
    const response = parseMemoText(item.dataset.response);
    const tagString = item.dataset.tags || "";
    const tags = tagString
      .split(/\s+/)
      .map((tag) => tag.trim())
      .filter(Boolean);

    openModal({
      title: item.dataset.title || "保存したメモ",
      date: item.dataset.date || "",
      tags,
      input,
      response
    });
  };

  document.addEventListener("click", (event) => {
    const target = event.target as HTMLElement | null;
    if (!target) return;

    const shareButton = target.closest<HTMLElement>("[data-share-memo]");
    if (shareButton) {
      event.stopPropagation();
      const memoItem = shareButton.closest<HTMLElement>(".memo-item");
      const memoId = memoItem?.dataset.memoId || "";
      if (!memoId) {
        setShareStatus("共有対象のメモが見つかりません。", true);
        return;
      }
      openShareModal(memoId);
      void createShareLink(false);
      return;
    }

    const memoItem = target.closest<HTMLElement>(".memo-item");
    if (!memoItem) return;
    openMemoDetail(memoItem);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.closest("[data-share-memo]")) return;
    const memoItem = target.closest<HTMLElement>(".memo-item");
    if (!memoItem) return;
    event.preventDefault();
    openMemoDetail(memoItem);
  });

  const formatExcerptPreviews = () => {
    const excerptEls = document.querySelectorAll<HTMLElement>(".memo-item__excerpt");
    excerptEls.forEach((el) => {
      if (el.dataset.mdFormatted === "1") return;
      const text = el.textContent || "";
      if (text) {
        renderSanitizedHTML(el, formatLLMOutput(text));
      }
      el.dataset.mdFormatted = "1";
    });
  };

  formatExcerptPreviews();
  const memoHistoryList = document.querySelector<HTMLElement>(".memo-history__list");
  if (memoHistoryList && "MutationObserver" in window) {
    const observer = new MutationObserver(() => {
      formatExcerptPreviews();
    });
    observer.observe(memoHistoryList, { childList: true, subtree: true });
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", setupMemoModal);
} else {
  setupMemoModal();
}

export {};
