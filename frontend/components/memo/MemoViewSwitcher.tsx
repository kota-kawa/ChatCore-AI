import type { Dispatch, SetStateAction } from "react";

export type MemoView = "memos" | "context";

type MemoViewSwitcherProps = {
  activeView: MemoView;
  setActiveView: Dispatch<SetStateAction<MemoView>>;
};

export function MemoViewSwitcher({ activeView, setActiveView }: MemoViewSwitcherProps) {
  return (
    <nav className="memo-view-switcher" aria-label="Notebookの表示切り替え">
      <button
        type="button"
        className={`memo-view-switcher__item${activeView === "memos" ? " is-active" : ""}`}
        aria-current={activeView === "memos" ? "page" : undefined}
        onClick={() => setActiveView("memos")}
      >
        <i className="bi bi-journal-text" aria-hidden="true"></i>
        <span>メモ</span>
      </button>
      <button
        type="button"
        className={`memo-view-switcher__item${activeView === "context" ? " is-active" : ""}`}
        aria-current={activeView === "context" ? "page" : undefined}
        onClick={() => setActiveView("context")}
      >
        <i className="bi bi-safe" aria-hidden="true"></i>
        <span>マイコンテキスト</span>
      </button>
    </nav>
  );
}
