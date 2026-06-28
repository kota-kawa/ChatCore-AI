import { type Dispatch, type SetStateAction } from "react";

import type { BulkAction, Collection, MemoSummary } from "../../lib/memo/types";
import { MemoSelect } from "./MemoSelect";

type MemoBulkBarProps = {
  hasSelection: boolean;
  selectedIds: Set<string>;
  memos: MemoSummary[];
  selectAll: () => void;
  deselectAll: () => void;
  executeBulkAction: (action: BulkAction, extra?: { collectionId?: number | null }) => Promise<void>;
  bulkLoading: boolean;
  collections: Collection[];
  bulkCollectionId: number | null;
  setBulkCollectionId: Dispatch<SetStateAction<number | null>>;
};

// Bulk action bar
export function MemoBulkBar({
  hasSelection,
  selectedIds,
  memos,
  selectAll,
  deselectAll,
  executeBulkAction,
  bulkLoading,
  collections,
  bulkCollectionId,
  setBulkCollectionId,
}: MemoBulkBarProps) {
  return (
            <div className="memo-bulk-bar memo-card" role="toolbar" aria-label="一括操作バー">
              <div className="memo-bulk-bar__info">
                <input
                  type="checkbox"
                  id="bulk-select-all"
                  className="memo-bulk-checkbox"
                  checked={hasSelection && selectedIds.size === memos.length}
                  onChange={(e) => { if (e.target.checked) selectAll(); else deselectAll(); }}
                />
                <label htmlFor="bulk-select-all" className="memo-bulk-bar__count">
                  {hasSelection ? `${selectedIds.size}件選択中` : "すべて選択"}
                </label>
              </div>
              <div className="memo-bulk-bar__actions">
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("pin")} disabled={!hasSelection || bulkLoading} data-tooltip="ピン留め" data-tooltip-placement="top">
                  <i className="bi bi-pin-angle"></i>ピン留め
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unpin")} disabled={!hasSelection || bulkLoading} data-tooltip="ピン留め解除" data-tooltip-placement="top">
                  <i className="bi bi-pin-angle-fill"></i>解除
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("archive")} disabled={!hasSelection || bulkLoading} data-tooltip="アーカイブ" data-tooltip-placement="top">
                  <i className="bi bi-archive"></i>アーカイブ
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unarchive")} disabled={!hasSelection || bulkLoading} data-tooltip="アーカイブ解除" data-tooltip-placement="top">
                  <i className="bi bi-archive-fill"></i>解除
                </button>
                {collections.length > 0 && (
                  <div className="memo-bulk-bar__tag-group">
                    <MemoSelect
                      className="memo-select--sm"
                      value={String(bulkCollectionId ?? "")}
                      onChange={(v) => setBulkCollectionId(v === "" ? null : Number(v))}
                      options={[
                        { value: "", label: "コレクション選択" },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
                      ]}
                    />
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("set_collection", { collectionId: bulkCollectionId })} disabled={!hasSelection || bulkLoading || bulkCollectionId === null} data-tooltip="コレクション設定" data-tooltip-placement="top">
                      <i className="bi bi-folder2"></i>設定
                    </button>
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("clear_collection")} disabled={!hasSelection || bulkLoading} data-tooltip="コレクション解除" data-tooltip-placement="top">
                      解除
                    </button>
                  </div>
                )}
                <button type="button" className="memo-bulk-btn memo-bulk-btn--danger" onClick={() => void executeBulkAction("delete")} disabled={!hasSelection || bulkLoading} data-tooltip="削除" data-tooltip-placement="top">
                  <i className="bi bi-trash3"></i>削除
                </button>
              </div>
            </div>
  );
}
