import { MemoSelect } from "./MemoSelect";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageBoardContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

// Bulk action bar
export function MemoBulkBar() {
  const { memos, collections } = useMemoPageListContext();
  const {
    hasSelection,
    selectedIds,
    selectAll,
    deselectAll,
    executeBulkAction,
    bulkLoading,
    bulkCollectionId,
    setBulkCollectionId,
  } = useMemoPageBoardContext();
  const { t } = useTranslation();
  return (
            <div className="memo-bulk-bar memo-card" role="toolbar" aria-label={t("memo.bulkToolbar")}>
              <div className="memo-bulk-bar__info">
                <input
                  type="checkbox"
                  id="bulk-select-all"
                  className="memo-bulk-checkbox"
                  checked={hasSelection && selectedIds.size === memos.length}
                  onChange={(e) => { if (e.target.checked) selectAll(); else deselectAll(); }}
                />
                <label htmlFor="bulk-select-all" className="memo-bulk-bar__count">
                  {hasSelection ? t("memo.selectedCount", { count: selectedIds.size }) : t("memo.selectAll")}
                </label>
              </div>
              <div className="memo-bulk-bar__actions">
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("pin")} disabled={!hasSelection || bulkLoading} data-tooltip={t("memo.pin")} data-tooltip-placement="top">
                  <i className="bi bi-pin-angle"></i>{t("memo.pin")}
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unpin")} disabled={!hasSelection || bulkLoading} data-tooltip={t("memo.unpin")} data-tooltip-placement="top">
                  <i className="bi bi-pin-angle-fill"></i>{t("memo.remove")}
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("archive")} disabled={!hasSelection || bulkLoading} data-tooltip={t("memo.archive")} data-tooltip-placement="top">
                  <i className="bi bi-archive"></i>{t("memo.archive")}
                </button>
                <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("unarchive")} disabled={!hasSelection || bulkLoading} data-tooltip={t("memo.unarchive")} data-tooltip-placement="top">
                  <i className="bi bi-archive-fill"></i>{t("memo.remove")}
                </button>
                {collections.length > 0 && (
                  <div className="memo-bulk-bar__tag-group">
                    <MemoSelect
                      className="memo-select--sm"
                      value={String(bulkCollectionId ?? "")}
                      onChange={(v) => setBulkCollectionId(v === "" ? null : Number(v))}
                      options={[
                        { value: "", label: t("memo.chooseCollection") },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
                      ]}
                    />
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("set_collection", { collectionId: bulkCollectionId })} disabled={!hasSelection || bulkLoading || bulkCollectionId === null} data-tooltip={t("memo.setCollection")} data-tooltip-placement="top">
                      <i className="bi bi-folder2"></i>{t("memo.set")}
                    </button>
                    <button type="button" className="memo-bulk-btn" onClick={() => void executeBulkAction("clear_collection")} disabled={!hasSelection || bulkLoading} data-tooltip={t("memo.clearCollection")} data-tooltip-placement="top">
                      {t("memo.remove")}
                    </button>
                  </div>
                )}
                <button type="button" className="memo-bulk-btn memo-bulk-btn--danger" onClick={() => void executeBulkAction("delete")} disabled={!hasSelection || bulkLoading} data-tooltip={t("common.delete")} data-tooltip-placement="top">
                  <i className="bi bi-trash3"></i>{t("common.delete")}
                </button>
              </div>
            </div>
  );
}
