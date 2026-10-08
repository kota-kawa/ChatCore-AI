import { useEffect, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useMemoPageComposerContext } from "../../contexts/memo_page/memo_page_context";

// 作成欄は一覧の先頭にあるため、画面外へスクロールした後も新規作成に届く入口を出す。
// 押すと作成欄へ戻って入力を始める。狭い画面では CSS で文字ラベルを隠す。
// Keep new-memo creation reachable when the composer at the top scrolls off-screen.
// Clicking returns to the composer, ready to type; CSS hides the text label on narrow screens.
export function MemoNewFab() {
  const { t } = useTranslation();
  const { openTextComposer } = useMemoPageComposerContext();
  const [composerVisible, setComposerVisible] = useState(true);

  useEffect(() => {
    const composer = document.getElementById("memo-composer");
    if (!composer || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(([entry]) => setComposerVisible(entry.isIntersecting));
    observer.observe(composer);
    return () => observer.disconnect();
  }, []);

  if (composerVisible) return null;
  return (
    <button
      type="button"
      className="memo-new-fab"
      data-memo-composer-trigger=""
      onClick={() => {
        document.getElementById("memo-composer")?.scrollIntoView({ block: "start" });
        const toolbar = document.querySelector<HTMLElement>(".memo-toolbar");
        // PC の固定ツールバーで、戻った作成欄の見出しが隠れないようにする。
        // Leave the returned composer below the sticky desktop toolbar.
        if (toolbar && getComputedStyle(toolbar).position === "sticky") {
          window.scrollBy({ top: -(toolbar.getBoundingClientRect().bottom + 16) });
        }
        openTextComposer();
      }}
      aria-label={t("memo.new")}
    >
      <i className="bi bi-plus-lg" aria-hidden="true"></i>
      <span className="memo-new-fab__label">{t("memo.new")}</span>
    </button>
  );
}
