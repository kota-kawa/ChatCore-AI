import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

import { useTranslation } from "../../contexts/locale_context";

type ClipboardContent = { files: File[]; text: string; unsupported?: boolean };

// 同じ項目の画像と文章を両方貼ると、画像の代替テキストやURLも重複して入ってしまう。
// Prefer images over their alternate text/URL representations.
async function readClipboardContent(): Promise<ClipboardContent> {
  const clipboard = navigator.clipboard;
  if (!clipboard?.read) {
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

type ChatClipboardPasteOptions = {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  setInputValue: (value: string) => void;
  attachSelectedFiles: (files: File[], isCurrent: () => boolean) => Promise<void>;
  notifyError: (message: string) => void;
  isDisabled: boolean;
  scopeKey?: string | null;
};

export function useChatClipboardPaste(options: ChatClipboardPasteOptions) {
  const { t } = useTranslation();
  const { inputRef, isDisabled, scopeKey } = options;
  const latestOptions = useRef(options);
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
      const content = await readClipboardContent();
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
