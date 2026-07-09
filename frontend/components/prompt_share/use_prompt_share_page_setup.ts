import { useEffect, useState, type MutableRefObject } from "react";

type UsePromptSharePageSetupOptions = {
  hasModalLockRef: MutableRefObject<boolean>;
  postCloseTimerRef: MutableRefObject<number | null>;
};

// ページ固有のbodyクラス、Web Components、Web Share対応状況、アンマウント時のDOM復元を管理する
// Manages page-specific body classes, Web Components, Web Share support, and DOM cleanup
export function usePromptSharePageSetup({
  hasModalLockRef,
  postCloseTimerRef
}: UsePromptSharePageSetupOptions) {
  const [supportsNativeShare, setSupportsNativeShare] = useState(false);

  useEffect(() => {
    document.body.classList.add("prompt-share-page");
    setSupportsNativeShare(typeof navigator !== "undefined" && typeof navigator.share === "function");

    const importCustomElements = async () => {
      await Promise.all([
        import("../../scripts/components/popup_menu"),
        import("../../scripts/components/user_icon")
      ]);
    };
    void importCustomElements();

    return () => {
      // アンマウント時にスクロールロックとページ固有のクラスを全てクリーンアップする
      // Clean up scroll lock state and page-specific classes on unmount
      document.documentElement.classList.remove("ps-modal-open");
      document.body.classList.remove("ps-modal-open");
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.width = "";
      hasModalLockRef.current = false;
      document.body.classList.remove("prompt-share-page");

      if (postCloseTimerRef.current !== null) {
        window.clearTimeout(postCloseTimerRef.current);
        postCloseTimerRef.current = null;
      }
    };
  }, [hasModalLockRef, postCloseTimerRef]);

  return supportsNativeShare;
}
