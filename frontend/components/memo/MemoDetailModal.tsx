import React, { useCallback, useEffect, useRef } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import type { MemoEditPayload } from "../../lib/chat_page/mini_chat_runtime";
import { InlineLoading } from "../ui/inline_loading";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { parseMemoText } from "../../lib/memo/utils";
import { formatDateTime } from "../../lib/datetime";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageDetailContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Memo detail modal ──
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
            <button type="button" className="memo-modal__close" aria-label={t("common.close")} onClick={() => { void closeMemoDetail(); }}>
              <i className="bi bi-x-lg"></i>
            </button>
            <header className="memo-modal__header">
              <div className="memo-modal__title-row">
                <div className="memo-modal__title-block">
                  <span id="memoModalTitle" className="sr-only">{detailEditTitle || selectedMemo?.title || t("memo.savedMemo")}</span>
                  {detailPreviewMode ? (
                    <h3 aria-hidden="true">{detailEditTitle || selectedMemo?.title || t("memo.savedMemo")}</h3>
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
                          className={`memo-modal__color-option memo-modal__color-option--compact${(detailEditBackgroundColor || "") === option.value ? " is-active" : ""}`}
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
                    <div className={`memo-modal__autosave-status memo-modal__autosave-status--${detailSaveStatus}`} role="status" aria-live="polite">
                      {detailSaveStatus === "saving" && <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>{t("common.saving")}</>}
                      {detailSaveStatus === "saved" && <><i className="bi bi-check2" aria-hidden="true"></i>{t("memo.saved")}</>}
                      {detailSaveStatus === "idle" && detailHasUnsavedChanges && <><i className="bi bi-clock" aria-hidden="true"></i>{t("memo.awaitingAutosave")}</>}
                      {detailSaveStatus === "idle" && !detailHasUnsavedChanges && <><i className="bi bi-check2" aria-hidden="true"></i>{t("memo.saved")}</>}
                      {detailSaveStatus === "error" && <><i className="bi bi-exclamation-triangle" aria-hidden="true"></i>{detailSaveError || t("memo.autosaveFailed")}</>}
                    </div>
                  </div>
                )}
              </div>
            </header>
            {detailLoading && <div className="memo-history__empty"><InlineLoading label={t("memo.loadingMemo")} className="mx-auto" /></div>}
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
                          <i className="bi bi-code-slash" aria-hidden="true"></i>{t("common.edit")}
                        </button>
                        <button
                          type="button"
                          className={`memo-response-tab${detailPreviewMode ? " is-active" : ""}`}
                          onClick={() => setDetailPreviewMode(true)}
                          disabled={!detailEditAiResponse.trim()}
                        >
                          <i className="bi bi-eye" aria-hidden="true"></i>{t("memo.preview")}
                        </button>
                      </div>
                    </div>
                    {detailPreviewMode ? (
                      <div className="memo-preview-pane memo-modal__preview-pane">
                        {detailEditAiResponse.trim()
                          ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" />
                          : <p className="memo-preview-empty">{t("memo.noPreviewText")}</p>}
                      </div>
                    ) : (
                      <textarea
                        id="memo-detail-ai-response"
                        className="memo-control memo-modal__edit-textarea memo-modal__edit-textarea--response"
                        value={detailEditAiResponse}
                        onChange={(event) => setDetailEditAiResponse(event.target.value)}
                        placeholder={t("memo.writePlaceholder")}
                        required
                      />
                    )}
                  </div>
                </section>
                {isMemoAgentOpen && (
                  <aside className="memo-modal__agent-panel" aria-label={t("memo.askAgent")}>
                    <div className="memo-modal__agent-header">
                      <div className="memo-modal__agent-header-info">
                        <span className="memo-modal__agent-label">
                          <i className="bi bi-stars" aria-hidden="true"></i>
                          Memo Agent
                        </span>
                        <strong>{t("memo.askAgent")}</strong>
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
              </div>
            )}
          </div>
        </div>
  );
}
