// ブラウザのクリップボードへテキストを書き込む共通 primitive。
// Shared browser clipboard primitive used by React and legacy DOM surfaces.

function copyTextWithExecCommand(text: string): boolean {
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
/**
 * Copy text using the async Clipboard API, with the legacy DOM fallback kept
 * for browsers and embedded contexts where that API is unavailable.
 */
export async function copyTextToClipboard(text: string): Promise<void> {
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
