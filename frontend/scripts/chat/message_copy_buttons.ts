// メッセージ本文に埋め込まれたコピーボタンの共通ハンドラ。
// コードブロックとコピー枠は同じ「枠の右上のボタンで枠の中身をコピーする」挙動なので、
// document 委譲を1つだけ張り、ボタンごとのコピー元だけを表で切り替える。
// 委譲にしているのは、本文が生成中に何度も差し替わってもリスナーを付け直さずに済むため。
// Shared handler for the copy buttons embedded in message bodies.
// Code blocks and copy cards share the same behaviour — a button at the top right
// copies the body of its own frame — so a single document-level delegation is
// registered and only the copy source differs per button. Delegation keeps the
// listener valid while the streamed body is patched over and over.

import { copyTextToClipboard } from "./message_utils";

// アイコンの復帰と一時ラベルの表示時間。CSS のフィードバック表示と揃えている。
// How long the icon and temporary label stay in their feedback state.
const FEEDBACK_RESET_MS = 2000;

type CopyButtonSource = {
  // クリック対象のボタン / The clickable button
  buttonSelector: string;
  // ボタンとコピー元を含む枠 / The frame holding both the button and the copy source
  containerSelector: string;
  // 枠の中でコピー対象になる要素 / The element inside the frame that is copied
  textSelector: string;
};

const COPY_BUTTON_SOURCES: CopyButtonSource[] = [
  {
    buttonSelector: ".code-block-copy-btn",
    containerSelector: ".code-block-container",
    textSelector: "code",
  },
  {
    buttonSelector: ".copy-block-copy-btn",
    containerSelector: ".copy-block-container",
    textSelector: ".copy-block-text",
  },
];

const COPY_BUTTON_SELECTOR = COPY_BUTTON_SOURCES.map((source) => source.buttonSelector).join(", ");

// クリックされたボタンがどの種類かを判定し、その枠からコピー対象のテキストを取り出す。
// Identify which kind of button was clicked and read the copy text from its frame.
function readCopySourceText(button: Element): string | null {
  const source = COPY_BUTTON_SOURCES.find((candidate) => button.matches(candidate.buttonSelector));
  if (!source) return null;
  const textElement = button.closest(source.containerSelector)?.querySelector(source.textSelector);
  return textElement ? textElement.textContent || "" : "";
}

// 成功・失敗をアイコンとラベルで一時的に知らせ、一定時間後に元へ戻す。
// Show the outcome on the icon and label for a moment, then restore them.
function showCopyFeedback(button: Element, succeeded: boolean) {
  const icon = button.querySelector("i");
  const textSpan = button.querySelector("span");
  const defaultLabel = textSpan ? textSpan.dataset.defaultLabel || textSpan.textContent || "" : "";
  if (textSpan) textSpan.dataset.defaultLabel = defaultLabel;

  if (icon) {
    icon.classList.remove("bi-clipboard", "bi-check-lg", "bi-x-lg");
    icon.classList.add(succeeded ? "bi-check-lg" : "bi-x-lg");
    window.setTimeout(() => {
      icon.classList.remove("bi-check-lg", "bi-x-lg");
      icon.classList.add("bi-clipboard");
    }, FEEDBACK_RESET_MS);
  }

  if (textSpan) {
    textSpan.textContent = succeeded ? "Copied!" : "Failed";
    window.setTimeout(() => {
      textSpan.textContent = defaultLabel;
    }, FEEDBACK_RESET_MS);
  }
}

function onMessageCopyButtonClick(event: Event) {
  const target = event.target as Element | null;
  const button = target?.closest(COPY_BUTTON_SELECTOR) as HTMLButtonElement | null;
  if (!button) return;

  const text = readCopySourceText(button);
  if (text === null) return;

  copyTextToClipboard(text)
    .then(() => {
      showCopyFeedback(button, true);
    })
    .catch((error) => {
      console.error("Failed to copy message block.", error);
      showCopyFeedback(button, false);
    });
}

let messageCopyButtonsInitialized = false;

// 本文中のコピーボタンは document 委譲で処理するため、ページごとに一度だけ登録する。
// The in-message copy buttons are handled via document delegation, so register the
// listener once per page.
export function initMessageCopyButtons() {
  if (messageCopyButtonsInitialized) return;
  messageCopyButtonsInitialized = true;
  document.addEventListener("click", onMessageCopyButtonClick);
}
