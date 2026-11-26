// チャット入力欄の添付メニューにある「貼り付け」操作用の hook。クリップボードから画像（添付）か文字（カーソル位置へ挿入）を読み取る。呼び出し元は components/chat_page/chat_main_section.tsx と setup_section.tsx。
// Hook behind the paste action in the chat composer's attach menu: reads images (as attachments) or text (inserted at the caret) from the clipboard. Used by components/chat_page/chat_main_section.tsx and setup_section.tsx.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

import { useTranslation } from "../../contexts/locale_context";

type ClipboardContent = { files: File[]; text: string; unsupported?: boolean };

// クリップボード読み取り権限の状態を安全に確認する（未対応ブラウザでは "unsupported" を返す）。
// Safely check the clipboard-read permission state (returns "unsupported" when unavailable).
async function getClipboardPermissionState(): Promise<PermissionState | "unsupported"> {
  try {
    if (!navigator.permissions?.query) return "unsupported";
    const status = await navigator.permissions.query({ name: "clipboard-read" as PermissionName });
    return status.state;
  } catch {
    return "unsupported";
  }
}

function isNotAllowedError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "NotAllowedError";
}

function isFocusLossError(error: unknown): boolean {
  return error instanceof Error && /not focused/i.test(error.message);
}

// 1フレーム待機する（権限ダイアログ直後のフォーカス復帰を待つために使う）。
// Wait one animation frame so focus can settle after a permission prompt closes.
function waitForNextFrame(): Promise<void> {
  if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

// 同じ項目の画像と文章を両方貼ると、画像の代替テキストやURLも重複して入ってしまう。
// Prefer images over their alternate text/URL representations.
// クリップボードの中身を読む。画像があれば画像だけを返し、無ければ text/plain を結合して返す。対応する形式が無いときは unsupported を立てる
// Read the clipboard: return images only when present, otherwise the joined text/plain; flag unsupported when nothing usable is found
async function readClipboardContent(textOnlyFallback = false): Promise<ClipboardContent> {
  const clipboard = navigator.clipboard;
  if (textOnlyFallback || !clipboard?.read) {
    if (clipboard?.readText) return { files: [], text: await clipboard.readText() };
    throw new Error("Clipboard reading is unavailable");
  }

  const items = await clipboard.read();
  const files: File[] = [];
  const texts: string[] = [];
  const imageExtensions: Record<string, string> = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
  };
  for (const item of items) {
    const imageType = item.types.find((type) => imageExtensions[type]);
    if (imageType) {
      const blob = await item.getType(imageType);
      files.push(new File([blob], `paste-${crypto.randomUUID()}.${imageExtensions[imageType]}`, { type: imageType }));
    } else if (item.types.includes("text/plain")) {
      texts.push(await (await item.getType("text/plain")).text());
    }
  }
  return { files, text: files.length ? "" : texts.join("\n"), unsupported: items.length > 0 && !files.length && !texts.length };
}

// 初回の読み取りが権限ダイアログ直後のフォーカス喪失や read() 非対応で失敗した場合に、安全な条件だけ再試行する。
// Retry once when the first read fails due to focus loss right after a permission grant or when read() is unsupported.
async function readClipboardWithRetry(input: HTMLTextAreaElement, isCurrent: () => boolean): Promise<ClipboardContent> {
  try {
    return await readClipboardContent();
  } catch (error) {
    if (!isCurrent()) throw error;

    if (isNotAllowedError(error)) {
      const permissionState = await getClipboardPermissionState();
      const canRetry = permissionState === "granted" || (permissionState !== "denied" && isFocusLossError(error));
      if (!canRetry || !isCurrent()) throw error;

      if (typeof document !== "undefined" && !document.hasFocus()) {
        window.focus?.();
        input.focus();
        await waitForNextFrame();
        if (!isCurrent()) throw error;
      }

      try {
        return await readClipboardContent();
      } catch (retryError) {
        if (!isCurrent() || isNotAllowedError(retryError) || typeof navigator.clipboard?.readText !== "function") {
          throw retryError;
        }
        return await readClipboardContent(true);
      }
    }

    if (typeof navigator.clipboard?.read === "function" && typeof navigator.clipboard?.readText === "function") {
      return await readClipboardContent(true);
    }
    throw error;
  }
}

type ChatClipboardPasteOptions = {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  setInputValue: (value: string) => void;
  attachSelectedFiles: (files: File[], isCurrent: () => boolean) => Promise<void>;
  notifyError: (message: string) => void;
  isDisabled: boolean;
  scopeKey?: string | null;
};

// 貼り付け操作の処理を返す。読み取り中の二重実行を防ぎ、許可待ちの間に画面が変わった場合は結果を適用しない
// Return the paste handler; it blocks re-entry while reading and drops the result if the screen changed during the permission prompt
export function useChatClipboardPaste(options: ChatClipboardPasteOptions) {
  const { t } = useTranslation();
  const { inputRef, isDisabled, scopeKey } = options;
  // 非同期の途中でも最新の props を参照するため、毎回 ref に保存しておく
  // Keep the latest options in a ref so async work always sees current values
  const latestOptions = useRef(options);
  // 入力欄やルームが切り替わるたびに増やす番号。読み取り開始時の値と比べて、古い結果を判別する
  // Counter bumped whenever the composer or room changes; compared with the value at read start to spot stale results
  const scopeRef = useRef(0);
  const pendingRef = useRef(false);
  const caretRef = useRef<{ value: string; position: number } | null>(null);
  const [isPasting, setIsPasting] = useState(false);

  // 貼り付けた値が画面に出るのと同じコミットでフォーカスとキャレットを戻す。useEffect だと描画後に
  // 遅れて動き、キャレットが一瞬末尾に出るうえ、値の変化を監視する側（テストの waitFor など）が
  // フォーカス前の状態を読む。React 19 はサーバー描画で useLayoutEffect を警告しない。
  // Restore focus and the caret in the same commit that shows the pasted value. A useEffect runs later,
  // after paint, so the caret briefly sits at the end and an observer of the value (a test's waitFor,
  // say) reads the input before focus returns. React 19 does not warn about useLayoutEffect on the server.
  useLayoutEffect(() => {
    latestOptions.current = options;
    const caret = caretRef.current;
    const input = inputRef.current;
    if (caret && input?.value === caret.value) {
      caretRef.current = null;
      input.focus();
      input.setSelectionRange(caret.position, caret.position);
    }
  });

  // 許可待ちの間に画面・ルームが変わった場合は、結果を別の入力へ適用しない。
  // Discard a pending read when its composer or room is left, disabled, or unmounted.
  useEffect(() => {
    pendingRef.current = false;
    setIsPasting(false);
    return () => {
      scopeRef.current += 1;
      caretRef.current = null;
    };
  }, [isDisabled, scopeKey]);

  const handlePaste = useCallback(async () => {
    if (latestOptions.current.isDisabled || pendingRef.current) return;
    const input = inputRef.current;
    if (!input) return;
    const scope = scopeRef.current;
    const isCurrent = () => scope === scopeRef.current && !latestOptions.current.isDisabled;
    pendingRef.current = true;
    setIsPasting(true);
    try {
      // ユーザーのタップと同じ呼び出し内で読み取りを始める。
      // Start the read in the user's tap handler, before any other async work.
      const content = await readClipboardWithRetry(input, isCurrent);
      if (!isCurrent()) return;
      if (content.files.length) {
        await latestOptions.current.attachSelectedFiles(content.files, isCurrent);
      } else if (content.text) {
        // 許可待ちの間に編集されていても、現在の入力を保持して挿入する。
        // Preserve edits made while clipboard permission was pending.
        const value = input.value.slice(0, input.selectionStart) + content.text + input.value.slice(input.selectionEnd);
        caretRef.current = { value, position: input.selectionStart + content.text.length };
        latestOptions.current.setInputValue(value);
      } else {
        latestOptions.current.notifyError(t(content.unsupported ? "home.attachMenu.pasteUnsupported" : "home.attachMenu.pasteEmpty"));
      }
    } catch {
      if (isCurrent()) {
        latestOptions.current.notifyError(t("home.attachMenu.pasteUnavailable"));
      }
    } finally {
      if (scope === scopeRef.current) {
        pendingRef.current = false;
        setIsPasting(false);
      }
    }
  }, [inputRef, t]);

  return { handlePaste, isPasting };
}
