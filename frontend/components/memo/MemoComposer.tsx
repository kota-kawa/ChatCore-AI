import React, { useCallback, useEffect, useRef, useState } from "react";

import { useMemoMobileLayout, useMemoViewport } from "../../hooks/memo_page/use_memo_viewport";
import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { isImeConfirmKey } from "../../lib/memo/ime";
import { MemoFormatToggle, MemoFormatToolbar } from "./MemoFormatToolbar";
import { MemoEditor } from "./MemoEditor";
import { MemoSelect } from "./MemoSelect";
import { ModalShell } from "../ui/modal_shell";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageComposerContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

const OUTSIDE_CLICK_EXEMPT_SELECTOR = [
  "[role='listbox']",
  "[role='menu']",
  ".modal-base",
  ".cc-alert-modal",
  "[data-memo-composer-trigger]",
  "[data-memo-composing]",
].join(", ");

function hasMemoBodyContent(value: string): boolean {
  return value.split(/\r?\n/u).some((line) => {
    const content = line.replace(/^\s*(?:>\s*)*/u, "").trim();
    if (!content) return false;
    return !/^(?:[-*+]|\d{1,9}[.)])\s+\[[ xX]\]\s*$/u.test(content);
  });
}

function pathHasSelector(path: EventTarget[], selector: string): boolean {
  return path.some((item) => item instanceof Element && item.matches(selector));
}

// ── Quick capture ──
export function MemoComposer() {
  const { collections } = useMemoPageListContext();
  const {
    composeIsExpanded,
    openTextComposer,
    openChecklistComposer,
    openComposePalette,
    handleSubmitMemo,
    formState,
    handleFormChange,
    sourceMode,
    setSourceMode,
    composeEditorRef,
    composeFocusRequest,
    setFormState,
    aiSuggesting,
    handleAiSuggest,
    isComposePaletteOpen,
    submitting,
    setIsComposeExpanded,
    setIsComposePaletteOpen,
    hasComposeDraft,
  } = useMemoPageComposerContext();
  const { locale, t } = useTranslation();
  const english = locale === "en";
  const isMobileLayout = useMemoMobileLayout();
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [formattingOpen, setFormattingOpen] = useState(false);
  const [mobileDraftDismissed, setMobileDraftDismissed] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const paletteTriggerRef = useRef<HTMLButtonElement>(null);
  const collapsedTextButtonRef = useRef<HTMLButtonElement>(null);
  const autoSubmittedBodyRef = useRef<string | null>(null);
  const lastObservedBodyRef = useRef(formState.ai_response);
  const mobileReturnFocusRef = useRef<HTMLElement | null>(null);
  const mobileInitialFocusRef = useRef<"body" | "palette">("body");
  const wasMobileDialogOpenRef = useRef(false);

  const hasBody = hasMemoBodyContent(formState.ai_response);
  const showExpandedComposer = composeIsExpanded && !(isMobileLayout && mobileDraftDismissed);
  const mobileDialogOpen = isMobileLayout && showExpandedComposer;
  const viewportStyle = useMemoViewport(mobileDialogOpen, true);

  // The floating New button calls the controller directly, so it cannot clear the local
  // mobile dismissal state through the inline trigger handlers. Capture its native click first.
  useEffect(() => {
    const handleComposerTriggerClick = (event: MouseEvent) => {
      const trigger = event.composedPath().find(
        (item): item is HTMLElement => item instanceof HTMLElement && item.matches("[data-memo-composer-trigger]"),
      );
      if (!trigger) return;
      mobileReturnFocusRef.current = trigger;
      mobileInitialFocusRef.current = "body";
      setMobileDraftDismissed(false);
    };
    document.addEventListener("click", handleComposerTriggerClick, true);
    return () => document.removeEventListener("click", handleComposerTriggerClick, true);
  }, []);

  // Native click paths retain the original ancestors even if React replaces the clicked node
  // before the document listener runs. This also covers the persistent inline trigger and the
  // expanded composer portaled into the mobile dialog.
  useEffect(() => {
    if (!composeIsExpanded || isMobileLayout || submitting) return undefined;
    const handleOutsideClick = (event: MouseEvent) => {
      const path = event.composedPath();
      if (pathHasSelector(path, "[data-memo-composer-root]")) return;
      if (pathHasSelector(path, OUTSIDE_CLICK_EXEMPT_SELECTOR)) return;

      if (hasBody && autoSubmittedBodyRef.current !== formState.ai_response) {
        autoSubmittedBodyRef.current = formState.ai_response;
        formRef.current?.requestSubmit();
      } else if (!hasComposeDraft) {
        setIsComposeExpanded(false);
        setIsComposePaletteOpen(false);
        setIsMoreOpen(false);
      }
    };
    document.addEventListener("click", handleOutsideClick);
    return () => document.removeEventListener("click", handleOutsideClick);
  }, [composeIsExpanded, formState.ai_response, hasBody, hasComposeDraft, isMobileLayout, setIsComposeExpanded, setIsComposePaletteOpen, submitting]);

  useEffect(() => {
    if (!mobileDialogOpen) return undefined;
    document.body.classList.add("memo-compose-open");
    return () => document.body.classList.remove("memo-compose-open");
  }, [mobileDialogOpen]);

  useEffect(() => {
    if (lastObservedBodyRef.current !== formState.ai_response) {
      lastObservedBodyRef.current = formState.ai_response;
      autoSubmittedBodyRef.current = null;
    }
  }, [formState.ai_response]);

  useEffect(() => {
    if (!hasComposeDraft && !isComposePaletteOpen) setIsMoreOpen(false);
  }, [hasComposeDraft, isComposePaletteOpen]);

  useEffect(() => {
    if (!wasMobileDialogOpenRef.current || mobileDialogOpen) {
      wasMobileDialogOpenRef.current = mobileDialogOpen;
      return;
    }
    wasMobileDialogOpenRef.current = false;

    if (isMobileLayout && !showExpandedComposer) {
      const returnTarget = mobileReturnFocusRef.current?.isConnected
        ? mobileReturnFocusRef.current
        : collapsedTextButtonRef.current;
      returnTarget?.focus({ preventScroll: true });
      return;
    }
    if (!isMobileLayout && showExpandedComposer) {
      composeEditorRef.current?.focus();
    }
  }, [composeEditorRef, isMobileLayout, mobileDialogOpen, showExpandedComposer]);

  // 欄の外を押したら書き終えたものとして扱う。内容があれば一度だけ自動保存し、
  // チェック欄の記号だけなら空の項目を作らず、書きかけを控えたまま畳めるようにする。
  // A body saves once on outside click. A checklist marker alone stays a draft rather than
  // creating an empty task, and the mobile backdrop uses the same save-or-preserve rule.
  const dismissMobileComposer = useCallback(() => {
    setIsComposePaletteOpen(false);
    setIsMoreOpen(false);
    if (hasBody) {
      if (autoSubmittedBodyRef.current !== formState.ai_response) {
        autoSubmittedBodyRef.current = formState.ai_response;
        formRef.current?.requestSubmit();
      }
      return;
    }

    if (hasComposeDraft) {
      setMobileDraftDismissed(true);
      return;
    }
    setIsComposeExpanded(false);
  }, [formState.ai_response, hasBody, hasComposeDraft, setIsComposeExpanded, setIsComposePaletteOpen]);

  const rememberOpenTarget = (event: React.MouseEvent<HTMLElement>, target: "body" | "palette") => {
    mobileReturnFocusRef.current = event.currentTarget;
    mobileInitialFocusRef.current = target;
    setMobileDraftDismissed(false);
  };

  const handleOpenText = (event: React.MouseEvent<HTMLButtonElement>) => {
    rememberOpenTarget(event, "body");
    setSourceMode(true);
    openTextComposer();
  };

  const handleOpenChecklist = (event: React.MouseEvent<HTMLButtonElement>) => {
    rememberOpenTarget(event, "body");
    setSourceMode(true);
    openChecklistComposer();
  };

  const handleOpenCollapsedPalette = (event: React.MouseEvent<HTMLButtonElement>) => {
    rememberOpenTarget(event, "palette");
    setIsMoreOpen(true);
    openComposePalette();
  };

  const handleExpandedPaletteToggle = (event: React.MouseEvent<HTMLButtonElement>) => {
    rememberOpenTarget(event, "palette");
    setIsMoreOpen(!isComposePaletteOpen);
    openComposePalette();
  };

  const handleMoreToggle = (event: React.SyntheticEvent<HTMLDetailsElement>) => {
    const nextOpen = event.currentTarget.open;
    setIsMoreOpen(nextOpen);
    if (!nextOpen && isComposePaletteOpen) setIsComposePaletteOpen(false);
  };

  const getMobileInitialFocus = useCallback(() => {
    if (mobileInitialFocusRef.current === "palette") {
      return paletteTriggerRef.current ?? composeEditorRef.current?.contentDOM ?? titleRef.current;
    }
    return composeEditorRef.current?.contentDOM ?? titleRef.current ?? paletteTriggerRef.current;
  }, [composeEditorRef]);

  const handleCloseComposer = () => {
    setFormState({ ai_response: "", title: "", collection_id: null, background_color: null });
    setSourceMode(true);
    setIsComposeExpanded(false);
    setIsComposePaletteOpen(false);
    setIsMoreOpen(false);
    setMobileDraftDismissed(false);
  };

  // タイトルで Enter を押したら保存ではなく本文へ進む（日本語変換の確定の Enter は除く）
  // Enter in the title moves on to the body instead of saving (except the Enter that confirms an IME conversion)
  const handleTitleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || isImeConfirmKey(event)) return;
    event.preventDefault();
    composeEditorRef.current?.focus();
  };

  const renderCollapsedComposer = () => (
    <div className="memo-quick-capture__collapsed" aria-label={t("memo.new")}>
      <button
        ref={collapsedTextButtonRef}
        type="button"
        className="memo-quick-capture__text-button"
        onClick={handleOpenText}
        aria-label={english ? "Create a text memo" : "テキストメモを作成"}
      >
        <span>{english ? "Write a memo…" : "メモを入力..."}</span>
      </button>
      <div className="memo-quick-capture__shortcuts" role="toolbar" aria-label={english ? "New memo type" : "新しいメモの種類"}>
        <button
          type="button"
          className="memo-quick-capture__shortcut-btn"
          onClick={handleOpenChecklist}
          aria-label={english ? "Create a checklist" : "チェックリストを作成"}
          data-tooltip={english ? "Checklist" : "チェックリスト"}
          data-tooltip-placement="top"
        >
          <i className="bi bi-check2-square" aria-hidden="true"></i>
        </button>
        <button
          type="button"
          className="memo-quick-capture__shortcut-btn"
          onClick={handleOpenCollapsedPalette}
          aria-label={english ? "Choose a color" : "色を選択"}
          data-tooltip={english ? "Choose a color" : "色を選択"}
          data-tooltip-placement="top"
        >
          <i className="bi bi-palette" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  );

  const renderExpandedComposer = (sectionId: string, mobile: boolean) => (
    <form
      ref={formRef}
      method="post"
      className="memo-form memo-form--quick"
      onSubmit={handleSubmitMemo}
      style={formState.background_color ? { "--memo-compose-color": formState.background_color } as React.CSSProperties : undefined}
    >
      <div className="memo-quick-capture__header">
        <div className="memo-quick-capture__heading">
          <i className="bi bi-pencil-square" aria-hidden="true"></i>
          <h2 id={`${sectionId}-title`}>{t("memo.new")}</h2>
          <span className="memo-quick-capture__mode-label">{t(sourceMode ? "memo.editingMarkdown" : "memo.preview")}</span>
        </div>
        <div className="form-group memo-quick-capture__title-group">
          <label htmlFor={`${sectionId}-memo-title`} className="sr-only">{english ? "Title" : "タイトル"}</label>
          <input
            ref={titleRef}
            id={`${sectionId}-memo-title`}
            name="title"
            data-agent-id="memo.title"
            type="text"
            className="memo-control memo-quick-capture__title-input"
            value={formState.title}
            onChange={handleFormChange}
            onKeyDown={handleTitleKeyDown}
            maxLength={255}
            placeholder={english ? "Title (optional)" : "タイトル（任意）"}
            autoFocus={!hasComposeDraft && !mobile}
          />
        </div>

        <div className="memo-response-header memo-quick-capture__response-header">
          <label htmlFor={`${sectionId}-memo-response`} className="sr-only">{english ? "Content" : "本文"}</label>
          <button
            type="button"
            className={`memo-response-tab${!sourceMode ? " is-active" : ""}`}
            aria-label={t(sourceMode ? "memo.preview" : "common.edit")}
            onClick={() => {
              if (sourceMode) {
                setSourceMode(false);
                setFormattingOpen(false);
              } else setSourceMode(true);
            }}
          >
            <i className={`bi ${sourceMode ? "bi-eye" : "bi-pencil"}`} aria-hidden="true"></i>
            {t(sourceMode ? "memo.preview" : "common.edit")}
          </button>
          {mobile && sourceMode && (
            <MemoFormatToggle
              open={formattingOpen}
              onToggle={() => setFormattingOpen((open) => !open)}
              toolbarId={`${sectionId}-formatting`}
            />
          )}
        </div>

        <details
          className="memo-quick-capture__more"
          open={isMoreOpen || isComposePaletteOpen}
          onToggle={handleMoreToggle}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || event.defaultPrevented || !event.currentTarget.open) return;
            event.preventDefault();
            event.stopPropagation();
            setIsMoreOpen(false);
            setIsComposePaletteOpen(false);
            event.currentTarget.querySelector("summary")?.focus();
          }}
        >
          <summary><i className="bi bi-sliders" aria-hidden="true"></i>{t("memo.other")}</summary>
          <div className="memo-quick-capture__more-panel">
            <div className="memo-quick-capture__bottom-row">
              {collections.length > 0 && (
                <MemoSelect
                  id={`${sectionId}-collection`}
                  className="memo-select--quick"
                  value={String(formState.collection_id ?? "")}
                  onChange={(value) => setFormState((prev) => ({ ...prev, collection_id: value === "" ? null : Number(value) }))}
                  options={[
                    { value: "", label: english ? "No collection" : "コレクションなし" },
                    ...collections.map((collection) => ({ value: String(collection.id), label: collection.name })),
                  ]}
                />
              )}
              <button
                type="button"
                className={`memo-ai-suggest-btn${aiSuggesting ? " is-loading" : ""}`}
                onClick={() => { void handleAiSuggest(); }}
                disabled={aiSuggesting || !formState.ai_response.trim()}
                data-tooltip={english ? "Suggest a title with AI" : "AIがタイトルを提案"}
                data-tooltip-placement="top"
              >
                {aiSuggesting
                  ? <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>{english ? "Suggesting…" : "提案中..."}</>
                  : <><i className="bi bi-stars" aria-hidden="true"></i>{english ? "AI title" : "AIタイトル"}</>}
              </button>
              <div className="memo-compose-palette">
                <button
                  ref={paletteTriggerRef}
                  type="button"
                  className={`memo-compose-palette__trigger${isComposePaletteOpen ? " is-active" : ""}`}
                  onClick={handleExpandedPaletteToggle}
                  aria-label={english ? "Choose a color" : "色を選択"}
                  aria-expanded={isComposePaletteOpen}
                  data-tooltip={english ? "Choose a color" : "色を選択"}
                  data-tooltip-placement="top"
                >
                  <i className="bi bi-palette" aria-hidden="true"></i>
                </button>
                {isComposePaletteOpen && (
                  <div className="memo-compose-palette__menu" role="listbox" aria-label={english ? "Memo background color" : "メモの背景色"}>
                    {MEMO_COLOR_OPTIONS.map((option) => (
                      <button
                        key={option.label}
                        type="button"
                        className={`memo-compose-palette__option${(formState.background_color || "") === option.value ? " is-active" : ""}`}
                        style={{ "--palette-color": option.color } as React.CSSProperties}
                        onClick={() => {
                          setFormState((prev) => ({ ...prev, background_color: option.value || null }));
                          setIsComposePaletteOpen(false);
                          setIsMoreOpen(false);
                        }}
                        role="option"
                        aria-selected={(formState.background_color || "") === option.value}
                      >
                        <span className={`memo-compose-palette__swatch${option.value ? "" : " memo-compose-palette__swatch--empty"}`}></span>
                        <span>{t(`memo.color.${option.value || "default"}` as Parameters<typeof t>[0])}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </details>
      </div>

      <div className="memo-quick-capture__body">
        <div className="memo-quick-capture__editor">
          <MemoEditor
            id={`${sectionId}-memo-response`}
            agentId="memo.ai-response"
            editorRef={composeEditorRef}
            focusRequest={composeFocusRequest}
            value={formState.ai_response}
            onChange={(value) => setFormState((prev) => ({ ...prev, ai_response: value }))}
            sourceMode={sourceMode}
            label={english ? "Content" : "本文"}
            placeholder={english ? "Write a memo…" : "メモを入力..."}
          />
        </div>
      </div>

      <div className="memo-quick-capture__footer">
        <div className="memo-quick-capture__formatting">
          <MemoFormatToolbar id={`${sectionId}-formatting`} editorRef={composeEditorRef} hidden={!sourceMode || (mobile && !formattingOpen)} />
        </div>
        <div className="memo-quick-capture__actions">
          <button type="button" className="secondary-button" onClick={handleCloseComposer} disabled={submitting}>
            {t("common.close")}
          </button>
          <button type="submit" className="primary-button" data-agent-id="memo.save" disabled={submitting || !hasBody}>
            <i className="bi bi-check2" aria-hidden="true"></i>
            {t(submitting ? "common.saving" : "common.save")}
          </button>
        </div>
      </div>
    </form>
  );

  const renderSection = (options: { id: string; expanded: boolean; className?: string; hidden?: boolean }) => (
    <section
      id={options.id}
      className={`memo-card memo-compose-panel memo-quick-capture${options.expanded ? " is-expanded" : ""}${options.className ? ` ${options.className}` : ""}`}
      data-memo-composer-root=""
      aria-hidden={options.hidden ? "true" : undefined}
      inert={options.hidden}
    >
      {options.expanded ? renderExpandedComposer(options.id, options.id === "memo-composer-mobile") : renderCollapsedComposer()}
    </section>
  );

  const inlineExpanded = composeIsExpanded && !isMobileLayout;
  const inlineSection = renderSection({
    id: "memo-composer",
    expanded: inlineExpanded,
    className: isMobileLayout ? "memo-quick-capture--mobile-trigger" : undefined,
    hidden: mobileDialogOpen,
  });

  return (
    <>
      {inlineSection}
      <ModalShell
        isOpen={mobileDialogOpen}
        onClose={dismissMobileComposer}
        labelledBy="memo-composer-mobile-title"
        className="memo-compose-mobile-modal"
        style={viewportStyle}
        dismissDisabled={submitting}
        getInitialFocus={getMobileInitialFocus}
      >
        <div className="cc-modal__panel memo-compose-sheet">
          {mobileDialogOpen && renderSection({ id: "memo-composer-mobile", expanded: true })}
        </div>
      </ModalShell>
    </>
  );
}
