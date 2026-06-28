import React from "react";

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
