// chat_messages.ts – メッセージ描画／コピー／ボット表示
// --------------------------------------------------
// ※ DOMPurify が未ロードでも message_utils 側でテキスト描画にフォールバックする
import { getSharedDomRefs } from "../core/dom";
import { saveMessageToLocalStorage } from "./chat_history";
import { formatLLMOutput } from "./chat_ui";
import {
  createCopyBtn,
  createMemoSaveBtn,
  isChatViewportNearBottom,
  renderSanitizedHTML,
  scrollMessageToBottom,
  setTextWithLineBreaks
} from "./message_utils";

type StreamingBotMessageHandle = {
  appendChunk: (chunk: string) => void;
  complete: () => void;
  showError: (message: string) => void;
};

type DisplayMessageOptions = {
  prepend?: boolean;
  autoScroll?: boolean;
};

const STICKY_SCROLL_BOTTOM_THRESHOLD_PX = 72;

function isScrollViewportNearBottom(container: HTMLElement, thresholdPx = STICKY_SCROLL_BOTTOM_THRESHOLD_PX) {
  const distanceToBottom = container.scrollHeight - (container.scrollTop + container.clientHeight);
  return distanceToBottom <= thresholdPx;
}

function getShouldStickToBottom(container: HTMLElement) {
  return isChatViewportNearBottom(STICKY_SCROLL_BOTTOM_THRESHOLD_PX) || isScrollViewportNearBottom(container);
}

function createBotMessageElements(options: { scrollToBottom?: boolean } = {}) {
  const { scrollToBottom = true } = options;
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return null;
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper bot-message-wrapper";

  const msg = document.createElement("div");
  msg.className = "bot-message";

  const actionGroup = document.createElement("div");
  actionGroup.className = "message-actions";

  const copyBtn = createCopyBtn(() => msg.dataset.fullText || "");
  copyBtn.classList.add("message-action-btn");

  const saveBtn = createMemoSaveBtn(() => msg.dataset.fullText || "");
  saveBtn.classList.add("message-action-btn");

  actionGroup.append(copyBtn, saveBtn);
  wrapper.append(msg, actionGroup);
  chatMessages.appendChild(wrapper);
  if (scrollToBottom) {
    scrollMessageToBottom();
  }

  return { wrapper, msg };
}

function renderBotMessageContent(target: HTMLElement, raw: string) {
  renderSanitizedHTML(target, formatLLMOutput(raw));
}

function renderBotMessage(
  wrapper: HTMLElement,
  msg: HTMLElement,
  raw: string,
  options: { scrollToBottom?: boolean } = {}
) {
  const { scrollToBottom = true } = options;
  renderBotMessageContent(msg, raw);
  if (scrollToBottom) {
    scrollMessageToBottom();
  }
}

////////////////////////////////////////////////////////////////////////////////
// メッセージ描画
////////////////////////////////////////////////////////////////////////////////

/* ユーザーメッセージを即時描画 */
function renderUserMessage(text: string) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return;
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper user-message-wrapper";

  const msg = document.createElement("div");
  msg.className = "user-message";

  // テキスト → <br> 置換後、<br> だけ許可してサニタイズ描画
  const htmlText = text.replace(/\n/g, "<br>");
  renderSanitizedHTML(msg, htmlText, ["br"]);
  msg.style.animation = "floatUp 0.5s ease-out";

  const copyBtn = createCopyBtn(() => text);
  copyBtn.classList.add("message-action-btn");
  const actionGroup = document.createElement("div");
  actionGroup.className = "message-actions";

  actionGroup.append(copyBtn);
  wrapper.append(msg, actionGroup);
  chatMessages.appendChild(wrapper);
  scrollMessageToBottom();

  // ローカル保存は <br> 付き HTML で互換維持
  saveMessageToLocalStorage(htmlText, "user");
}

/* Bot メッセージを即時描画 */
function renderBotMessageImmediate(text: string) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return;
  const shouldStickToBottom = getShouldStickToBottom(chatMessages);
  const elements = createBotMessageElements({ scrollToBottom: shouldStickToBottom });
  if (!elements) return;
  const { wrapper, msg } = elements;
  msg.dataset.fullText = text;
  renderBotMessage(wrapper, msg, text, { scrollToBottom: shouldStickToBottom });
  saveMessageToLocalStorage(text, "bot");
}

function startStreamingBotMessage(): StreamingBotMessageHandle | null {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return null;
  const scrollContainer = chatMessages;
  const shouldStickToBottomAtStart = getShouldStickToBottom(scrollContainer);
  const elements = createBotMessageElements({ scrollToBottom: shouldStickToBottomAtStart });
  if (!elements) return null;
  const { wrapper, msg } = elements;
  wrapper.classList.add("message-wrapper--streaming");
  msg.classList.add("bot-message--streaming");
  const formattedContent = document.createElement("div");
  formattedContent.className = "bot-message__formatted-stream";
  const streamTail = document.createElement("span");
  streamTail.className = "bot-message__stream-tail";
  msg.append(formattedContent, streamTail);

  let receivedRaw = "";
  let displayedRaw = "";
  let formattedRaw = "";
  let animationFrameId: number | null = null;
  let shouldForceMarkdownFlush = false;
  let lastMarkdownRenderAt = 0;
  let lastTypingFrameAt: number | null = null;
  let lastChunkReceivedAt: number | null = null;
  let typingCharsPerMs = 0.042;
  let isProgrammaticScroll = false;
  let shouldStickToBottom = shouldStickToBottomAtStart;
  let lastObservedScrollTop = scrollContainer.scrollTop;
  let isCompleted = false;
  let isFinalized = false;

  // Scroll-to-bottom ボタン (ユーザーが上へスクロールした時に表示)
  let scrollToBottomBtn: HTMLButtonElement | null = null;
  const chatArea = scrollContainer.closest(".chat-area");
  if (chatArea) {
    chatArea.querySelector(".scroll-to-bottom-btn")?.remove();
    scrollToBottomBtn = document.createElement("button");
    scrollToBottomBtn.type = "button";
    scrollToBottomBtn.className = "scroll-to-bottom-btn scroll-to-bottom-btn--hidden";
    scrollToBottomBtn.setAttribute("aria-label", "最下部へスクロール");
    scrollToBottomBtn.innerHTML = '<i class="bi bi-chevron-down"></i>';
    chatArea.appendChild(scrollToBottomBtn);

    scrollToBottomBtn.addEventListener("click", () => {
      shouldStickToBottom = true;
      isProgrammaticScroll = true;
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
      lastObservedScrollTop = scrollContainer.scrollTop;
      isProgrammaticScroll = false;
      updateScrollToBottomVisibility();
    });
  }

  const updateScrollToBottomVisibility = () => {
    if (!scrollToBottomBtn) return;
    if (shouldStickToBottom) {
      scrollToBottomBtn.classList.add("scroll-to-bottom-btn--hidden");
    } else {
      scrollToBottomBtn.classList.remove("scroll-to-bottom-btn--hidden");
    }
  };

  // 初期状態: ボトムにいなければボタンを表示
  if (!shouldStickToBottom) updateScrollToBottomVisibility();

  const markdownRefreshCharInterval = 30;
  const markdownRefreshMaxDelayMs = 120;
  const minTypingCharsPerMs = 0.016;
  const maxTypingCharsPerMs = 0.22;
  const typingRateSmoothing = 0.28;
  const backlogSpeedupDivisor = 80;
  const maxBacklogSpeedup = 4;

  const handleScroll = () => {
    if (isProgrammaticScroll) return;
    const currentScrollTop = scrollContainer.scrollTop;
    const didUserScrollUp = currentScrollTop < lastObservedScrollTop;
    shouldStickToBottom = didUserScrollUp ? false : getShouldStickToBottom(scrollContainer);
    lastObservedScrollTop = currentScrollTop;
    updateScrollToBottomVisibility();
  };

  scrollContainer.addEventListener("scroll", handleScroll, { passive: true });

  const scrollStreamingViewport = () => {
    if (!shouldStickToBottom) return;

    isProgrammaticScroll = true;
    scrollContainer.scrollTop = scrollContainer.scrollHeight;
    lastObservedScrollTop = scrollContainer.scrollTop;
    isProgrammaticScroll = false;
  };

  const refreshStreamingMarkdown = (force = false) => {
    const pendingMarkdownChars = displayedRaw.length - formattedRaw.length;
    if (pendingMarkdownChars <= 0) return false;

    const now = performance.now();
    const shouldFlush = force
      || pendingMarkdownChars >= markdownRefreshCharInterval
      || displayedRaw.endsWith("\n")
      || displayedRaw.endsWith("。")
      || displayedRaw.endsWith(".")
      || now - lastMarkdownRenderAt >= markdownRefreshMaxDelayMs;

    if (!shouldFlush) return false;

    const nextFormattedRaw = displayedRaw;
    renderBotMessageContent(formattedContent, nextFormattedRaw);
    formattedRaw = nextFormattedRaw;
    lastMarkdownRenderAt = now;
    return true;
  };

  const clamp = (value: number, min: number, max: number) => {
    if (value < min) return min;
    if (value > max) return max;
    return value;
  };

  const updateTypingRateFromChunk = (chunkText: string) => {
    const chunkLength = chunkText.length;
    if (chunkLength <= 0) return;

    const now = performance.now();
    if (lastChunkReceivedAt !== null) {
      const elapsedMs = Math.max(16, now - lastChunkReceivedAt);
      const observedCharsPerMs = chunkLength / elapsedMs;
      typingCharsPerMs = clamp(
        typingCharsPerMs * (1 - typingRateSmoothing) + observedCharsPerMs * typingRateSmoothing,
        minTypingCharsPerMs,
        maxTypingCharsPerMs
      );
    }
    lastChunkReceivedAt = now;
  };

  const advanceDisplayedText = (frameNow: number, forceAll = false) => {
    const pendingChars = receivedRaw.length - displayedRaw.length;
    if (pendingChars <= 0) {
      lastTypingFrameAt = frameNow;
      return 0;
    }

    if (forceAll) {
      displayedRaw = receivedRaw;
      lastTypingFrameAt = frameNow;
      return 0;
    }

    const previousFrameAt = lastTypingFrameAt ?? frameNow - 16;
    const elapsedMs = clamp(frameNow - previousFrameAt, 16, 120);
    lastTypingFrameAt = frameNow;

    const speedup = Math.min(maxBacklogSpeedup, 1 + pendingChars / backlogSpeedupDivisor);
    const charsToAdvance = Math.max(1, Math.floor(elapsedMs * typingCharsPerMs * speedup));
    displayedRaw = receivedRaw.slice(0, displayedRaw.length + Math.min(pendingChars, charsToAdvance));
    return receivedRaw.length - displayedRaw.length;
  };

  const renderStreamingText = (frameNow: number, forceMarkdown = false, forceAllChars = false) => {
    const remainingChars = advanceDisplayedText(frameNow, forceAllChars);
    const refreshedMarkdown = refreshStreamingMarkdown(forceMarkdown);
    streamTail.textContent = displayedRaw.slice(formattedRaw.length);
    msg.dataset.fullText = displayedRaw;
    scrollStreamingViewport();
    return remainingChars;
  };

  const finalizeMessage = () => {
    if (isFinalized) return;
    isFinalized = true;
    scrollContainer.removeEventListener("scroll", handleScroll);
    scrollToBottomBtn?.remove();
    scrollToBottomBtn = null;

    if (animationFrameId !== null) {
      window.cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }

    wrapper.classList.remove("message-wrapper--streaming");
    msg.classList.remove("bot-message--streaming");
    msg.dataset.fullText = receivedRaw;
    renderBotMessage(wrapper, msg, receivedRaw, { scrollToBottom: shouldStickToBottom });
    saveMessageToLocalStorage(receivedRaw, "bot");
  };

  const scheduleAnimation = () => {
    if (animationFrameId !== null || isFinalized) return;
    animationFrameId = window.requestAnimationFrame((frameNow) => {
      animationFrameId = null;
      const forceAllChars = isCompleted;
      const remainingChars = renderStreamingText(frameNow, shouldForceMarkdownFlush, forceAllChars);
      shouldForceMarkdownFlush = false;

      if (isCompleted) {
        finalizeMessage();
        return;
      }

      if (remainingChars > 0) {
        scheduleAnimation();
      }
    });
  };

  return {
    appendChunk(chunkText: string) {
      if (!chunkText || isCompleted) return;
      receivedRaw += chunkText;
      updateTypingRateFromChunk(chunkText);
      shouldForceMarkdownFlush = false;
      scheduleAnimation();
    },
    complete() {
      if (isCompleted) return;
      isCompleted = true;
      shouldForceMarkdownFlush = true;
      scheduleAnimation();
    },
    showError(message: string) {
      if (!message) return;
      receivedRaw = receivedRaw ? `${receivedRaw}\n\nエラー: ${message}` : `エラー: ${message}`;
      isCompleted = true;
      shouldForceMarkdownFlush = true;
      scheduleAnimation();
    }
  };
}

/* ローカル／サーバ履歴共通描画 */
function buildHistoryMessageElement(text: string, sender: string) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return;
  const wrapper = document.createElement("div");
  const copyBtn = createCopyBtn(() => text);

  if (sender === "user") {
    wrapper.className = "message-wrapper user-message-wrapper";
    const msg = document.createElement("div");
    msg.className = "user-message";
    const actionGroup = document.createElement("div");
    actionGroup.className = "message-actions";
    copyBtn.classList.add("message-action-btn");

    // 既存履歴は <br> が含まれているため、<br> だけ許可して描画
    if (text.includes("<")) {
      renderSanitizedHTML(msg, text, ["br"]);
    } else {
      setTextWithLineBreaks(msg, text);
    }

    actionGroup.append(copyBtn);
    wrapper.append(msg, actionGroup);
  } else {
    wrapper.className = "message-wrapper bot-message-wrapper";
    const msg = document.createElement("div");
    msg.className = "bot-message";
    msg.dataset.fullText = text;
    const actionGroup = document.createElement("div");
    actionGroup.className = "message-actions";
    const saveBtn = createMemoSaveBtn(() => msg.dataset.fullText || "");
    copyBtn.classList.add("message-action-btn");
    saveBtn.classList.add("message-action-btn");

    // Bot はマークアップ済み → 広めのタグ許可でサニタイズ
    renderSanitizedHTML(msg, formatLLMOutput(text));
    actionGroup.append(copyBtn, saveBtn);
    wrapper.append(msg, actionGroup);
  }
  return wrapper;
}

function displayMessage(text: string, sender: string, options: DisplayMessageOptions = {}) {
  const { chatMessages } = getSharedDomRefs();
  if (!chatMessages) return;

  const wrapper = buildHistoryMessageElement(text, sender);
  if (!wrapper) return;

  const { prepend = false, autoScroll = true } = options;
  if (prepend) {
    chatMessages.insertBefore(wrapper, chatMessages.firstChild);
  } else {
    chatMessages.appendChild(wrapper);
  }

  if (!autoScroll) return;
  scrollMessageToBottom();
}

export { renderUserMessage, renderBotMessageImmediate, startStreamingBotMessage, displayMessage };
