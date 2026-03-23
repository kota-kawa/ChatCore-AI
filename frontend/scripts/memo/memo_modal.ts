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
    window.loggedIn = loggedIn;
    document.dispatchEvent(
      new CustomEvent("authstatechange", {
        detail: { loggedIn }
      })
    );
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
      if (window.renderSanitizedHTML && window.formatLLMOutput) {
        window.renderSanitizedHTML(el as HTMLElement, window.formatLLMOutput(text));
      } else {
        el.textContent = text;
      }
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
      const response = await fetch("/memo/api/share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ memo_id: Number(currentShareMemoId) })
      });
      const data = await response.json().catch(() => ({} as Record<string, unknown>));
      const shareUrl = typeof data.share_url === "string" ? data.share_url : "";
      const errorText =
        typeof data.error === "string"
          ? data.error
          : typeof data.message === "string"
            ? data.message
            : `共有リンクの作成に失敗しました (${response.status})`;

      if (!response.ok || !shareUrl) {
        throw new Error(errorText);
      }

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
      if (window.copyTextToClipboard) {
        await window.copyTextToClipboard(shareUrl);
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        throw new Error("このブラウザではコピー機能が利用できません。");
      }
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

  const memoItems = document.querySelectorAll<HTMLElement>(".memo-item");
  memoItems.forEach((item) => {
    const openMemoDetail = () => {
      const input = item.dataset.input ? JSON.parse(item.dataset.input) : "";
      const response = item.dataset.response ? JSON.parse(item.dataset.response) : "";
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

    item.addEventListener("click", openMemoDetail);
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if ((event.target as HTMLElement | null)?.closest("[data-share-memo]")) return;
      event.preventDefault();
      openMemoDetail();
    });

    const shareButton = item.querySelector<HTMLButtonElement>("[data-share-memo]");
    shareButton?.addEventListener("click", (event) => {
      event.stopPropagation();
      const memoId = item.dataset.memoId || "";
      if (!memoId) {
        setShareStatus("共有対象のメモが見つかりません。", true);
        return;
      }
      openShareModal(memoId);
      void createShareLink(false);
    });
  });

  // Apply Markdown formatting to excerpt previews in the memo list
  const excerptEls = document.querySelectorAll<HTMLElement>(".memo-item__excerpt");
  excerptEls.forEach((el) => {
    const text = el.textContent || "";
    if (!text) return;
    if (window.renderSanitizedHTML && window.formatLLMOutput) {
      window.renderSanitizedHTML(el, window.formatLLMOutput(text));
    }
  });
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", setupMemoModal);
} else {
  setupMemoModal();
}

export {};
