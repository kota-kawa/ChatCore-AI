import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "../../contexts/locale_context";
import type { MemoView } from "../../lib/memo/types";

// 型の正本は lib/memo/types.ts。既存の import 元との互換のため再エクスポートする。
// The type now lives in lib/memo/types.ts; re-export it so existing imports keep working.
export type { MemoView };

type MemoViewSwitcherProps = {
  activeView: MemoView;
  setActiveView: Dispatch<SetStateAction<MemoView>>;
};

export function MemoViewSwitcher({ activeView, setActiveView }: MemoViewSwitcherProps) {
  const { t } = useTranslation();
  return (
    <nav className="memo-view-switcher" aria-label={t("memo.viewSwitcher")}>
      <button
        type="button"
        className={`memo-view-switcher__item${activeView === "memos" ? " is-active" : ""}`}
        aria-current={activeView === "memos" ? "page" : undefined}
        onClick={() => setActiveView("memos")}
      >
        <i className="bi bi-journal-text" aria-hidden="true"></i>
        <span>{t("memo.heading")}</span>
      </button>
      <button
        type="button"
        className={`memo-view-switcher__item${activeView === "context" ? " is-active" : ""}`}
        aria-current={activeView === "context" ? "page" : undefined}
        onClick={() => setActiveView("context")}
      >
        <i className="bi bi-safe" aria-hidden="true"></i>
        <span>{t("memo.myContext")}</span>
      </button>
    </nav>
  );
}
