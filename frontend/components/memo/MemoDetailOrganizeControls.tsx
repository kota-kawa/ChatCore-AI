// メモ詳細モーダルの「…」メニュー。ピン留め・アーカイブ・共有設定・削除・コレクション・背景色をまとめて操作する。MemoDetailModal から使われる。
// The "more actions" menu of the memo detail modal: pin, archive, share settings, delete, collection, and background color; used by MemoDetailModal.
import { useRef, useState, type CSSProperties, type ReactNode } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { useDismissOnOutsidePress } from "../../hooks/use_dismiss_on_outside_press";
import { useMemoPageBoardContext, useMemoPageDetailContext, useMemoPageListContext } from "../../contexts/memo_page/memo_page_context";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { MemoSelect } from "./MemoSelect";

type MemoDetailOrganizeControlsProps = {
  // 操作の先頭に足す項目。受け取った関数でこのメニューを閉じられる
  // Extra items placed before the actions; the function they receive closes this menu
  renderExtraActions?: (closeMenu: () => void) => ReactNode;
};

// 開閉は state で制御する <details>。外側の押下と Esc で閉じる（外側の押下は閉じるだけで、押した先には届かない）。
// A <details> whose open state is controlled; it closes on Esc or an outside press, which only closes it and never reaches what was pressed.
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

  // メニュー外の押下は閉じるだけにする。body へポータルされる MemoSelect のドロップダウン（listbox）内はメニューの一部として扱う。
  // A press outside the menu only closes it; a MemoSelect dropdown (listbox), portaled to body, counts as part of the menu.
  useDismissOnOutsidePress(
    open,
    (target) => Boolean(ref.current?.contains(target) || (target instanceof Element && target.closest("[role='listbox']"))),
    () => setOpen(false),
  );

  // 閉じると中のボタンが消えるので、フォーカスを開くボタンへ戻す
  // Closing hides the focused item, so return focus to the trigger
  const closeMenu = () => {
    setOpen(false);
    ref.current?.querySelector("summary")?.focus();
  };

  return (
    <details
      ref={ref}
      className="memo-modal__organize"
      open={open}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open || event.defaultPrevented) return;
        event.preventDefault();
        event.stopPropagation();
        closeMenu();
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
      <div className="memo-modal__organize-panel" hidden={!open}>
        {selectedMemo && (
          <div className="memo-modal__memo-actions" role="toolbar" aria-label={t("memo.actions")}>
            {renderExtraActions?.(closeMenu)}
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
