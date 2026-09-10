import React, { useCallback, useEffect, useRef } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import type { MemoEditPayload } from "../../lib/chat_page/mini_chat_runtime";
import { InlineLoading } from "../ui/inline_loading";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { parseMemoText } from "../../lib/memo/utils";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageDetailContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Memo detail modal ──
// 本文を読む／編集する面。共通モーダル面（cc-modal）の読む面サイズ（xl / reader）に、
// ヘッダー＝タイトル入力と操作・保存状態、本文＝編集・プレビュー（＋エージェント）を置く。
// Reading / editing sheet on the shared modal surface (cc-modal, xl / reader): the header holds
// the title input, actions and save state, while the body holds the editor / preview (+ agent).
export function MemoDetailModal() {
  const { collections } = useMemoPageListContext();
  const {
    selectedMemo,
    isMemoDetailClosing,
    closeMemoDetail,
    detailEditBackgroundColor,
    setDetailEditBackgroundColor,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
    detailEditCollectionId,
    setDetailEditCollectionId,
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
  } = useMemoPageDetailContext();
  const { t } = useTranslation();
  const bodyRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isOpen = Boolean(selectedMemo) && !isMemoDetailClosing;

  // 開いた直後はパネル自体へフォーカスし、操作ボタンを勝手に選ばない
  // Focus the panel itself on open instead of jumping to the first action button
  const getInitialFocus = useCallback(() => panelRef.current, []);

  // メモエージェントが提案した編集を編集中のタイトル・本文へ反映する（保存は既存の自動保存に任せる）
  // Applies an agent-proposed edit to the editing state; persistence is handled by the existing autosave
  const applyAgentMemoEdit = useCallback(async ({ content, title }: MemoEditPayload): Promise<StepExecutionResult> => {
    if (!content.trim()) {
      return { ok: false, message: t("memo.emptyEditedBody"), needsReplan: false };
    }
    setDetailEditAiResponse(content);
    if (title !== undefined) {
      setDetailEditTitle(title.slice(0, 255));
    }
    return { ok: true };
  }, [setDetailEditAiResponse, setDetailEditTitle, t]);

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

  const displayTitle = detailEditTitle || selectedMemo?.title || t("memo.savedMemo");

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={closeMemoDetail}
      id="memo-detail-modal"
      className="cc-modal memo-modal-scope memo-modal"
      labelledBy="memoModalTitle"
      getInitialFocus={getInitialFocus}
    >
      <div
        ref={panelRef}
        className={`cc-modal__panel cc-modal__panel--xl cc-modal__panel--reader memo-modal__content${detailEditBackgroundColor ? " has-accent" : ""}`}
        style={detailEditBackgroundColor ? { "--memo-detail-color": detailEditBackgroundColor } as React.CSSProperties : undefined}
        tabIndex={-1}
      >
        <header className="cc-modal__header memo-modal__header">
          <div className="cc-modal__heading memo-modal__heading">
            <span id="memoModalTitle" className="sr-only">{displayTitle}</span>
            {detailPreviewMode ? (
              <h2 className="cc-modal__title memo-modal__title" aria-hidden="true">{displayTitle}</h2>
            ) : (
              <input
                type="text"
                className="memo-modal__title-input"
                value={detailEditTitle}
                onChange={(event) => setDetailEditTitle(event.target.value)}
                placeholder={t("memo.titleAutoPlaceholder")}
                maxLength={255}
                aria-label={t("memo.titleLabel")}
              />
            )}
          </div>
          {selectedMemo && (
            <div className="memo-modal__header-actions">
              <div className="cc-modal__tabs memo-modal__tabs" role="tablist" aria-label={t("memo.content")}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={!detailPreviewMode}
                  className={`cc-modal__tab${!detailPreviewMode ? " is-active" : ""}`}
                  onClick={() => setDetailPreviewMode(false)}
                >
                  <i className="bi bi-code-slash" aria-hidden="true"></i>{t("common.edit")}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailPreviewMode}
                  className={`cc-modal__tab${detailPreviewMode ? " is-active" : ""}`}
                  onClick={() => setDetailPreviewMode(true)}
                  disabled={!detailEditAiResponse.trim()}
                >
                  <i className="bi bi-eye" aria-hidden="true"></i>{t("memo.preview")}
                </button>
              </div>
              {collections.length > 0 && (
                <MemoSelect
                  id="memo-detail-collection"
                  className="memo-select--detail-collection"
                  value={String(detailEditCollectionId ?? "")}
                  onChange={(value) => setDetailEditCollectionId(value === "" ? null : Number(value))}
                  options={[
                    { value: "", label: t("memo.noCollection") },
                    ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
                  ]}
                />
              )}
              <div className="memo-modal__color-strip" role="listbox" aria-label={t("memo.backgroundColor")}>
                {MEMO_COLOR_OPTIONS.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    className={`memo-modal__color-option${(detailEditBackgroundColor || "") === option.value ? " is-active" : ""}`}
                    style={{ "--palette-color": option.color } as React.CSSProperties}
                    onClick={() => setDetailEditBackgroundColor(option.value || null)}
                    role="option"
                    aria-selected={(detailEditBackgroundColor || "") === option.value}
                    aria-label={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
                    data-tooltip={t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}
                    data-tooltip-placement="bottom"
                  >
                    <span></span>
                  </button>
                ))}
              </div>
              <CopyButton
                onCopy={copyDetailFullText}
                label={t("memo.copyFullText")}
                copiedLabel={t("common.copied")}
                className="memo-modal__icon-btn"
                copiedClassName="is-copied"
                idleIcon="bi-files"
                tooltip="data-tooltip"
                tooltipPlacement="bottom"
              />
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
                aria-label={isMemoAgentOpen ? t("memo.closeAgent") : t("memo.askAgent")}
                aria-expanded={isMemoAgentOpen}
                data-tooltip={isMemoAgentOpen ? t("memo.closeAgent") : t("memo.askAgent")}
                data-tooltip-placement="bottom"
              >
                <i className="bi bi-robot" aria-hidden="true"></i>
              </button>
              <span
                className={`memo-modal__autosave-status memo-modal__autosave-status--${detailSaveStatus}`}
                role="status"
                aria-live="polite"
              >
                {detailSaveStatus === "saving" && <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>{t("common.saving")}</>}
                {detailSaveStatus === "saved" && <><i className="bi bi-check2" aria-hidden="true"></i>{t("memo.saved")}</>}
                {detailSaveStatus === "idle" && detailHasUnsavedChanges && <><i className="bi bi-clock" aria-hidden="true"></i>{t("memo.awaitingAutosave")}</>}
                {detailSaveStatus === "idle" && !detailHasUnsavedChanges && <><i className="bi bi-check2" aria-hidden="true"></i>{t("memo.saved")}</>}
                {detailSaveStatus === "error" && <><i className="bi bi-exclamation-triangle" aria-hidden="true"></i>{detailSaveError || t("memo.autosaveFailed")}</>}
              </span>
            </div>
          )}
          <ModalCloseButton label={t("common.close")} onClick={() => { void closeMemoDetail(); }} />
        </header>

        <div
          ref={bodyRef}
          className={`cc-modal__body memo-modal__body${isMemoAgentOpen ? " memo-modal__body--with-agent" : ""}`}
        >
          {detailLoading && <div className="memo-modal__state"><InlineLoading label={t("memo.loadingMemo")} className="mx-auto" /></div>}
          {!detailLoading && detailError && <div className="memo-modal__state">{detailError}</div>}
          {!detailLoading && selectedMemo && (
            <>
              <section className="memo-modal__edit-form" aria-label={t("memo.content")}>
                {detailPreviewMode ? (
                  <div className="memo-modal__preview-pane" role="tabpanel">
                    {detailEditAiResponse.trim()
                      ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" />
                      : <p className="memo-preview-empty">{t("memo.noPreviewText")}</p>}
                  </div>
                ) : (
                  <textarea
                    id="memo-detail-ai-response"
                    className="memo-modal__edit-textarea"
                    value={detailEditAiResponse}
                    onChange={(event) => setDetailEditAiResponse(event.target.value)}
                    placeholder={t("memo.writePlaceholder")}
                    aria-label={t("memo.content")}
                    required
                  />
                )}
              </section>
              {isMemoAgentOpen && (
                <aside className="memo-modal__agent-panel" aria-label={t("memo.askAgent")}>
                  <div className="memo-modal__agent-header">
                    <div className="memo-modal__agent-header-info">
                      <strong>{t("memo.askAgent")}</strong>
                      <span className="memo-modal__agent-label">Memo Agent</span>
                    </div>
                    <button type="button" className="memo-modal__agent-close" onClick={() => setIsMemoAgentOpen(false)} aria-label={t("memo.closeAgent")}>
                      <i className="bi bi-x-lg" aria-hidden="true"></i>
                    </button>
                  </div>
                  <MiniChat
                    key={`memo-agent-${selectedMemo.id}`}
                    memoId={selectedMemo.id}
                    storageScope={`memoAgent.${selectedMemo.id}`}
                    quickPrompts={[
                      t("memo.agentPromptSummarize"),
                      t("memo.agentPromptKeyPoints"),
                      t("memo.agentPromptProofread"),
                      t("memo.agentPromptRewrite"),
                    ]}
                    placeholderTitle={t("memo.agentTitle")}
                    placeholderDescription={t("memo.agentDescription")}
                    inputPlaceholder={t("memo.agentPlaceholder")}
                    enableActions={false}
                    persistConversation={false}
                    onMemoEdit={applyAgentMemoEdit}
                  />
                </aside>
              )}
            </>
          )}
        </div>
      </div>
    </ModalShell>
  );
}
