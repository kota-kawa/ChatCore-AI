import React from "react";
import { createPortal } from "react-dom";

import { isAutoMemoTitle } from "../../lib/memo/auto_title";
import { parseMemoText } from "../../lib/memo/utils";
import type { MemoSummary } from "../../lib/memo/types";
import { daysUntil, formatDate, formatDateTime } from "../../lib/datetime";
import { CollectionBadge } from "./CollectionBadge";
import { HighlightedText } from "./HighlightedText";
import { MemoListSkeleton } from "./MemoListSkeleton";
import { MemoMarkdown } from "./MemoMarkdown";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageBoardContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Memo list ──
export function MemoHistoryPanel() {
  const {
    activeCollection,
    totalMemoCount,
    remainingMemoCount,
    canLoadMoreMemos,
    isLoadingMoreMemos,
    loadMoreMemos,
    memoLoadError,
    memoListLoading,
    memos,
    hasActiveFilters,
    debouncedQuery,
    archiveScope,
    activeCollectionId,
    query,
  } = useMemoPageListContext();
  const {
    pinnedMemos,
    otherMemos,
    openMenuMemoId,
    actionLoadingId,
    selectedIds,
    copyingMemoId,
    canDragMemos,
    draggedMemoId,
    cardRefs,
    isBulkMode,
    menuPosition,
    canReorderCurrentView,
    handleMemoDragStart,
    clearMemoDragState,
    toggleSelectMemo,
    handleTogglePin,
    handleToggleMemoTask,
    openMemoDetail,
    copyMemoFullText,
    handleToggleArchive,
    toggleMemoActionMenu,
    openShareModal,
    setOpenMenuMemoId,
    setMenuPosition,
    handleDeleteMemo,
    handleRestoreMemo,
    handlePurgeMemo,
    handleEmptyTrash,
    emptyingTrash,
    handleMemoSectionDragOver,
    handleMemoDrop,
    showFlash,
  } = useMemoPageBoardContext();
  const { t } = useTranslation();
  // ゴミ箱の一覧は読み取り専用。開く・編集・ピン・並べ替え・共有はできず、戻すか完全に削除するだけ
  // The trash list is read-only: no opening, editing, pinning, reordering or sharing, only restore or delete for good
  const isTrash = archiveScope === "trash";
  // 「ゴミ箱を空にする」は絞り込みに関係なく全件を消すので、一部だけが見えている間は出さない
  // "Empty trash" deletes everything whatever the filter, so it is withheld while only part of the trash is shown
  const canEmptyTrash = isTrash && memos.length > 0 && !query.trim() && activeCollectionId === null;
  return (
            <section className="memo-history-panel">
              <div className="memo-panel__header">
                <div className="memo-panel__heading">
                  <h2>
                    <i className={`bi ${isTrash ? "bi-trash3" : "bi-list-ul"}`} aria-hidden="true"></i>
                    {isTrash ? t("memo.trash") : t("memo.list")}
                  </h2>
                  {activeCollection && <CollectionBadge name={activeCollection.name} color={activeCollection.color || "#6b7280"} />}
                </div>
                <span className="memo-panel__count">
                  <i className="bi bi-journal-text" aria-hidden="true"></i>
                  {t("memo.items", { count: totalMemoCount })}
                </span>
              </div>

              {isTrash && (
                <div className="memo-trash-notice">
                  <p className="memo-trash-notice__text">{t("memo.trashNotice")}</p>
                  {canEmptyTrash && (
                    <button
                      type="button"
                      className="memo-trash-notice__empty"
                      onClick={() => { void handleEmptyTrash(); }}
                      disabled={emptyingTrash}
                    >
                      <i className="bi bi-trash3" aria-hidden="true"></i>
                      {t("memo.emptyTrash")}
                    </button>
                  )}
                </div>
              )}

              {memoLoadError && <div className="memo-history__empty">{memoLoadError.message}</div>}
              {!memoLoadError && memoListLoading && memos.length === 0 && (
                <MemoListSkeleton />
              )}
              {!memoLoadError && !memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty">
                  {isTrash && !query.trim() && activeCollectionId === null
                    ? t("memo.trashEmpty")
                    : hasActiveFilters ? t("memo.noMatchingMemos") : t("memo.noMemosYet")}
                </div>
              )}

              {memos.length > 0 && (() => {
                const renderMemoCard = (memo: MemoSummary) => {
                  const memoId = String(memo.id);
                  const isMenuOpen = openMenuMemoId === memoId;
                  const isBusy = actionLoadingId === memoId;
                  const isSelected = selectedIds.has(memoId);
                  const isCopying = copyingMemoId === memoId;
                  const canDragMemo = canDragMemos && !isBusy;
                  const isDragging = draggedMemoId === memoId;
                  const displayDate = formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || "";
                  const trashDaysLeft = isTrash ? daysUntil(memo.trash_expires_at) : null;

                  return (
                    <li key={memoId}>
                      <article
                        ref={(el) => {
                          if (el) cardRefs.current.set(memoId, el);
                          else cardRefs.current.delete(memoId);
                        }}
                        className={`memo-item${isTrash ? " is-trashed" : ""}${memo.is_archived ? " is-archived" : ""}${memo.is_pinned ? " is-pinned" : ""}${memo.background_color ? " has-accent" : ""}${isSelected ? " is-selected" : ""}${canDragMemo ? " is-reorderable" : ""}${isDragging ? " is-dragging" : ""}`}
                        style={memo.background_color ? { "--memo-card-accent": memo.background_color } as React.CSSProperties : undefined}
                        draggable={canDragMemo}
                        onDragStart={(event) => handleMemoDragStart(event, memo)}
                        onDragEnd={clearMemoDragState}
                        aria-grabbed={draggedMemoId === memoId}
                      >
                        {isBulkMode && (
                          <div className="memo-item__checkbox-wrap">
                            <input
                              type="checkbox"
                              className="memo-bulk-checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelectMemo(memoId)}
                              aria-label={t("memo.selectNamed", { title: memo.title || t("memo.savedMemo") })}
                            />
                          </div>
                        )}

                        {!isBulkMode && !isTrash && (
                          <button
                            type="button"
                            className={`memo-item__pin${memo.is_pinned ? " is-pinned" : ""}`}
                            onClick={() => { void handleTogglePin(memo); }}
                            disabled={isBusy}
                            aria-label={memo.is_pinned ? t("memo.unpin") : t("memo.pin")}
                            aria-pressed={memo.is_pinned}
                            data-tooltip={memo.is_pinned ? t("memo.unpin") : t("memo.pin")}
                            data-tooltip-placement="left"
                          >
                            <i className={`bi ${memo.is_pinned ? "bi-pin-angle-fill" : "bi-pin-angle"}`} aria-hidden="true"></i>
                          </button>
                        )}

                        {/* 中のチェック欄を押せるよう button 要素にはしない（button の中の操作部品は
                            ブラウザによってクリックを受け取れない）。役割とキー操作は button と同じにする
                            Not a button element so the checkboxes inside stay clickable (controls nested in
                            a button do not receive clicks in every browser); role and keys match a button */}
                        <div
                          role={isTrash && !isBulkMode ? undefined : "button"}
                          tabIndex={isTrash && !isBulkMode ? undefined : 0}
                          className="memo-item__open memo-item__open--content"
                          onClick={(event) => {
                            // チェック欄（MemoMarkdown が処理済み）と本文中のリンクは、カードを開く操作にしない
                            // A checkbox (already handled by MemoMarkdown) or a link in the body does not open the card
                            if (event.defaultPrevented || (event.target as Element).closest("a")) return;
                            if (isBulkMode) { toggleSelectMemo(memoId); return; }
                            // ゴミ箱のメモは詳細を取得できない（バックエンドが 404 を返す）ので開かない
                            // A trashed memo has no detail to open (the backend answers 404)
                            if (isTrash) return;
                            void openMemoDetail(memoId);
                          }}
                          onKeyDown={(event) => {
                            if (event.target !== event.currentTarget || (event.key !== "Enter" && event.key !== " ")) return;
                            if (isTrash && !isBulkMode) return;
                            event.preventDefault();
                            if (isBulkMode) { toggleSelectMemo(memoId); return; }
                            void openMemoDetail(memoId);
                          }}
                        >
                          {/* 本文の最初の行がそのままタイトルになっているメモは、題を出すと同じ文が 2 回並ぶ
                              A memo whose title is just the first line of its body would show that line twice */}
                          {!isAutoMemoTitle(memo.title, parseMemoText(memo.excerpt)) && (
                            <h3 className="memo-item__title">
                              {memo.title ? <HighlightedText text={memo.title} query={debouncedQuery} /> : t("memo.savedMemo")}
                            </h3>
                          )}
                          {memo.excerpt && (
                            <MemoMarkdown
                              text={parseMemoText(memo.excerpt)}
                              className="memo-item__excerpt"
                              highlight={debouncedQuery}
                              onToggleTask={isBulkMode || isTrash ? undefined : (index, rendered) => {
                                // 保存中の連打は受け付けない（古い本文をもとに二重に書き換えないため）
                                // Ignore taps while a save is running so two rewrites never start from the same stale body
                                if (isBusy) return false;
                                void handleToggleMemoTask(memo, index, rendered);
                                return true;
                              }}
                            />
                          )}
                        </div>

                        <footer className="memo-item__footer">
                          <div className="memo-item__meta">
                            {memo.collection_name && (
                              <CollectionBadge name={memo.collection_name} color={memo.collection_color || "#6b7280"} />
                            )}
                            {displayDate && (
                              <time className="memo-item__date">
                                <i className="bi bi-clock" aria-hidden="true"></i>
                                {/* 幅の狭い 2 列表示では日付だけにする（CSS が切り替える）
                                    The narrow two-column layout shows the date only (CSS switches) */}
                                <span className="memo-item__date-full">{displayDate}</span>
                                <span className="memo-item__date-short">{formatDate(memo.updated_at || memo.created_at)}</span>
                              </time>
                            )}
                            {trashDaysLeft !== null && (
                              <span className="memo-item__trash-expiry">
                                <i className="bi bi-hourglass-split" aria-hidden="true"></i>
                                {trashDaysLeft <= 0
                                  ? t("memo.trashDeletingSoon")
                                  : t(trashDaysLeft === 1 ? "memo.trashDayLeft" : "memo.trashDaysLeft", { days: trashDaysLeft })}
                              </span>
                            )}
                            {memo.is_archived && (
                              <span className="memo-item__archive-badge" aria-label={t("memo.archived")} data-tooltip={t("memo.archived")} data-tooltip-placement="top">
                                <i className="bi bi-archive-fill" aria-hidden="true"></i>
                              </span>
                            )}
                          </div>

                          {!isBulkMode && !isTrash && (
                            <div className="memo-item__actions">
                              <CopyButton
                                onCopy={() => copyMemoFullText(memo)}
                                label={t("memo.copyFullText")}
                                copiedLabel={t("common.copied")}
                                className="memo-item__action"
                                copiedClassName="is-copied"
                                idleIcon="bi-files"
                                tooltip="data-tooltip"
                                tooltipPlacement="top"
                                busy={isCopying}
                                busyIconClass="bi-arrow-repeat memo-spin"
                                disabled={isBusy}
                              />
                              <button
                                type="button"
                                className="memo-item__action"
                                onClick={(event) => { event.stopPropagation(); void handleToggleArchive(memo); }}
                                disabled={isBusy}
                                aria-label={memo.is_archived ? t("memo.unarchive") : t("memo.archive")}
                                data-tooltip={memo.is_archived ? t("memo.unarchive") : t("memo.archive")}
                                data-tooltip-placement="top"
                              >
                                <i className={`bi ${memo.is_archived ? "bi-archive-fill" : "bi-archive"}`}></i>
                              </button>
                              <div className="memo-item__menu-wrap">
                                <button
                                  type="button"
                                  className={`memo-item__action${isMenuOpen ? " is-active" : ""}`}
                                  onClick={(event) => { toggleMemoActionMenu(memoId, event.currentTarget); }}
                                  disabled={isBusy}
                                  data-tooltip={t("memo.moreActions")}
                                  data-tooltip-placement="top"
                                  aria-haspopup="true"
                                  aria-expanded={isMenuOpen}
                                  aria-label={t("memo.moreActions")}
                                >
                                  <i className="bi bi-three-dots"></i>
                                </button>
                                {isMenuOpen && menuPosition && createPortal(
                                  <div
                                    className="memo-item__dropdown"
                                    role="menu"
                                    style={{
                                      position: "fixed",
                                      top: menuPosition.top,
                                      left: menuPosition.left,
                                      width: menuPosition.width,
                                      maxHeight: menuPosition.maxHeight,
                                    }}
                                  >
                                    {/* スマホの 2 列表示ではカード下のコピー・アーカイブを隠すので、同じ操作をここに置く
                                        The phone two-column layout hides the copy / archive buttons under the card,
                                        so the same actions live here */}
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item memo-item__dropdown-item--compact-only"
                                      role="menuitem"
                                      onClick={() => {
                                        setOpenMenuMemoId("");
                                        setMenuPosition(null);
                                        void copyMemoFullText(memo).then((copied) => { if (copied) showFlash("success", t("common.copied")); });
                                      }}
                                    >
                                      <i className="bi bi-files"></i>
                                      {t("memo.copyFullText")}
                                    </button>
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item memo-item__dropdown-item--compact-only"
                                      role="menuitem"
                                      onClick={() => { void handleToggleArchive(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className={`bi ${memo.is_archived ? "bi-archive-fill" : "bi-archive"}`}></i>
                                      {memo.is_archived ? t("memo.unarchive") : t("memo.archive")}
                                    </button>
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item"
                                      role="menuitem"
                                      onClick={() => { void openShareModal(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-share"></i>
                                      {t("memo.shareSettings")}
                                    </button>
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item memo-item__dropdown-item--danger"
                                      role="menuitem"
                                      onClick={() => { void handleDeleteMemo(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-trash3"></i>
                                      {t("common.delete")}
                                    </button>
                                  </div>,
                                  document.body,
                                )}
                              </div>
                            </div>
                          )}
                        </footer>

                        {isTrash && !isBulkMode && (
                          <div className="memo-item__trash-actions" role="group" aria-label={t("memo.trashItem")}>
                            <button
                              type="button"
                              className="memo-item__trash-action"
                              onClick={() => { void handleRestoreMemo(memo); }}
                              disabled={isBusy}
                            >
                              <i className="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
                              {t("memo.restoreAction")}
                            </button>
                            <button
                              type="button"
                              className="memo-item__trash-action memo-item__trash-action--purge"
                              onClick={() => { void handlePurgeMemo(memo); }}
                              disabled={isBusy}
                            >
                              <i className="bi bi-x-circle" aria-hidden="true"></i>
                              {t("memo.purge")}
                            </button>
                          </div>
                        )}
                      </article>
                    </li>
                  );
                };

                // ゴミ箱は削除した新しい順の 1 つの並び。ピン留めは操作できないので、分けて先頭に出さない
                // The trash is one list, newest deletion first; pins cannot be used there, so they are not split out on top
                const sectionPinned = isTrash ? [] : pinnedMemos;
                const sectionOther = isTrash ? memos : otherMemos;
                const showSectionLabels = sectionPinned.length > 0 && sectionOther.length > 0;

                return (
                  <div className="memo-history__sections">
                    {sectionPinned.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">
                            <i className="bi bi-pin-angle-fill" aria-hidden="true"></i>{t("memo.pinned")}
                          </h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, sectionPinned)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {sectionPinned.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                    {sectionOther.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">{t("memo.other")}</h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, sectionOther)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {sectionOther.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                    {canLoadMoreMemos && (
                      <div className="memo-history__load-more">
                        <button
                          type="button"
                          className="memo-history__load-more-button"
                          onClick={loadMoreMemos}
                          disabled={isLoadingMoreMemos}
                        >
                          <i
                            className={`bi ${isLoadingMoreMemos ? "bi-arrow-repeat memo-spin" : "bi-arrow-down-circle"}`}
                            aria-hidden="true"
                          ></i>
                          {isLoadingMoreMemos ? t("memo.loadingMore") : t("memo.loadMoreMemos")}
                        </button>
                        <span className="memo-history__load-more-hint">
                          {t("memo.remainingCount", { count: remainingMemoCount })}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })()}
            </section>
  );
}
