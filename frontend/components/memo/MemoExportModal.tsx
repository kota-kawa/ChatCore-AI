import { EXPORT_FORMATS } from "../../lib/memo/constants";
import type { MemoSummary } from "../../lib/memo/types";
import { formatDateTime } from "../../lib/datetime";

type ExportFormat = "markdown" | "json" | "csv";
type ExportScope = "all" | "selected";

type MemoExportModalProps = {
  isExportModalOpen: boolean;
  setIsExportModalOpen: (value: boolean) => void;
  exportFormat: ExportFormat;
  setExportFormat: (value: ExportFormat) => void;
  exportScope: ExportScope;
  setExportScope: (value: ExportScope) => void;
  exportSelectedIds: Set<string>;
  exportSelectedCount: number;
  allVisibleExportSelected: boolean;
  clearExportSelection: () => void;
  selectAllExportMemos: () => void;
  toggleExportMemo: (memoId: string) => void;
  canDownloadExport: boolean;
  handleExport: () => void;
  memos: MemoSummary[];
};

// ── Export modal ──
export function MemoExportModal({
  isExportModalOpen,
  setIsExportModalOpen,
  exportFormat,
  setExportFormat,
  exportScope,
  setExportScope,
  exportSelectedIds,
  exportSelectedCount,
  allVisibleExportSelected,
  clearExportSelection,
  selectAllExportMemos,
  toggleExportMemo,
  canDownloadExport,
  handleExport,
  memos,
}: MemoExportModalProps) {
  return (
        <div className={`memo-export-modal${isExportModalOpen ? " is-visible" : ""}`} aria-hidden={isExportModalOpen ? "false" : "true"}>
          <div className="memo-export-modal__overlay" onClick={() => setIsExportModalOpen(false)}></div>
          <div className="memo-export-modal__content" role="dialog" aria-modal="true" aria-labelledby="exportModalTitle">
            <button type="button" className="memo-export-modal__close" aria-label="閉じる" onClick={() => setIsExportModalOpen(false)}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-export-modal__header">
              <h3 id="exportModalTitle"><i className="bi bi-download"></i>メモをエクスポート</h3>
              <p>保存したメモをファイルとしてダウンロードします。</p>
            </header>
            <div className="memo-export-modal__body">
              <div className="memo-export-section">
                <p className="memo-export-label">フォーマット</p>
                <div className="memo-export-formats">
                  {EXPORT_FORMATS.map((fmt) => (
                    <label
                      key={fmt.value}
                      className={`memo-export-format-option${exportFormat === fmt.value ? " is-active" : ""}`}
                    >
                      <input
                        type="radio"
                        name="export-format"
                        value={fmt.value}
                        checked={exportFormat === fmt.value}
                        onChange={() => setExportFormat(fmt.value as typeof exportFormat)}
                        className="sr-only"
                      />
                      <i className={`bi ${fmt.icon}`}></i>
                      <span>{fmt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="memo-export-section">
                <p className="memo-export-label">対象範囲</p>
                <div className="memo-export-scope">
                  <label className={`memo-export-scope-option${exportScope === "all" ? " is-active" : ""}`}>
                    <input type="radio" name="export-scope" value="all" checked={exportScope === "all"} onChange={() => setExportScope("all")} className="sr-only" />
                    <i className="bi bi-collection"></i>すべてのメモ
                  </label>
                  <label className={`memo-export-scope-option${exportScope === "selected" ? " is-active" : ""}${memos.length === 0 ? " is-disabled" : ""}`}>
                    <input type="radio" name="export-scope" value="selected" checked={exportScope === "selected"} onChange={() => setExportScope("selected")} disabled={memos.length === 0} className="sr-only" />
                    <i className="bi bi-check2-square"></i>
                    {exportSelectedCount > 0 ? `選択中の${exportSelectedCount}件` : "メモを選択"}
                  </label>
                </div>
              </div>
              {exportScope === "selected" && (
                <div className="memo-export-section memo-export-select">
                  <div className="memo-export-select__header">
                    <p className="memo-export-label">メモ</p>
                    <div className="memo-export-select__actions">
                      <button
                        type="button"
                        className="memo-export-select__action"
                        onClick={allVisibleExportSelected ? clearExportSelection : selectAllExportMemos}
                        disabled={memos.length === 0}
                      >
                        {allVisibleExportSelected ? "解除" : "すべて選択"}
                      </button>
                    </div>
                  </div>
                  {memos.length === 0 ? (
                    <p className="memo-export-select__empty">表示中のメモがありません。</p>
                  ) : (
                    <ul className="memo-export-select__list">
                      {memos.map((memo) => {
                        const memoId = String(memo.id);
                        const checked = exportSelectedIds.has(memoId);
                        return (
                          <li key={memoId}>
                            <label className={`memo-export-select__item${checked ? " is-selected" : ""}`}>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleExportMemo(memoId)}
                              />
                              <span className="memo-export-select__content">
                                <span className="memo-export-select__title">{memo.title || "保存したメモ"}</span>
                                <span className="memo-export-select__meta">
                                  {formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || ""}
                                  {memo.collection_name ? ` / ${memo.collection_name}` : ""}
                                </span>
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
              <div className="memo-export-actions">
                <button type="button" className="primary-button" onClick={handleExport} disabled={!canDownloadExport}>
                  <i className="bi bi-download"></i>ダウンロード
                </button>
                <button type="button" className="secondary-button" onClick={() => setIsExportModalOpen(false)}>キャンセル</button>
              </div>
            </div>
          </div>
        </div>
  );
}
