import React, { useCallback, useEffect, useRef } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import { applyMemoEdits, type MemoEditPayload } from "../../lib/memo/agent_edits";
import { InlineLoading } from "../ui/inline_loading";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { isSelectionCollapsed, shouldBeginEditingFromClick } from "../../lib/memo/detail_click_to_edit";
import { captureMemoEditPosition } from "../../lib/memo/detail_edit_position";
import { parseMemoText } from "../../lib/memo/utils";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import { useMemoDetailEditFocus } from "../../hooks/memo_page/use_memo_detail_edit_focus";
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
  const { textareaRef, titleInputRef, beginEditing } = useMemoDetailEditFocus({
    previewMode: detailPreviewMode,
    setPreviewMode: setDetailPreviewMode,
  });

  // プレビュー面のクリックで編集に入る。リンク・操作部品・ドラッグ選択は通常動作のまま
  // Enter edit mode from a preview click; links, controls and drag selections keep their behaviour
  const handlePreviewClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    const shouldEdit = shouldBeginEditingFromClick({
      target: event.target,
      defaultPrevented: event.defaultPrevented,
      selectionCollapsed: isSelectionCollapsed(),
    });
    if (shouldEdit) {
      beginEditing("body", captureMemoEditPosition(
        event.currentTarget, detailEditAiResponse, event.clientX, event.clientY,
      ));
    }
  }, [beginEditing, detailEditAiResponse]);

  // タイトルもドラッグ選択（コピー）の直後は編集に入らない
  // The title too stays put right after a drag selection (copying)
  const handleTitleClick = useCallback((event: React.MouseEvent<HTMLHeadingElement>) => {
    if (event.defaultPrevented || !isSelectionCollapsed()) return;
    beginEditing("title", captureMemoEditPosition(
      event.currentTarget, detailEditTitle, event.clientX, event.clientY, false,
    ));
  }, [beginEditing, detailEditTitle]);

  const handlePreviewKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" || event.target !== event.currentTarget) return;
    event.preventDefault();
    beginEditing("body");
  }, [beginEditing]);

  // 開いた直後はパネル自体へフォーカスし、操作ボタンを勝手に選ばない
  // Focus the panel itself on open instead of jumping to the first action button
  const getInitialFocus = useCallback(() => panelRef.current, []);

  // 部分置換は実行した時点のエディタ本文へ当てる。提案を待つ間や確認中の手編集も拾えるよう、最新の本文を ref で持つ
  // Partial edits apply to the editor body as of execution; a ref tracks the latest body so manual edits
  // made while the proposal was pending or being confirmed are taken into account
  const latestBodyRef = useRef(detailEditAiResponse);
  useEffect(() => {
    latestBodyRef.current = detailEditAiResponse;
  }, [detailEditAiResponse]);

  // メモエージェントが提案した編集を編集中のタイトル・本文へ反映する（保存は既存の自動保存に任せる）
  // Applies an agent-proposed edit to the editing state; persistence is handled by the existing autosave
  const applyAgentMemoEdit = useCallback(async (edit: MemoEditPayload): Promise<StepExecutionResult> => {
    const applied = edit.kind === "edits"
      ? applyMemoEdits(latestBodyRef.current, edit.edits)
      : { ok: true as const, body: edit.content };
    // サーバーは LLM が読んだ時点の本文で検証済みなので、ここで当たらないのはその後に本文が変わったため。本文もタイトルも変えずに知らせる
    // The server already validated these edits against the body the LLM read, so a failure here means the body
    // changed since then; leave the body and title untouched
    if (!applied.ok) {
      return { ok: false, message: t("memo.agentEditConflict"), needsReplan: false };
    }
    if (!applied.body.trim()) {
      return { ok: false, message: t("memo.emptyEditedBody"), needsReplan: false };
    }
    latestBodyRef.current = applied.body;
    setDetailEditAiResponse(applied.body);
    if (edit.title !== undefined) {
      setDetailEditTitle(edit.title.slice(0, 255));
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
              // マウス向けの近道。キーボードでは編集タブから同じ入力に到達できる
              // A mouse shortcut; keyboard users reach the same input through the edit tab
              <h2
                className="cc-modal__title memo-modal__title memo-modal__title--editable"
                aria-hidden="true"
                onClick={handleTitleClick}
                title={t("memo.clickToEdit")}
              >
                {displayTitle}
              </h2>
            ) : (
              <input
                ref={titleInputRef}
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
                <img src="/static/ChacoMemo.png" alt="" aria-hidden="true" />
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
                  <>
                    <span id="memo-detail-edit-hint" className="memo-modal__edit-hint">{t("memo.clickToEdit")}</span>
                    {/* tabIndex=0 は Enter で編集に入るための停止点。本文内のリンク等とは別の停止点になる
                        tabIndex=0 is the stop that lets Enter start editing; links inside the body remain their own stops */}
                    <div
                      className="memo-modal__preview-pane memo-modal__preview-pane--editable"
                      role="tabpanel"
                      tabIndex={0}
                      aria-describedby="memo-detail-edit-hint"
                      onClick={handlePreviewClick}
                      onKeyDown={handlePreviewKeyDown}
                    >
                      {detailEditAiResponse.trim()
                        ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" />
                        : <p className="memo-preview-empty">{t("memo.noPreviewText")}</p>}
                    </div>
                  </>
                ) : (
                  <textarea
                    ref={textareaRef}
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
                    <span className="memo-modal__agent-header-icon" aria-hidden="true">
                      <img src="/static/ChacoMemo.png" alt="" />
                    </span>
                    <div className="memo-modal__agent-header-info">
                      <strong>{t("memo.agentTitle")}</strong>
                      <span className="memo-modal__agent-label">{t("memo.agentHeaderSubtitle")}</span>
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
                    showModelLabel
                    iconOnlyClearButton={true}
                    agentIconPath="/static/ChacoMemo.png"
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
