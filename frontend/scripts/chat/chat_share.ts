import { ShareChatRoomResponseSchema } from "../../types/chat";
import { getCurrentChatRoomId } from "../core/app_state";
import { extractApiErrorMessage, readJsonBody } from "../core/runtime_validation";
import { copyTextToClipboard } from "./message_utils";

const SHARE_TITLE = "Chat Core 共有チャット";
const SHARE_TEXT = "このチャットルームを共有しました。";
const cachedShareUrls = new Map<string, string>();
let chatShareInitialized = false;

function getShareModalElements() {
  return {
    shareBtn: document.getElementById("share-chat-btn") as HTMLButtonElement | null,
    modal: document.getElementById("chat-share-modal"),
    closeBtn: document.getElementById("chat-share-close-btn") as HTMLButtonElement | null,
    copyBtn: document.getElementById("chat-share-copy-btn") as HTMLButtonElement | null,
    webShareBtn: document.getElementById("chat-share-web-btn") as HTMLButtonElement | null,
    linkInput: document.getElementById("chat-share-link-input") as HTMLInputElement | null,
    statusEl: document.getElementById("chat-share-status"),
    snsX: document.getElementById("chat-share-sns-x") as HTMLAnchorElement | null,
    snsLine: document.getElementById("chat-share-sns-line") as HTMLAnchorElement | null,
    snsFacebook: document.getElementById("chat-share-sns-facebook") as HTMLAnchorElement | null
  };
}

function setStatus(message: string, isError = false) {
  const { statusEl } = getShareModalElements();
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("chat-share-status--error", isError);
}

function updateSnsLinks(shareUrl: string) {
  const { snsX, snsLine, snsFacebook } = getShareModalElements();
  const encodedUrl = encodeURIComponent(shareUrl);
  const encodedText = encodeURIComponent(SHARE_TEXT);

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

function setShareUrl(shareUrl: string) {
  const { linkInput } = getShareModalElements();
  if (!linkInput) return;
  linkInput.value = shareUrl;
  updateSnsLinks(shareUrl);
}

function openChatShareModal() {
  const { modal } = getShareModalElements();
  if (!modal) return;
  modal.style.display = "flex";
  modal.setAttribute("aria-hidden", "false");
}

function closeChatShareModal() {
  const { modal } = getShareModalElements();
  if (!modal) return;
  modal.style.display = "none";
  modal.setAttribute("aria-hidden", "true");
}

function setShareActionLoading(isLoading: boolean) {
  const { copyBtn, webShareBtn } = getShareModalElements();
  if (copyBtn) copyBtn.disabled = isLoading;
  if (webShareBtn) webShareBtn.disabled = isLoading;
}

async function createShareLink(forceRefresh = false) {
  const roomId = getCurrentChatRoomId();
  if (!roomId) {
    setStatus("共有するチャットルームを選択してください。", true);
    setShareUrl("");
    return;
  }

  if (!forceRefresh && cachedShareUrls.has(roomId)) {
    const shareUrl = cachedShareUrls.get(roomId) || "";
    setShareUrl(shareUrl);
    setStatus("共有リンクを表示しています。");
    return;
  }

  setShareActionLoading(true);
  setStatus("共有リンクを生成しています...");

  try {
    const response = await fetch("/api/share_chat_room", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ room_id: roomId })
    });
    const rawPayload = await readJsonBody(response).catch(() => ({}));
    const parsed = ShareChatRoomResponseSchema.safeParse(rawPayload);
    const data = parsed.success ? parsed.data : null;

    if (!response.ok || !data || typeof data.share_url !== "string" || data.share_url.length === 0) {
      throw new Error(extractApiErrorMessage(rawPayload, "共有リンクの作成に失敗しました。", response.status));
    }

    cachedShareUrls.set(roomId, data.share_url);
    setShareUrl(data.share_url);
    setStatus("共有リンクを作成しました。");
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    setStatus(errorMessage, true);
  } finally {
    setShareActionLoading(false);
  }
}

async function copyShareLink() {
  const { linkInput } = getShareModalElements();
  const shareUrl = linkInput?.value.trim() || "";
  if (!shareUrl) {
    setStatus("先に共有リンクを生成してください。", true);
    return;
  }

  try {
    await copyTextToClipboard(shareUrl);
    setStatus("リンクをコピーしました。");
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    setStatus(errorMessage, true);
  }
}

async function shareWithNativeSheet() {
  const { linkInput } = getShareModalElements();
  const shareUrl = linkInput?.value.trim() || "";
  if (!shareUrl) {
    setStatus("先に共有リンクを生成してください。", true);
    return;
  }
  if (!navigator.share) {
    setStatus("このブラウザはネイティブ共有に対応していません。", true);
    return;
  }

  try {
    await navigator.share({
      title: SHARE_TITLE,
      text: SHARE_TEXT,
      url: shareUrl
    });
    setStatus("共有シートを開きました。");
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") return;
    const errorMessage = error instanceof Error ? error.message : String(error);
    setStatus(errorMessage, true);
  }
}

function refreshChatShareState() {
  const { shareBtn } = getShareModalElements();
  if (!shareBtn) return;

  const hasRoom = Boolean(getCurrentChatRoomId());
  shareBtn.disabled = !hasRoom;
  shareBtn.classList.toggle("chat-share-btn--disabled", !hasRoom);
  shareBtn.setAttribute("aria-disabled", hasRoom ? "false" : "true");
}

function initChatShare() {
  if (chatShareInitialized) return;
  chatShareInitialized = true;

  const {
    shareBtn,
    modal,
    closeBtn,
    copyBtn,
    webShareBtn
  } = getShareModalElements();
  if (!shareBtn || !modal) return;

  refreshChatShareState();
  setShareUrl("");
  setStatus("共有するチャットルームを選択してください。");

  if (webShareBtn && !navigator.share) {
    webShareBtn.style.display = "none";
  }

  shareBtn.addEventListener("click", () => {
    openChatShareModal();
    void createShareLink(false);
  });

  closeBtn?.addEventListener("click", closeChatShareModal);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeChatShareModal();
    }
  });

  copyBtn?.addEventListener("click", () => {
    void copyShareLink();
  });
  webShareBtn?.addEventListener("click", () => {
    void shareWithNativeSheet();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modal.style.display === "none") return;
    closeChatShareModal();
  });
}

export { initChatShare, refreshChatShareState, closeChatShareModal };
