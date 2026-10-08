import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useMemoPageBoardContext, useMemoPageDetailContext, useMemoPageListContext } from "../../contexts/memo_page/memo_page_context";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { MemoSelect } from "./MemoSelect";

type MemoDetailOrganizeControlsProps = {
  // 操作の先頭に足す項目。受け取った関数でこのメニューを閉じられる
  // Extra items placed before the actions; the function they receive closes this menu
  renderExtraActions?: (closeMenu: () => void) => ReactNode;
};

export function MemoDetailOrganizeControls({ renderExtraActions }: MemoDetailOrganizeControlsProps) {
  const { t } = useTranslation();
  const { collections } = useMemoPageListContext();
  const { actionLoadingId, handleTogglePin, handleToggleArchive, handleDeleteMemo, openShareModal } = useMemoPageBoardContext();
  const {
    selectedMemo, closeMemoDetail,
    detailEditCollectionId, setDetailEditCollectionId,
    detailEditBackgroundColor, setDetailEditBackgroundColor,
  } = useMemoPageDetailContext();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || ref.current?.contains(target) || target.closest("[role='listbox']")) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  return (
    <details
      ref={ref}
      className="memo-modal__organize"
      open={open}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open || event.defaultPrevented) return;
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        ref.current?.querySelector("summary")?.focus();
      }}
    >
      <summary
        className="memo-modal__icon-btn"
        aria-label={t("memo.moreActions")}
        aria-expanded={open}
        onClick={(event) => { event.preventDefault(); setOpen((previous) => !previous); }}
      >
        <i className="bi bi-three-dots" aria-hidden="true" />
      </summary>
      <div className="memo-modal__organize-panel">
        {selectedMemo && (
          <div className="memo-modal__memo-actions" role="toolbar" aria-label={t("memo.actions")}>
            {renderExtraActions?.(() => setOpen(false))}
            <button
              type="button"
              className={`memo-modal__memo-action${selectedMemo.is_pinned ? " is-active" : ""}`}
              onClick={() => { void handleTogglePin(selectedMemo); }}
              disabled={actionLoadingId === String(selectedMemo.id)}
              aria-pressed={Boolean(selectedMemo.is_pinned)}
            >
              <i className={`bi ${selectedMemo.is_pinned ? "bi-pin-angle-fill" : "bi-pin-angle"}`} aria-hidden="true"></i>
              {selectedMemo.is_pinned ? t("memo.unpin") : t("memo.pin")}
            </button>
            <button
              type="button"
              className="memo-modal__memo-action"
              onClick={() => { void handleToggleArchive(selectedMemo); }}
              disabled={actionLoadingId === String(selectedMemo.id)}
            >
              <i className={`bi ${selectedMemo.is_archived ? "bi-archive-fill" : "bi-archive"}`} aria-hidden="true"></i>
              {selectedMemo.is_archived ? t("memo.unarchive") : t("memo.archive")}
            </button>
            {/* 共有設定は別のモーダル。重ねて開くと Esc やタブ移動を 2 つのモーダルが取り合うので、
                先にこの詳細を閉じる（未保存の編集は閉じる処理が保存する）
                Share settings is another modal. Stacked, the two would fight over Esc and Tab,
                so this detail closes first (closing saves any pending edit) */}
            <button
              type="button"
              className="memo-modal__memo-action"
              onClick={() => { void closeMemoDetail().then(() => openShareModal(selectedMemo)); }}
            >
              <i className="bi bi-share" aria-hidden="true"></i>
              {t("memo.shareSettings")}
            </button>
            <button
              type="button"
              className="memo-modal__memo-action"
              onClick={() => { void handleDeleteMemo(selectedMemo); }}
              disabled={actionLoadingId === String(selectedMemo.id)}
            >
              <i className="bi bi-trash3" aria-hidden="true"></i>
              {t("common.delete")}
            </button>
          </div>
        )}
        {collections.length > 0 && (
          <div className="memo-modal__organize-field">
            <span>{t("memo.collections")}</span>
            <MemoSelect
              id="memo-detail-collection"
              ariaLabel={t("memo.collections")}
              className="memo-select--detail-collection"
              value={String(detailEditCollectionId ?? "")}
              onChange={(value) => setDetailEditCollectionId(value === "" ? null : Number(value))}
              options={[
                { value: "", label: t("memo.noCollection") },
                ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
              ]}
            />
          </div>
        )}
        <div className="memo-modal__organize-field">
          <span>{t("memo.backgroundColor")}</span>
          <div className="memo-modal__color-strip" role="listbox" aria-label={t("memo.backgroundColor")}>
            {MEMO_COLOR_OPTIONS.map((option) => (
              <button
                key={option.label}
                type="button"
                className={`memo-modal__color-option${(detailEditBackgroundColor || "") === option.value ? " is-active" : ""}`}
                style={{ "--palette-color": option.color } as CSSProperties}
                onClick={() => setDetailEditBackgroundColor(option.value || null)}
                role="option"
                aria-selected={(detailEditBackgroundColor || "") === option.value}
                aria-label={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
                data-tooltip={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
              >
                <span />
              </button>
            ))}
          </div>
        </div>
      </div>
    </details>
  );
}
