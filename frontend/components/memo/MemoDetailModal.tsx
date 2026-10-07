import type { EditorView } from "@codemirror/view";
import React, { useCallback, useEffect, useId, useRef, useState } from "react";

import { MiniChat } from "../chat_page/MiniChat";
import type { StepExecutionResult } from "../../lib/chat_page/ai_agent";
import { applyMemoEdits, type MemoEditPayload } from "../../lib/memo/agent_edits";
import { InlineLoading } from "../ui/inline_loading";
import { ModalCloseButton } from "../ui/modal_close_button";
import { ModalShell } from "../ui/modal_shell";
import { isImeConfirmKey } from "../../lib/memo/ime";
import { MemoEditor } from "./MemoEditor";
import { MemoFormatToggle, MemoFormatToolbar } from "./MemoFormatToolbar";
import { MemoDetailOrganizeControls } from "./MemoDetailOrganizeControls";
import { CopyButton } from "../ui/copy_button";
import { useTranslation } from "../../contexts/locale_context";
import { useMemoMobileLayout, useMemoViewport } from "../../hooks/memo_page/use_memo_viewport";
import {
  useMemoPageDetailContext,
} from "../../contexts/memo_page/memo_page_context";

// ── Memo detail modal ──
// 本文を読む／編集する面。共通モーダル面（cc-modal）の読む面サイズ（xl / reader）に、
// ヘッダー＝タイトル入力と操作・保存状態、本文＝ライブエディタ（＋エージェント）を置く。
// Reading / editing sheet on the shared modal surface (cc-modal, xl / reader): the header holds
// the title input, actions and save state, while the body holds the live editor (+ agent).
export function MemoDetailModal() {
  const {
    selectedMemo,
    isMemoDetailClosing,
    closeMemoDetail,
    detailEditBackgroundColor,
    detailSourceMode,
    setDetailSourceMode,
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
  const { t } = useTranslation();
  const panelRef = useRef<HTMLDivElement>(null);
  const isOpen = Boolean(selectedMemo) && !isMemoDetailClosing;
  const editorRef = useRef<EditorView | null>(null);

  const viewportStyle = useMemoViewport(isOpen);
  const isMobile = useMemoMobileLayout();
  const [formattingOpen, setFormattingOpen] = useState(false);
  const formatToolbarId = useId();
  const [mobilePane, setMobilePane] = useState<{ memoId: string | number | undefined; agent: boolean }>({ memoId: undefined, agent: false });
  const agentActive = isMemoAgentOpen && mobilePane.memoId === selectedMemo?.id && mobilePane.agent;
  const showMemo = !isMobile || !agentActive;
  const showAgent = !isMobile || agentActive;
  const selectMemo = () => {
    setMobilePane({ memoId: selectedMemo?.id, agent: false });
  };
  const toggleSource = () => {
    selectMemo();
    setDetailSourceMode(!detailSourceMode);
    editorRef.current?.focus();
  };
  const toggleAgent = () => {
    if (isMobile) {
      setMobilePane({ memoId: selectedMemo?.id, agent: !agentActive });
      if (!isMemoAgentOpen) void openMemoAgent();
    } else if (isMemoAgentOpen) setIsMemoAgentOpen(false);
    else void openMemoAgent();
  };

  // Enter in the title moves to the same live editor, except when confirming IME input.
  const handleTitleKeyDown = useCallback((event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || isImeConfirmKey(event)) return;
    event.preventDefault();
    setMobilePane({ memoId: selectedMemo?.id, agent: false });
    editorRef.current?.focus();
  }, [selectedMemo?.id]);

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
            <input
              type="text"
              className="memo-modal__title-input"
              value={detailEditTitle}
              onChange={(event) => setDetailEditTitle(event.target.value)}
              onKeyDown={handleTitleKeyDown}
              placeholder={t("memo.titleAutoPlaceholder")}
              maxLength={255}
              aria-label={t("memo.titleLabel")}
            />
          </div>
          {selectedMemo && (
            <div className="memo-modal__header-actions">
              <div className="cc-modal__tabs memo-modal__tabs" role="group" aria-label={t("memo.content")}>
                <button
                  type="button"
                  aria-pressed={detailSourceMode}
                  className={`cc-modal__tab${detailSourceMode ? " is-active" : ""}`}
                  onClick={toggleSource}
                  aria-label={t("memo.markdownSource")}
                  title={t("memo.markdownSource")}
                >
                  <i className="bi bi-code-slash" aria-hidden="true"></i>{t("memo.markdownSourceShort")}
                </button>
                <div className="memo-modal__panes" role={isMobile ? "tablist" : undefined} aria-label={isMobile ? t("memo.content") : undefined}>
                  {isMobile && (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={showMemo}
                      className={`cc-modal__tab${showMemo ? " is-active" : ""}`}
                      onClick={selectMemo}
                    >
                      <i className="bi bi-journal-text" aria-hidden="true"></i>{t("nav.memo")}
                    </button>
                  )}
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
          {isMobile && showMemo && (
            <MemoFormatToggle
              open={formattingOpen}
              onToggle={() => setFormattingOpen((open) => !open)}
              toolbarId={formatToolbarId}
              className="memo-modal__format-toggle"
            />
          )}
          <ModalCloseButton label={t("common.close")} onClick={() => { void closeMemoDetail(); }} />
        </header>

        <div
          className={`cc-modal__body memo-modal__body${isMemoAgentOpen ? " memo-modal__body--with-agent" : ""}`}
        >
          {detailLoading && <div className="memo-modal__state"><InlineLoading label={t("memo.loadingMemo")} className="mx-auto" /></div>}
          {!detailLoading && detailError && <div className="memo-modal__state">{detailError}</div>}
          {!detailLoading && selectedMemo && (
            <>
              <section className="memo-modal__edit-form" aria-label={t("memo.content")} hidden={!showMemo}>
                <MemoEditor
                  key={selectedMemo.id}
                  editorRef={editorRef}
                  id="memo-detail-ai-response"
                  value={detailEditAiResponse}
                  onChange={setDetailEditAiResponse}
                  sourceMode={detailSourceMode}
                  label={t("memo.content")}
                  placeholder={t("memo.writePlaceholder")}
                />
                <MemoFormatToolbar id={formatToolbarId} editorRef={editorRef} hidden={isMobile && !formattingOpen} />
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
