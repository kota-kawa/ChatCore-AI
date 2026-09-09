import { EXPORT_FORMATS } from "../../lib/memo/constants";
import { formatDateTime } from "../../lib/datetime";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageListContext,
  useMemoPageModalsContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Export modal ──
// 共通モーダル面（cc-modal）に、形式・範囲・対象メモの選択を節ごとに並べる。
// Shared modal surface (cc-modal) listing the format, scope and memo selection as sections.
export function MemoExportModal() {
  const { memos } = useMemoPageListContext();
  const {
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
  } = useMemoPageModalsContext();
  const { t } = useTranslation();
  const close = () => setIsExportModalOpen(false);
  return (
    <ModalShell
      isOpen={isExportModalOpen}
      onClose={close}
      id="memo-export-modal"
      className="cc-modal memo-modal-scope memo-export-modal"
      labelledBy="exportModalTitle"
    >
      <div className="cc-modal__panel cc-modal__panel--md" tabIndex={-1}>
        <header className="cc-modal__header">
          <div className="cc-modal__heading">
            <h2 className="cc-modal__title" id="exportModalTitle">{t("memo.exportTitle")}</h2>
            <p className="cc-modal__lead">{t("memo.exportDescription")}</p>
          </div>
          <ModalCloseButton label={t("common.close")} onClick={close} />
        </header>

        <div className="cc-modal__body memo-export-modal__body">
          <section className="cc-modal__section memo-export-section">
            <div className="cc-modal__section-head">
              <h3 className="cc-modal__section-title">{t("memo.format")}</h3>
            </div>
            <div className="memo-export-formats">
              {EXPORT_FORMATS.map((fmt) => (
                <label
                  key={fmt.value}
                  className={`memo-export-option${exportFormat === fmt.value ? " is-active" : ""}`}
                >
                  <input
                    type="radio"
                    name="export-format"
                    value={fmt.value}
                    checked={exportFormat === fmt.value}
                    onChange={() => setExportFormat(fmt.value as typeof exportFormat)}
                    className="sr-only"
                  />
                  <i className={`bi ${fmt.icon}`} aria-hidden="true"></i>
                  <span>{fmt.label}</span>
                </label>
              ))}
            </div>
          </section>

          <section className="cc-modal__section memo-export-section">
            <div className="cc-modal__section-head">
              <h3 className="cc-modal__section-title">{t("memo.scope")}</h3>
            </div>
            <div className="memo-export-scope">
              <label className={`memo-export-option${exportScope === "all" ? " is-active" : ""}`}>
                <input type="radio" name="export-scope" value="all" checked={exportScope === "all"} onChange={() => setExportScope("all")} className="sr-only" />
                <i className="bi bi-collection" aria-hidden="true"></i>
                <span>{t("memo.allMemos")}</span>
              </label>
              <label className={`memo-export-option${exportScope === "selected" ? " is-active" : ""}${memos.length === 0 ? " is-disabled" : ""}`}>
                <input type="radio" name="export-scope" value="selected" checked={exportScope === "selected"} onChange={() => setExportScope("selected")} disabled={memos.length === 0} className="sr-only" />
                <i className="bi bi-check2-square" aria-hidden="true"></i>
                <span>{exportSelectedCount > 0 ? t("memo.selectedCount", { count: exportSelectedCount }) : t("memo.selectMemos")}</span>
              </label>
            </div>
          </section>

          {exportScope === "selected" && (
            <section className="cc-modal__section memo-export-section memo-export-select">
              <div className="cc-modal__section-head">
                <h3 className="cc-modal__section-title">{t("memo.heading")}</h3>
                <button
                  type="button"
                  className="cc-modal__btn cc-modal__btn--ghost cc-modal__btn--sm"
                  onClick={allVisibleExportSelected ? clearExportSelection : selectAllExportMemos}
                  disabled={memos.length === 0}
                >
                  {allVisibleExportSelected ? t("memo.remove") : t("memo.selectAll")}
                </button>
              </div>
              {memos.length === 0 ? (
                <p className="memo-export-select__empty">{t("memo.noVisibleMemos")}</p>
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
                            <span className="memo-export-select__title">{memo.title || t("memo.savedMemo")}</span>
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
            </section>
          )}
        </div>

        <footer className="cc-modal__footer">
          <button type="button" className="cc-modal__btn" onClick={close}>{t("common.cancel")}</button>
          <button type="button" className="cc-modal__btn cc-modal__btn--primary" onClick={handleExport} disabled={!canDownloadExport}>
            <i className="bi bi-download" aria-hidden="true"></i>{t("memo.download")}
          </button>
        </footer>
      </div>
    </ModalShell>
  );
}
