// 共有プロンプトページの初期化を行う hook。body クラスの付与、Web Components の読み込み、Web Share 対応の判定、アンマウント時の後始末を担う。呼び出し元は pages/prompt_share/index.tsx。
// Hook that sets up the prompt-share page: body class, Web Components loading, Web Share support detection and unmount cleanup. Used by pages/prompt_share/index.tsx.
import { useEffect, useState, type MutableRefObject } from "react";
import { isNativeShareSupported } from "../../lib/share";

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
    setSupportsNativeShare(isNativeShareSupported());

    // popup_menu と user_icon のカスタム要素は、このページを開いたときに初めて読み込む
    // The popup_menu and user_icon custom elements are loaded only when this page is opened
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
