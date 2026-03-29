import { PROMPT_SHARE_TEXT, PROMPT_SHARE_TITLE } from "./constants";
import { copyTextToClipboard } from "../chat/message_utils";
import type { PromptData } from "./types";

type PromptShareModalElements = {
  modal: HTMLElement | null;
  closeBtn: HTMLButtonElement | null;
  copyBtn: HTMLButtonElement | null;
  webShareBtn: HTMLButtonElement | null;
  linkInput: HTMLInputElement | null;
  statusEl: HTMLElement | null;
  snsX: HTMLAnchorElement | null;
  snsLine: HTMLAnchorElement | null;
  snsFacebook: HTMLAnchorElement | null;
};

type InitPromptShareDialogOptions = {
  openModal: (modal: HTMLElement, preferredElement?: HTMLElement | null) => void;
  closeModal: (modal: HTMLElement) => void;
};

export function initPromptShareDialog(options: InitPromptShareDialogOptions) {
  const { openModal, closeModal } = options;
  const cachedPromptShareUrls = new Map<string, string>();
  let currentSharePrompt: PromptData | null = null;

  function getPromptShareKey(prompt: PromptData | null) {
    if (!prompt) return "";
    if (prompt.id === undefined || prompt.id === null) return "";
    return String(prompt.id);
  }

  function getPromptShareModalElements(): PromptShareModalElements {
    return {
      modal: document.getElementById("promptShareModal") as HTMLElement | null,
      closeBtn: document.getElementById("closePromptShareModal") as HTMLButtonElement | null,
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
    const { copyBtn, webShareBtn } = getPromptShareModalElements();
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
      await copyTextToClipboard(shareUrl);
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

  function openPromptShareDialog(prompt: PromptData, event?: Event) {
    event?.stopPropagation();
    currentSharePrompt = prompt;
    const { modal, copyBtn } = getPromptShareModalElements();
    if (modal) {
      openModal(modal, copyBtn);
    }
    void createPromptShareLink(false);
  }

  const {
    modal: promptShareModal,
    closeBtn: promptShareCloseBtn,
    copyBtn: promptShareCopyBtn,
    webShareBtn: promptShareWebBtn
  } = getPromptShareModalElements();

  if (promptShareWebBtn && !navigator.share) {
    promptShareWebBtn.style.display = "none";
  }
  setPromptShareUrl("");
  setPromptShareStatus("共有するプロンプトを選択してください。");

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

  return {
    openPromptShareDialog
  };
}
