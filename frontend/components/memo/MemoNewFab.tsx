import { useEffect, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useMemoPageComposerContext } from "../../contexts/memo_page/memo_page_context";

// ── New memo button for phones ──
// スマホでは作成欄が一覧の先頭にしか無く、スクロールすると書き始められない。作成欄が画面から
// 外れている間だけ出し、押すと作成欄へ戻って入力を始める（表示する幅は CSS が決める）。
// On phones the composer sits only at the top of the list, out of reach once scrolled. This shows
// while the composer is off-screen and jumps back to it, ready to type (CSS decides the widths
// it appears at).
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
        openTextComposer();
      }}
      aria-label={t("memo.new")}
    >
      <i className="bi bi-plus-lg" aria-hidden="true"></i>
    </button>
  );
}
