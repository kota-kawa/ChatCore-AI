import React, { useCallback, useEffect, useRef, useState } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import { applyMemoEdits, type MemoEditPayload } from "../../lib/memo/agent_edits";
import { InlineLoading } from "../ui/inline_loading";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { isSelectionCollapsed, shouldBeginEditingFromClick } from "../../lib/memo/detail_click_to_edit";
import { toggleTaskMarker, type RenderedTask } from "../../lib/memo/list_editing";
import { captureMemoEditPosition } from "../../lib/memo/detail_edit_position";
import { isImeConfirmKey } from "../../lib/memo/textarea_edit";
import { parseMemoText } from "../../lib/memo/utils";
import { MemoFormatToolbar } from "./MemoFormatToolbar";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoDetailOrganizeControls } from "./MemoDetailOrganizeControls";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import { useMemoDetailEditFocus } from "../../hooks/memo_page/use_memo_detail_edit_focus";
import { useMemoMobileLayout, useMemoViewport } from "../../hooks/memo_page/use_memo_viewport";
import {
  useMemoPageBoardContext,
  useMemoPageDetailContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Memo detail modal ──
// 本文を読む／編集する面。共通モーダル面（cc-modal）の読む面サイズ（xl / reader）に、
// ヘッダー＝タイトル入力と操作・保存状態、本文＝編集・プレビュー（＋エージェント）を置く。
// Reading / editing sheet on the shared modal surface (cc-modal, xl / reader): the header holds
// the title input, actions and save state, while the body holds the editor / preview (+ agent).
export function MemoDetailModal() {
  const {
    selectedMemo,
    isMemoDetailClosing,
    closeMemoDetail,
    detailEditBackgroundColor,
    detailPreviewMode,
    setDetailPreviewMode,
    detailEditTitle,
    setDetailEditTitle,
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
  const { actionLoadingId, handleTogglePin, handleToggleArchive, handleDeleteMemo, openShareModal } = useMemoPageBoardContext();
  const { t } = useTranslation();
  const bodyRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isOpen = Boolean(selectedMemo) && !isMemoDetailClosing;
  const { textareaRef, titleInputRef, beginEditing, rememberBodyScroll } = useMemoDetailEditFocus({
    previewMode: detailPreviewMode,
    setPreviewMode: setDetailPreviewMode,
    bodySource: detailEditAiResponse,
    memoId: selectedMemo?.id,
  });

  const viewportStyle = useMemoViewport(isOpen);
  const isMobile = useMemoMobileLayout();
  const [mobilePane, setMobilePane] = useState<{ memoId: string | number | undefined; agent: boolean }>({ memoId: undefined, agent: false });
  const agentActive = isMemoAgentOpen && mobilePane.memoId === selectedMemo?.id && mobilePane.agent;
  const showMemo = !isMobile || !agentActive;
  const showAgent = !isMobile || agentActive;
  const selectMemoMode = (preview: boolean) => {
    setMobilePane({ memoId: selectedMemo?.id, agent: false });
    setDetailPreviewMode(preview);
  };
  const toggleAgent = () => {
    if (isMobile) {
      setMobilePane({ memoId: selectedMemo?.id, agent: !agentActive });
      if (!isMemoAgentOpen) void openMemoAgent();
    } else if (isMemoAgentOpen) setIsMemoAgentOpen(false);
    else void openMemoAgent();
  };

  // プレビューのチェック欄をその場で切り替える（保存は既存の自動保存に任せる）
  // Tick a checklist box right in the preview; the existing autosave persists it
  const toggleDetailTask = useCallback((index: number, rendered: RenderedTask[]) => {
    const next = toggleTaskMarker(detailEditAiResponse, index, rendered);
    if (next === null) return false;
    setDetailEditAiResponse(next);
    return true;
  }, [detailEditAiResponse, setDetailEditAiResponse]);

  // タイトルで Enter を押したら本文へ進む（日本語変換の確定の Enter は除く）
  // Enter in the title moves on to the body (except the Enter that confirms an IME conversion)
  const handleTitleKeyDown = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || isImeConfirmKey(event)) return;
    event.preventDefault();
    setMobilePane({ memoId: selectedMemo?.id, agent: false });
    setDetailPreviewMode(false);
    const textarea = textareaRef.current;
    if (textarea && !textarea.closest("[hidden]")) textarea.focus();
    else window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, [selectedMemo?.id, setDetailPreviewMode, textareaRef]);

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
    setMobilePane({ memoId: selectedMemo?.id, agent: false });
    beginEditing("title", captureMemoEditPosition(
      event.currentTarget, detailEditTitle, event.clientX, event.clientY, false,
    ));
  }, [beginEditing, detailEditTitle, selectedMemo?.id]);

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

  const displayTitle = detailEditTitle || selectedMemo?.title || t("memo.savedMemo");

  return (
    <ModalShell
      isOpen={isOpen}
      onClose={closeMemoDetail}
      id="memo-detail-modal"
      className="cc-modal memo-modal-scope memo-modal"
      labelledBy="memoModalTitle"
      getInitialFocus={getInitialFocus}
      style={viewportStyle}
    >
      <div
        ref={panelRef}
        className={`cc-modal__panel cc-modal__panel--xl cc-modal__panel--reader memo-modal__content${detailEditBackgroundColor ? " has-accent" : ""}`}
        style={{
          ...(detailEditBackgroundColor ? { "--memo-detail-color": detailEditBackgroundColor } : null),
        } as React.CSSProperties}
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
                onKeyDown={handleTitleKeyDown}
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
                  aria-selected={!detailPreviewMode && showMemo}
                  className={`cc-modal__tab${!detailPreviewMode && showMemo ? " is-active" : ""}`}
                  onClick={() => selectMemoMode(false)}
                >
                  <i className="bi bi-code-slash" aria-hidden="true"></i>{t("common.edit")}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={detailPreviewMode && showMemo}
                  className={`cc-modal__tab${detailPreviewMode && showMemo ? " is-active" : ""}`}
                  onClick={() => selectMemoMode(true)}
                  disabled={!detailEditAiResponse.trim()}
                >
                  <i className="bi bi-eye" aria-hidden="true"></i>{t("memo.preview")}
                </button>
              <button
                type="button"
                className={`memo-modal__icon-btn memo-modal__agent-toggle${isMemoAgentOpen && showAgent ? " is-active" : ""}`}
                onClick={toggleAgent}
                aria-label={!isMobile && isMemoAgentOpen ? t("memo.closeAgent") : t("memo.askAgent")}
                role={isMobile ? "tab" : undefined}
                aria-selected={isMobile ? agentActive : undefined}
                aria-expanded={isMobile ? undefined : isMemoAgentOpen}
                data-tooltip={!isMobile && isMemoAgentOpen ? t("memo.closeAgent") : t("memo.askAgent")}
                data-tooltip-placement="bottom"
              >
                <img src="/static/ChacoMemo.png" alt="" aria-hidden="true" />
              </button>
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
              <MemoDetailOrganizeControls />
            </div>
          )}
          {/* 保存状態は操作列と分け、画面幅や表示中の面に関係なく見える位置に置く。
              Keep save feedback visible independently of the controls and active pane. */}
          {selectedMemo && (
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
              <section className="memo-modal__edit-form" aria-label={t("memo.content")} hidden={!showMemo}>
                {detailPreviewMode && (
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
                        ? <MemoMarkdown text={parseMemoText(detailEditAiResponse)} className="memo-preview-content" onToggleTask={toggleDetailTask} />
                        : <p className="memo-preview-empty">{t("memo.noPreviewText")}</p>}
                    </div>
                  </>
                )}
                {/* プレビュー中も外さずに隠すだけにする。外すとカーソル位置と「元に戻す」の履歴が消える。
                    key でメモごとに作り直し、履歴が別のメモへ持ち越されないようにする
                    Hidden rather than unmounted during the preview: unmounting drops the caret and the
                    undo history. The key remounts it per memo so the history never carries over */}
                <textarea
                  key={selectedMemo.id}
                  ref={textareaRef}
                  id="memo-detail-ai-response"
                  className="memo-modal__edit-textarea"
                  data-memo-editor=""
                  hidden={detailPreviewMode}
                  value={detailEditAiResponse}
                  onChange={(event) => setDetailEditAiResponse(event.target.value)}
                  onScroll={rememberBodyScroll}
                  placeholder={t("memo.writePlaceholder")}
                  aria-label={t("memo.content")}
                  required
                />
                {!detailPreviewMode && <MemoFormatToolbar textareaRef={textareaRef} />}
                {/* 読んでいる間は、一覧に戻らなくてもこのメモを整理できる操作を同じ位置に出す
                    While reading, the same slot offers the actions that organise this memo without
                    going back to the list */}
                {detailPreviewMode && (
                  <div className="memo-modal__memo-actions" role="toolbar" aria-label={t("memo.actions")}>
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
              </section>
              {isMemoAgentOpen && (
                <aside className="memo-modal__agent-panel" aria-label={t("memo.askAgent")} hidden={!showAgent}>
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
