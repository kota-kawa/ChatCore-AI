import React, {
  type Dispatch,
  type DragEvent,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { createPortal } from "react-dom";

import { parseMemoText } from "../../lib/memo/utils";
import type { Collection, MemoActionMenuPosition, MemoSummary } from "../../lib/memo/types";
import { formatDateTime } from "../../lib/datetime";
import { CollectionBadge } from "./CollectionBadge";
import { MemoListSkeleton } from "./MemoListSkeleton";
import { MemoMarkdown } from "./MemoMarkdown";

type MemoHistoryPanelProps = {
  activeCollection: Collection | null | undefined;
  totalMemoCount: number;
  memoLoadError: Error | undefined;
  memoListLoading: boolean;
  memos: MemoSummary[];
  pinnedMemos: MemoSummary[];
  otherMemos: MemoSummary[];
  openMenuMemoId: string;
  actionLoadingId: string;
  selectedIds: Set<string>;
  copiedMemoId: string;
  copyingMemoId: string;
  canDragMemos: boolean;
  draggedMemoId: string;
  cardRefs: MutableRefObject<Map<string, HTMLElement>>;
  isBulkMode: boolean;
  menuPosition: MemoActionMenuPosition | null;
  canReorderCurrentView: boolean;
  handleMemoDragStart: (event: DragEvent<HTMLElement>, memo: MemoSummary) => void;
  clearMemoDragState: () => void;
  toggleSelectMemo: (memoId: string) => void;
  handleTogglePin: (memo: MemoSummary) => Promise<void>;
  openMemoDetail: (memoId: string | number) => Promise<void>;
  copyMemoFullText: (memo: MemoSummary) => Promise<void>;
  handleToggleArchive: (memo: MemoSummary) => Promise<void>;
  toggleMemoActionMenu: (memoId: string, trigger: HTMLElement) => void;
  openShareModal: (memo: MemoSummary) => Promise<void>;
  setOpenMenuMemoId: Dispatch<SetStateAction<string>>;
  setMenuPosition: Dispatch<SetStateAction<MemoActionMenuPosition | null>>;
  handleDeleteMemo: (memo: MemoSummary) => Promise<void>;
  handleMemoSectionDragOver: (event: DragEvent<HTMLUListElement>, sectionMemos: MemoSummary[]) => void;
  handleMemoDrop: (event: DragEvent<HTMLElement>) => Promise<void>;
};

// ── Memo list ──
export function MemoHistoryPanel({
  activeCollection,
  totalMemoCount,
  memoLoadError,
  memoListLoading,
  memos,
  pinnedMemos,
  otherMemos,
  openMenuMemoId,
  actionLoadingId,
  selectedIds,
  copiedMemoId,
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
  openMemoDetail,
  copyMemoFullText,
  handleToggleArchive,
  toggleMemoActionMenu,
  openShareModal,
  setOpenMenuMemoId,
  setMenuPosition,
  handleDeleteMemo,
  handleMemoSectionDragOver,
  handleMemoDrop,
}: MemoHistoryPanelProps) {
  return (
            <section className="memo-history-panel">
              <div className="memo-panel__header">
                <div className="memo-panel__heading">
                  <h2><i className="bi bi-list-ul" aria-hidden="true"></i>メモ一覧</h2>
                  {activeCollection && <CollectionBadge name={activeCollection.name} color={activeCollection.color || "#6b7280"} />}
                </div>
                <span className="memo-panel__count">
                  <i className="bi bi-journal-text" aria-hidden="true"></i>
                  {totalMemoCount}件
                </span>
              </div>

              {memoLoadError && <div className="memo-history__empty">{memoLoadError.message}</div>}
              {!memoLoadError && memoListLoading && memos.length === 0 && (
                <MemoListSkeleton />
              )}
              {!memoLoadError && !memoListLoading && memos.length === 0 && (
                <div className="memo-history__empty">条件に一致するメモがありません。</div>
              )}

              {memos.length > 0 && (() => {
                const renderMemoCard = (memo: MemoSummary) => {
                  const memoId = String(memo.id);
                  const isMenuOpen = openMenuMemoId === memoId;
                  const isBusy = actionLoadingId === memoId;
                  const isSelected = selectedIds.has(memoId);
                  const isCopied = copiedMemoId === memoId;
                  const isCopying = copyingMemoId === memoId;
                  const canDragMemo = canDragMemos && !isBusy;
                  const isDragging = draggedMemoId === memoId;
                  const displayDate = formatDateTime(memo.updated_at || memo.created_at) || memo.updated_at || memo.created_at || "";

                  return (
                    <li key={memoId}>
                      <article
                        ref={(el) => {
                          if (el) cardRefs.current.set(memoId, el);
                          else cardRefs.current.delete(memoId);
                        }}
                        className={`memo-item${memo.is_archived ? " is-archived" : ""}${memo.is_pinned ? " is-pinned" : ""}${memo.background_color ? " has-accent" : ""}${isSelected ? " is-selected" : ""}${canDragMemo ? " is-reorderable" : ""}${isDragging ? " is-dragging" : ""}`}
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
                              aria-label={`${memo.title || "保存したメモ"}を選択`}
                            />
                          </div>
                        )}

                        {!isBulkMode && (
                          <button
                            type="button"
                            className={`memo-item__pin${memo.is_pinned ? " is-pinned" : ""}`}
                            onClick={() => { void handleTogglePin(memo); }}
                            disabled={isBusy}
                            aria-label={memo.is_pinned ? "ピン留めを解除" : "ピン留め"}
                            aria-pressed={memo.is_pinned}
                            data-tooltip={memo.is_pinned ? "ピン留めを解除" : "ピン留め"}
                            data-tooltip-placement="left"
                          >
                            <i className={`bi ${memo.is_pinned ? "bi-pin-angle-fill" : "bi-pin-angle"}`} aria-hidden="true"></i>
                          </button>
                        )}

                        <button
                          type="button"
                          className="memo-item__open memo-item__open--content"
                          onClick={() => { if (isBulkMode) { toggleSelectMemo(memoId); return; } void openMemoDetail(memoId); }}
                        >
                          <h3 className="memo-item__title">{memo.title || "保存したメモ"}</h3>
                          {memo.excerpt && <MemoMarkdown text={parseMemoText(memo.excerpt)} className="memo-item__excerpt" />}
                        </button>

                        <footer className="memo-item__footer">
                          <div className="memo-item__meta">
                            {memo.collection_name && (
                              <CollectionBadge name={memo.collection_name} color={memo.collection_color || "#6b7280"} />
                            )}
                            {displayDate && (
                              <time className="memo-item__date">
                                <i className="bi bi-clock" aria-hidden="true"></i>
                                {displayDate}
                              </time>
                            )}
                            {memo.is_archived && (
                              <span className="memo-item__archive-badge" aria-label="アーカイブ済み" data-tooltip="アーカイブ済み" data-tooltip-placement="top">
                                <i className="bi bi-archive-fill" aria-hidden="true"></i>
                              </span>
                            )}
                          </div>

                          {!isBulkMode && (
                            <div className="memo-item__actions">
                              <button
                                type="button"
                                className={`memo-item__action${isCopied ? " is-copied" : ""}`}
                                onClick={() => { void copyMemoFullText(memo); }}
                                disabled={isBusy || isCopying}
                                aria-label={isCopied ? "コピーしました" : "全文をコピー"}
                                data-tooltip={isCopied ? "コピーしました" : "全文をコピー"}
                                data-tooltip-placement="top"
                              >
                                <i className={`bi ${isCopied ? "bi-check2" : isCopying ? "bi-arrow-repeat memo-spin" : "bi-files"}`}></i>
                              </button>
                              <button
                                type="button"
                                className="memo-item__action"
                                onClick={(event) => { event.stopPropagation(); void handleToggleArchive(memo); }}
                                disabled={isBusy}
                                aria-label={memo.is_archived ? "アーカイブを解除" : "アーカイブ"}
                                data-tooltip={memo.is_archived ? "アーカイブを解除" : "アーカイブ"}
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
                                  data-tooltip="その他の操作"
                                  data-tooltip-placement="top"
                                  aria-haspopup="true"
                                  aria-expanded={isMenuOpen}
                                  aria-label="その他の操作"
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
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item"
                                      role="menuitem"
                                      onClick={() => { void openShareModal(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-share"></i>
                                      共有設定
                                    </button>
                                    <button
                                      type="button"
                                      className="memo-item__dropdown-item memo-item__dropdown-item--danger"
                                      role="menuitem"
                                      onClick={() => { void handleDeleteMemo(memo); setOpenMenuMemoId(""); setMenuPosition(null); }}
                                    >
                                      <i className="bi bi-trash3"></i>
                                      削除
                                    </button>
                                  </div>,
                                  document.body,
                                )}
                              </div>
                            </div>
                          )}
                        </footer>
                      </article>
                    </li>
                  );
                };

                const showSectionLabels = pinnedMemos.length > 0 && otherMemos.length > 0;

                return (
                  <div className="memo-history__sections">
                    {pinnedMemos.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">
                            <i className="bi bi-pin-angle-fill" aria-hidden="true"></i>ピン留め
                          </h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, pinnedMemos)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {pinnedMemos.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                    {otherMemos.length > 0 && (
                      <section className="memo-history__section">
                        {showSectionLabels && (
                          <h3 className="memo-history__section-label">その他</h3>
                        )}
                        <ul
                          className={`memo-history__list${draggedMemoId && canReorderCurrentView ? " is-drop-ready" : ""}`}
                          onDragOver={(event) => handleMemoSectionDragOver(event, otherMemos)}
                          onDrop={(event) => { void handleMemoDrop(event); }}
                        >
                          {otherMemos.map(renderMemoCard)}
                        </ul>
                      </section>
                    )}
                  </div>
                );
              })()}
            </section>
  );
}
