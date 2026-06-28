import { type Dispatch, type SetStateAction } from "react";

import type { Collection } from "../../lib/memo/types";

type MemoCollectionModalProps = {
  isCollectionPanelOpen: boolean;
  setIsCollectionPanelOpen: (value: boolean) => void;
  collections: Collection[];
  newCollectionName: string;
  setNewCollectionName: Dispatch<SetStateAction<string>>;
  newCollectionColor: string;
  setNewCollectionColor: Dispatch<SetStateAction<string>>;
  collectionActionLoading: boolean;
  handleCreateCollection: () => Promise<void>;
  editingCollectionId: number | null;
  setEditingCollectionId: Dispatch<SetStateAction<number | null>>;
  editingCollectionName: string;
  setEditingCollectionName: Dispatch<SetStateAction<string>>;
  editingCollectionColor: string;
  setEditingCollectionColor: Dispatch<SetStateAction<string>>;
  handleUpdateCollection: (collectionId: number) => Promise<void>;
  handleDeleteCollection: (collectionId: number, name: string) => Promise<void>;
};

// ── Collection management panel ──
export function MemoCollectionModal({
  isCollectionPanelOpen,
  setIsCollectionPanelOpen,
  collections,
  newCollectionName,
  setNewCollectionName,
  newCollectionColor,
  setNewCollectionColor,
  collectionActionLoading,
  handleCreateCollection,
  editingCollectionId,
  setEditingCollectionId,
  editingCollectionName,
  setEditingCollectionName,
  editingCollectionColor,
  setEditingCollectionColor,
  handleUpdateCollection,
  handleDeleteCollection,
}: MemoCollectionModalProps) {
  return (
        <div className={`memo-collection-modal${isCollectionPanelOpen ? " is-visible" : ""}`} aria-hidden={isCollectionPanelOpen ? "false" : "true"}>
          <div className="memo-collection-modal__overlay" onClick={() => setIsCollectionPanelOpen(false)}></div>
          <div className="memo-collection-modal__content" role="dialog" aria-modal="true" aria-labelledby="collectionPanelTitle">
            <button type="button" className="memo-collection-modal__close" aria-label="閉じる" onClick={() => setIsCollectionPanelOpen(false)}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-collection-modal__header">
              <h3 id="collectionPanelTitle"><i className="bi bi-folder2-open"></i>コレクション管理</h3>
              <p>メモをグループ分けして整理できます。</p>
            </header>
            <div className="memo-collection-modal__body">
              {/* Create new */}
              <div className="memo-collection-create">
                <input
                  type="text"
                  className="memo-control memo-collection-create__input"
                  value={newCollectionName}
                  onChange={(e) => setNewCollectionName(e.target.value)}
                  placeholder="新しいコレクション名"
                  maxLength={100}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void handleCreateCollection(); } }}
                />
                <div className="memo-collection-create__color-row">
                  <label htmlFor="new-collection-color">カラー</label>
                  <input type="color" id="new-collection-color" value={newCollectionColor} onChange={(e) => setNewCollectionColor(e.target.value)} className="memo-collection-color-input" />
                  <div className="memo-collection-presets">
                    {["#6b7280", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9"].map((c) => (
                      <button
                        type="button"
                        key={c}
                        className={`memo-collection-preset${newCollectionColor === c ? " is-active" : ""}`}
                        style={{ background: c }}
                        onClick={() => setNewCollectionColor(c)}
                        data-tooltip={c}
                        data-tooltip-placement="top"
                      />
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  className="primary-button memo-collection-create__btn"
                  onClick={() => { void handleCreateCollection(); }}
                  disabled={collectionActionLoading || !newCollectionName.trim()}
                >
                  <i className="bi bi-plus-lg"></i>作成
                </button>
              </div>

              {/* Collection list */}
              {collections.length === 0 && <p className="memo-collection-empty">コレクションはまだありません。</p>}
              <ul className="memo-collection-list">
                {collections.map((col) => (
                  <li key={col.id} className="memo-collection-item">
                    {editingCollectionId === col.id ? (
                      <div className="memo-collection-item__edit">
                        <input
                          type="text"
                          className="memo-control"
                          value={editingCollectionName}
                          onChange={(e) => setEditingCollectionName(e.target.value)}
                          maxLength={100}
                        />
                        <div className="memo-collection-create__color-row">
                          <label>カラー</label>
                          <input type="color" value={editingCollectionColor} onChange={(e) => setEditingCollectionColor(e.target.value)} className="memo-collection-color-input" />
                          <div className="memo-collection-presets">
                            {["#6b7280", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#0ea5e9"].map((c) => (
                              <button type="button" key={c} className={`memo-collection-preset${editingCollectionColor === c ? " is-active" : ""}`} style={{ background: c }} onClick={() => setEditingCollectionColor(c)} data-tooltip={c} data-tooltip-placement="top" />
                            ))}
                          </div>
                        </div>
                        <div className="memo-collection-item__edit-actions">
                          <button type="button" className="primary-button" onClick={() => { void handleUpdateCollection(col.id); }} disabled={collectionActionLoading}>保存</button>
                          <button type="button" className="secondary-button" onClick={() => setEditingCollectionId(null)}>キャンセル</button>
                        </div>
                      </div>
                    ) : (
                      <div className="memo-collection-item__row">
                        <span className="memo-collection-item__dot" style={{ background: col.color }}></span>
                        <span className="memo-collection-item__name">{col.name}</span>
                        <span className="memo-collection-item__count">{col.memo_count}件</span>
                        <button type="button" className="memo-collection-item__action" onClick={() => { setEditingCollectionId(col.id); setEditingCollectionName(col.name); setEditingCollectionColor(col.color); }} data-tooltip="編集" data-tooltip-placement="top">
                          <i className="bi bi-pencil"></i>
                        </button>
                        <button type="button" className="memo-collection-item__action memo-collection-item__action--danger" onClick={() => { void handleDeleteCollection(col.id, col.name); }} disabled={collectionActionLoading} data-tooltip="削除" data-tooltip-placement="top">
                          <i className="bi bi-trash3"></i>
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
  );
}
