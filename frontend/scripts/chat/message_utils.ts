// message_utils.ts – 共通メッセージユーティリティ
// --------------------------------------------------
import { getSharedDomRefs } from "../core/dom";
import { sanitizeClassAttributeValue } from "../core/html";
import { extractApiErrorMessage, readJsonBodySafe } from "../core/runtime_validation";
import { MemoSaveResponseSchema } from "../../types/generated/api_schemas";

// DOMPurify が利用可能な場合は使用し、未ロード時は安全なテキスト描画にフォールバック

/**
 * HTML をサニタイズして挿入する
 * @param element   挿入先
 * @param dirtyHtml サニタイズ前 HTML
 * @param allowed   許可タグ（省略時はデフォルト）
 */
function compactBotMessageHtml(html: string) {
  return html
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/(?:<br\s*\/?>\s*){3,}/gi, "<br><br>")
    .replace(/<p>(?:\s|&nbsp;|&#160;|&#xA0;|&#8203;|&#x200b;|<br\s*\/?>)*<\/p>/gi, "")
    .replace(/(<\/(?:p|ul|ol|pre|blockquote|table|h[1-6])>\s*)(?:<br\s*\/?>\s*)+/gi, "$1")
    .replace(/(?:<br\s*\/?>\s*)+(<(?:p|ul|ol|pre|blockquote|table|h[1-6]|hr)\b)/gi, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isSafeUrl(value: string) {
  const v = value.trim();
  if (!v) return false;
  return /^(https?:|mailto:|tel:|\/|#)/i.test(v);
}

function sanitizeHtmlWithoutPurifier(
  dirtyHtml: string,
  allowedTags: string[],
  allowedAttrs: string[]
) {
  const allowedTagSet = new Set(allowedTags.map((t) => t.toLowerCase()));
  const allowedAttrSet = new Set(allowedAttrs.map((a) => a.toLowerCase()));

  const template = document.createElement("template");
  template.innerHTML = dirtyHtml;

  const sanitizeNode = (node: Node): Node | DocumentFragment | null => {
    if (node.nodeType === Node.TEXT_NODE) {
      return document.createTextNode(node.textContent || "");
    }

    if (node.nodeType !== Node.ELEMENT_NODE) {
      return null;
    }

    const element = node as HTMLElement;
    const tag = element.tagName.toLowerCase();

    // 非許可タグは中身だけ展開して残す
    if (!allowedTagSet.has(tag)) {
      const fragment = document.createDocumentFragment();
      Array.from(element.childNodes).forEach((child) => {
        const cleanedChild = sanitizeNode(child);
        if (cleanedChild) fragment.appendChild(cleanedChild);
      });
      return fragment;
    }

    const clean = document.createElement(tag);
    Array.from(element.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase();
      const value = attr.value;
      if (!allowedAttrSet.has(name)) return;

      if ((name === "href" || name === "src") && !isSafeUrl(value)) {
        return;
      }

      if (name === "target") {
        if (value === "_blank") {
          clean.setAttribute("target", "_blank");
          clean.setAttribute("rel", "noopener noreferrer");
        }
        return;
      }

      if (name === "class") {
        const safeClassNames = sanitizeClassAttributeValue(value);
        if (safeClassNames) {
          clean.setAttribute("class", safeClassNames);
        }
        return;
      }

      clean.setAttribute(name, value);
    });

    Array.from(element.childNodes).forEach((child) => {
      const cleanedChild = sanitizeNode(child);
      if (cleanedChild) clean.appendChild(cleanedChild);
    });

    return clean;
  };

  const root = document.createElement("div");
  Array.from(template.content.childNodes).forEach((child) => {
    const cleaned = sanitizeNode(child);
    if (cleaned) root.appendChild(cleaned);
  });

  return root.innerHTML;
}

function sanitizeAllowedClasses(html: string) {
  const template = document.createElement("template");
  template.innerHTML = html;

  Array.from(template.content.querySelectorAll("[class]")).forEach((node) => {
    const safeClassNames = sanitizeClassAttributeValue(node.getAttribute("class"));
    if (safeClassNames) {
      node.setAttribute("class", safeClassNames);
      return;
    }
    node.removeAttribute("class");
  });

  return template.innerHTML;
}

function renderSanitizedHTML(
  element: HTMLElement,
  dirtyHtml: string,
  allowed: string[] = [
    "a",
    "strong",
    "em",
    "code",
    "pre",
    "br",
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "img",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "div",
    "span",
    "button",
    "i"
  ]
) {
  const isBotMessage = element.classList.contains("bot-message");
  const purifier = typeof DOMPurify !== "undefined" ? DOMPurify : null;
  if (purifier && typeof purifier.sanitize === "function") {
    let clean = purifier.sanitize(dirtyHtml, {
      ALLOWED_TAGS: allowed,
      ALLOWED_ATTR: ["href", "src", "alt", "title", "target", "class"]
    });
    clean = sanitizeAllowedClasses(clean);
    if (isBotMessage) {
      clean = compactBotMessageHtml(clean);
    }
    element.innerHTML = clean;
    return;
  }

  // サニタイザが未ロードでも許可タグだけを残すフォールバックサニタイズを適用する
  if (allowed.length === 1 && allowed[0] === "br") {
    setTextWithLineBreaks(element, dirtyHtml.replace(/<br\s*\/?>/gi, "\n"));
    return;
  }

  let clean = sanitizeHtmlWithoutPurifier(dirtyHtml, allowed, ["href", "src", "alt", "title", "target", "class"]);
  if (isBotMessage) {
    clean = compactBotMessageHtml(clean);
  }
  element.innerHTML = clean;
}

/**
 * テキストを \n→<br> に変換しつつ安全に挿入
 * @param element
 * @param text
 */
function setTextWithLineBreaks(element: HTMLElement, text: string) {
  element.textContent = "";
  text.split("\n").forEach((line, idx, arr) => {
    element.appendChild(document.createTextNode(line));
    if (idx < arr.length - 1) element.appendChild(document.createElement("br"));
  });
}

const CHAT_SCROLL_BOTTOM_THRESHOLD_PX = 72;

function isChatViewportNearBottom(thresholdPx = CHAT_SCROLL_BOTTOM_THRESHOLD_PX) {
  const container = getSharedDomRefs().chatMessages;
  if (!container) return true;
  const distanceToBottom = container.scrollHeight - (container.scrollTop + container.clientHeight);
  return distanceToBottom <= thresholdPx;
}

// 新しいメッセージを表示領域の末尾へ追従
function scrollMessageToBottom() {
  const chatMessages = getSharedDomRefs().chatMessages;
  if (!chatMessages) return;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setActionButtonIcon(btn: HTMLButtonElement, iconClass: string) {
  btn.innerHTML = `<i class="bi ${iconClass}"></i>`;
}

function setCopyButtonIcon(btn: HTMLButtonElement, iconClass: string) {
  setActionButtonIcon(btn, iconClass);
}

function copyTextWithExecCommand(text: string) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "readonly");
  textArea.setAttribute("aria-hidden", "true");
  textArea.style.position = "fixed";
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.width = "1px";
  textArea.style.height = "1px";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";

  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  textArea.setSelectionRange(0, text.length);

  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textArea);
  }

  return copied;
}

async function copyTextToClipboard(text: string) {
  const clipboardWrite = navigator.clipboard?.writeText?.bind(navigator.clipboard);
  if (clipboardWrite) {
    try {
      await clipboardWrite(text);
      return;
    } catch (error) {
      if (copyTextWithExecCommand(text)) return;
      throw error;
    }
  }

  if (copyTextWithExecCommand(text)) return;
  throw new Error("Clipboard API is unavailable in this browser");
}

// 汎用コピーアイコン
function createCopyBtn(getText: () => string) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "copy-btn";
  btn.setAttribute("aria-label", "メッセージをコピー");
  btn.setAttribute("data-tooltip", "このメッセージをコピー");
  btn.setAttribute("data-tooltip-placement", "top");
  setCopyButtonIcon(btn, "bi-clipboard");

  btn.addEventListener("click", async () => {
    const text = getText();
    try {
      await copyTextToClipboard(text);
      setCopyButtonIcon(btn, "bi-check-lg");
      btn.classList.add("copy-btn--success");
      btn.classList.remove("copy-btn--error");
    } catch (error) {
      console.error("Failed to copy chat message.", error);
      setCopyButtonIcon(btn, "bi-x-lg");
      btn.classList.add("copy-btn--error");
      btn.classList.remove("copy-btn--success");
    } finally {
      window.setTimeout(() => {
        setCopyButtonIcon(btn, "bi-clipboard");
        btn.classList.remove("copy-btn--success", "copy-btn--error");
      }, 2000);
    }
  });

  return btn;
}

function createMemoSaveBtn(getText: () => string) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "memo-save-btn";
  btn.setAttribute("aria-label", "メモに保存");
  btn.setAttribute("data-tooltip", "この回答をメモに保存");
  btn.setAttribute("data-tooltip-placement", "top");
  setActionButtonIcon(btn, "bi-bookmark-plus");

  let resetTimerId: number | null = null;

  const resetVisualState = () => {
    if (resetTimerId !== null) {
      window.clearTimeout(resetTimerId);
      resetTimerId = null;
    }
    setActionButtonIcon(btn, "bi-bookmark-plus");
    btn.classList.remove("memo-save-btn--success", "memo-save-btn--error", "memo-save-btn--loading");
    btn.setAttribute("data-tooltip", "この回答をメモに保存");
  };

  const scheduleReset = () => {
    if (resetTimerId !== null) {
      window.clearTimeout(resetTimerId);
    }
    resetTimerId = window.setTimeout(() => {
      resetVisualState();
    }, 2000);
  };

  btn.addEventListener("click", async () => {
    if (btn.classList.contains("memo-save-btn--loading")) return;
    resetVisualState();

    const aiResponse = getText().trim();
    if (!aiResponse) {
      setActionButtonIcon(btn, "bi-x-lg");
      btn.classList.add("memo-save-btn--error");
      btn.setAttribute("data-tooltip", "保存失敗: 空のメッセージです");
      scheduleReset();
      return;
    }

    btn.disabled = true;
    btn.classList.add("memo-save-btn--loading");
    setActionButtonIcon(btn, "bi-hourglass-split");

    try {
      const response = await fetch("/memo/api", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        credentials: "same-origin",
        body: JSON.stringify({
          input_content: "",
          ai_response: aiResponse,
          title: "",
          tags: ""
        })
      });

      const rawPayload = await readJsonBodySafe(response);
      const parsed = MemoSaveResponseSchema.safeParse(rawPayload);
      const status = parsed.success ? parsed.data.status : null;

      if (!response.ok || status === "fail") {
        throw new Error(extractApiErrorMessage(rawPayload, "メモの保存に失敗しました。", response.status));
      }

      setActionButtonIcon(btn, "bi-check-lg");
      btn.classList.add("memo-save-btn--success");
      btn.classList.remove("memo-save-btn--error");
      btn.setAttribute("data-tooltip", "メモに保存しました");
    } catch (error) {
      console.error("Failed to save chat message to memo.", error);
      setActionButtonIcon(btn, "bi-x-lg");
      btn.classList.add("memo-save-btn--error");
      btn.classList.remove("memo-save-btn--success");
      btn.setAttribute("data-tooltip", error instanceof Error ? `保存失敗: ${error.message}` : "保存に失敗しました");
    } finally {
      btn.disabled = false;
      btn.classList.remove("memo-save-btn--loading");
      scheduleReset();
    }
  });

  return btn;
}

function scrollMessageToTop(_element?: HTMLElement) {
  scrollMessageToBottom();
}

export {
  renderSanitizedHTML,
  setTextWithLineBreaks,
  isChatViewportNearBottom,
  scrollMessageToBottom,
  scrollMessageToTop,
  copyTextToClipboard,
  createCopyBtn,
  createMemoSaveBtn
};
