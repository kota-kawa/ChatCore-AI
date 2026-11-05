// メモのコレクション名を、コレクションごとの色付きバッジで表示するコンポーネント。MemoHistoryPanel から使われる。
// Component that shows a memo's collection name as a badge in the collection's color; used by MemoHistoryPanel.
import React from "react";

// コレクション名を示すバッジ。
// ---------------------------------------------------------------------------
// CollectionBadge
// ---------------------------------------------------------------------------

// コレクション（タグ）のバッジを表示するコンポーネント
// Component to display a collection (tag) badge
export function CollectionBadge({ name, color }: { name: string; color: string }) {
  return (
    <span className="memo-collection-badge" style={{ "--badge-color": color } as React.CSSProperties}>
      <i className="bi bi-folder2" aria-hidden="true"></i>
      {name}
    </span>
  );
}
