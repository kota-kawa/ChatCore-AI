import React, { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import type { MemoEditPayload } from "../../lib/chat_page/mini_chat_runtime";
import { InlineLoading } from "../ui/inline_loading";
import { MEMO_AGENT_QUICK_PROMPTS, MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { parseMemoText } from "../../lib/memo/utils";
import type { Collection, DetailSaveStatus, MemoDetail } from "../../lib/memo/types";
import { formatDateTime } from "../../lib/datetime";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";

type MemoDetailModalProps = {
  selectedMemo: MemoDetail | null;
  isMemoDetailClosing: boolean;
  closeMemoDetail: () => Promise<void>;
  detailEditBackgroundColor: string | null;
  setDetailEditBackgroundColor: Dispatch<SetStateAction<string | null>>;
  detailPreviewMode: boolean;
  setDetailPreviewMode: Dispatch<SetStateAction<boolean>>;
  detailEditTitle: string;
  setDetailEditTitle: Dispatch<SetStateAction<string>>;
  collections: Collection[];
  detailEditCollectionId: number | null;
  setDetailEditCollectionId: Dispatch<SetStateAction<number | null>>;
  detailCopied: boolean;
  copyDetailFullText: () => Promise<void>;
  isMemoAgentOpen: boolean;
  setIsMemoAgentOpen: Dispatch<SetStateAction<boolean>>;
  openMemoAgent: () => Promise<void>;
  detailSaveStatus: DetailSaveStatus;
  detailHasUnsavedChanges: boolean;
  detailSaveError: string;
  detailLoading: boolean;
  detailError: string;
  detailEditAiResponse: string;
  setDetailEditAiResponse: Dispatch<SetStateAction<string>>;
};

// ── Memo detail modal ──
export function MemoDetailModal({
  selectedMemo,
  isMemoDetailClosing,
  closeMemoDetail,
  detailEditBackgroundColor,
  setDetailEditBackgroundColor,
  detailPreviewMode,
  setDetailPreviewMode,
  detailEditTitle,
  setDetailEditTitle,
  collections,
  detailEditCollectionId,
  setDetailEditCollectionId,
  detailCopied,
  copyDetailFullText,
  isMemoAgentOpen,
  setIsMemoAgentOpen,
  openMemoAgent,
  detailSaveStatus,
  detailHasUnsavedChanges,
  detailSaveError,
  detailLoading,
  detailError,
  detailEditAiResponse,
  setDetailEditAiResponse,
}: MemoDetailModalProps) {
  const bodyRef = useRef<HTMLDivElement>(null);

  // メモエージェントが提案した編集を編集中のタイトル・本文へ反映する（保存は既存の自動保存に任せる）
  // Applies an agent-proposed edit to the editing state; persistence is handled by the existing autosave
  const applyAgentMemoEdit = useCallback(async ({ content, title }: MemoEditPayload): Promise<StepExecutionResult> => {
    if (!content.trim()) {
      return { ok: false, message: "編集後の本文が空のため適用できませんでした。", needsReplan: false };
    }
    setDetailEditAiResponse(content);
    if (title !== undefined) {
      setDetailEditTitle(title.slice(0, 255));
    }
    return { ok: true };
  }, [setDetailEditAiResponse, setDetailEditTitle]);

  useEffect(() => {
    if (!isMemoAgentOpen) return;
    if (!window.matchMedia("(max-width: 768px)").matches) return;

    const frameId = window.requestAnimationFrame(() => {
      bodyRef.current?.scrollTo({
        top: 0,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [isMemoAgentOpen]);

  return (
        <div
          className={`memo-modal${selectedMemo && !isMemoDetailClosing ? " is-visible" : ""}${isMemoDetailClosing ? " is-closing" : ""}`}
          aria-hidden={selectedMemo && !isMemoDetailClosing ? "false" : "true"}
        >
          <div className="memo-modal__overlay" onClick={() => { void closeMemoDetail(); }}></div>
          <div
            className={`memo-modal__content${detailEditBackgroundColor ? " has-accent" : ""}`}
            style={detailEditBackgroundColor ? { "--memo-detail-color": detailEditBackgroundColor } as React.CSSProperties : undefined}
            role="dialog"
            aria-modal="true"
            aria-labelledby="memoModalTitle"
          >
            <button type="button" className="memo-modal__close" aria-label="閉じる" onClick={() => { void closeMemoDetail(); }}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-modal__header">
              <div className="memo-modal__title-row">
                <div className="memo-modal__title-block">
                  <span id="memoModalTitle" className="sr-only">{detailEditTitle || selectedMemo?.title || "保存したメモ"}</span>
                  {detailPreviewMode ? (
                    <h3 aria-hidden="true">{detailEditTitle || selectedMemo?.title || "保存したメモ"}</h3>
                  ) : (
                    <input
                      type="text"
                      className="memo-modal__title-input"
                      value={detailEditTitle}
                      onChange={(event) => setDetailEditTitle(event.target.value)}
                      placeholder="空欄なら回答1行目を採用"
                      maxLength={255}
                      aria-label="タイトル"
                    />
                  )}
                  <p className="memo-modal__date">{formatDateTime(selectedMemo?.updated_at || selectedMemo?.created_at) || selectedMemo?.created_at || ""}</p>
                </div>
                {selectedMemo && (
                  <div className="memo-modal__header-actions">
                    {collections.length > 0 && (
                      <MemoSelect
                        id="memo-detail-collection"
                        className="memo-select--detail-collection"
                        value={String(detailEditCollectionId ?? "")}
                        onChange={(value) => setDetailEditCollectionId(value === "" ? null : Number(value))}
                        options={[
                          { value: "", label: "コレクションなし" },
                          ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
                        ]}
                      />
                    )}
                    <div className="memo-modal__color-strip" role="listbox" aria-label="メモの背景色">
                      {MEMO_COLOR_OPTIONS.map((option) => (
                        <button
                          key={option.label}
                          type="button"
                          className={`memo-modal__color-option memo-modal__color-option--compact${(detailEditBackgroundColor || "") === option.value ? " is-active" : ""}`}
                          style={{ "--palette-color": option.color } as React.CSSProperties}
                          onClick={() => setDetailEditBackgroundColor(option.value || null)}
                          role="option"
                          aria-selected={(detailEditBackgroundColor || "") === option.value}
                          aria-label={option.label}
                          data-tooltip={option.label}
                          data-tooltip-placement="bottom"
                        >
                          <span></span>
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      className={`memo-modal__icon-btn${detailCopied ? " is-copied" : ""}`}
                      onClick={() => { void copyDetailFullText(); }}
                      aria-label={detailCopied ? "コピーしました" : "全文をコピー"}
                      data-tooltip={detailCopied ? "コピーしました" : "全文をコピー"}
                      data-tooltip-placement="bottom"
                    >
                      <i className={`bi ${detailCopied ? "bi-check2" : "bi-files"}`} aria-hidden="true"></i>
                    </button>
                    <button
                      type="button"
                      className={`memo-modal__icon-btn memo-modal__agent-toggle${isMemoAgentOpen ? " is-active" : ""}`}
                      onClick={() => {
                        if (isMemoAgentOpen) {
                          setIsMemoAgentOpen(false);
                        } else {
                          void openMemoAgent();
                        }
                      }}
                      aria-label={isMemoAgentOpen ? "メモチャットを閉じる" : "このメモについてAIに質問・編集"}
                      aria-expanded={isMemoAgentOpen}
                      data-tooltip={isMemoAgentOpen ? "メモチャットを閉じる" : "このメモについてAIに質問・編集"}
                      data-tooltip-placement="bottom"
                    >
                      <i className="bi bi-robot" aria-hidden="true"></i>
                    </button>
                    <div className={`memo-modal__autosave-status memo-modal__autosave-status--${detailSaveStatus}`} role="status" aria-live="polite">
                      {detailSaveStatus === "saving" && <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>保存中...</>}
                      {detailSaveStatus === "saved" && <><i className="bi bi-check2" aria-hidden="true"></i>保存済み</>}
                      {detailSaveStatus === "idle" && detailHasUnsavedChanges && <><i className="bi bi-clock" aria-hidden="true"></i>自動保存待ち</>}
                      {detailSaveStatus === "idle" && !detailHasUnsavedChanges && <><i className="bi bi-check2" aria-hidden="true"></i>保存済み</>}
                      {detailSaveStatus === "error" && <><i className="bi bi-exclamation-triangle" aria-hidden="true"></i>{detailSaveError || "自動保存に失敗しました"}</>}
                    </div>
                  </div>
                )}
              </div>
            </header>
            {detailLoading && <div className="memo-history__empty"><InlineLoading label="メモを読み込んでいます..." className="mx-auto" /></div>}
            {!detailLoading && detailError && <div className="memo-history__empty">{detailError}</div>}
            {!detailLoading && selectedMemo && (
              <div
                ref={bodyRef}
                className={`memo-modal__body memo-modal__body--edit${isMemoAgentOpen ? " memo-modal__body--with-agent" : ""}`}
              >
                <section
                  className="memo-modal__section memo-modal__section--full memo-modal__edit-form"
                >
                  <div className="memo-modal__edit-fields">
                    <div className="memo-modal__response-header">
                      <div className="memo-response-tabs">
                        <button
                          type="button"
                          className={`memo-response-tab${!detailPreviewMode ? " is-active" : ""}`}
                          onClick={() => setDetailPreviewMode(false)}
                        >
                          <i className="bi bi-code-slash" aria-hidden="true"></i>編集
                        </button>
                        <button
                          type="button"
                          className={`memo-response-tab${detailPreviewMode ? " is-active" : ""}`}
                          onClick={() => setDetailPreviewMode(true)}
                          disabled={!detailEditAiResponse.trim()}
                        >
                          <i className="bi bi-eye" aria-hidden="true"></i>プレビュー
                        </button>
                      </div>
                    </div>
                    {detailPreviewMode ? (
                      <div className="memo-preview-pane memo-modal__preview-pane">
                        {detailEditAiResponse.trim()
                          ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" />
                          : <p className="memo-preview-empty">プレビューするテキストがありません。</p>}
                      </div>
                    ) : (
                      <textarea
                        id="memo-detail-ai-response"
                        className="memo-control memo-modal__edit-textarea memo-modal__edit-textarea--response"
                        value={detailEditAiResponse}
                        onChange={(event) => setDetailEditAiResponse(event.target.value)}
                        placeholder="メモを入力..."
                        required
                      />
                    )}
                  </div>
                </section>
                {isMemoAgentOpen && (
                  <aside className="memo-modal__agent-panel" aria-label="このメモについてAIに質問・編集">
                    <div className="memo-modal__agent-header">
                      <div className="memo-modal__agent-header-info">
                        <span className="memo-modal__agent-label">
                          <i className="bi bi-stars" aria-hidden="true"></i>
                          Memo Agent
                        </span>
                        <strong>このメモについて質問・編集</strong>
                      </div>
                      <button type="button" className="memo-modal__agent-close" onClick={() => setIsMemoAgentOpen(false)} aria-label="メモチャットを閉じる">
                        <i className="bi bi-x-lg" aria-hidden="true"></i>
                      </button>
                    </div>
                    <MiniChat
                      key={`memo-agent-${selectedMemo.id}`}
                      memoId={selectedMemo.id}
                      storageScope={`memoAgent.${selectedMemo.id}`}
                      quickPrompts={MEMO_AGENT_QUICK_PROMPTS}
                      placeholderTitle="メモ専用エージェント"
                      placeholderDescription="このメモの内容を参照して、要約や質問に加えて、本文の編集も依頼できます。編集は実行ボタンを押したときだけ反映されます。"
                      inputPlaceholder="このメモについて質問・編集を依頼する..."
                      enableActions={false}
                      persistConversation={false}
                      onMemoEdit={applyAgentMemoEdit}
                    />
                  </aside>
                )}
              </div>
            )}
          </div>
        </div>
  );
}
