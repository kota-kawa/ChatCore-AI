import React from "react";

import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { parseMemoText } from "../../lib/memo/utils";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";
import { useTranslation } from "../../contexts/locale_context";
import {
  useMemoPageComposerContext,
  useMemoPageListContext,
} from "../../contexts/memo_page/memo_page_context";

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
    previewMode,
    setPreviewMode,
    composeTextareaRef,
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
  return (
          <section className={`memo-card memo-compose-panel memo-quick-capture${composeIsExpanded ? " is-expanded" : ""}`}>
            {!composeIsExpanded ? (
              <div className="memo-quick-capture__collapsed" aria-label={t("memo.new")}>
                <button
                  type="button"
                  className="memo-quick-capture__text-button"
                  onClick={openTextComposer}
                  aria-label={english ? "Create a text memo" : "テキストメモを作成"}
                >
                  <span>{english ? "Write a memo…" : "メモを入力..."}</span>
                </button>
                <div className="memo-quick-capture__shortcuts" role="toolbar" aria-label={english ? "New memo type" : "新しいメモの種類"}>
                  <button
                    type="button"
                    className="memo-quick-capture__shortcut-btn"
                    onClick={openChecklistComposer}
                    aria-label={english ? "Create a checklist" : "チェックリストを作成"}
                    data-tooltip={english ? "Checklist" : "チェックリスト"}
                    data-tooltip-placement="top"
                  >
                    <i className="bi bi-check2-square" aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className="memo-quick-capture__shortcut-btn"
                    onClick={openComposePalette}
                    aria-label={english ? "Choose a color" : "色を選択"}
                    data-tooltip={english ? "Choose a color" : "色を選択"}
                    data-tooltip-placement="top"
                  >
                    <i className="bi bi-palette" aria-hidden="true"></i>
                  </button>
                </div>
              </div>
            ) : (
              <form
                method="post"
                className="memo-form memo-form--quick"
                onSubmit={handleSubmitMemo}
                style={formState.background_color ? { "--memo-compose-color": formState.background_color } as React.CSSProperties : undefined}
              >
                <div className="form-group">
                  <label htmlFor="title" className="sr-only">{english ? "Title" : "タイトル"}</label>
                  <input
                    id="title"
                    name="title"
                    data-agent-id="memo.title"
                    type="text"
                    className="memo-control memo-quick-capture__title-input"
                    value={formState.title}
                    onChange={handleFormChange}
                    maxLength={255}
                    placeholder={english ? "Title" : "タイトル"}
                    autoFocus={!hasComposeDraft}
                  />
                </div>

                <div className="form-group">
                  <div className="memo-response-header memo-quick-capture__response-header">
                    <label htmlFor="ai_response" className="sr-only">{english ? "Content" : "本文"}</label>
                    <div className="memo-response-tabs">
                      <button type="button" className={`memo-response-tab${!previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(false)}>
                        <i className="bi bi-pencil" aria-hidden="true"></i>{t("common.edit")}
                      </button>
                      <button type="button" className={`memo-response-tab${previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(true)} disabled={!formState.ai_response.trim()}>
                        <i className="bi bi-eye" aria-hidden="true"></i>{english ? "Preview" : "プレビュー"}
                      </button>
                    </div>
                  </div>
                  {previewMode ? (
                    <div className="memo-preview-pane">
                      {formState.ai_response.trim()
                        ? <MemoMarkdown text={parseMemoText(formState.ai_response)} className="memo-preview-content" />
                        : <p className="memo-preview-empty">{english ? "There is no text to preview." : "プレビューするテキストがありません。"}</p>}
                    </div>
                  ) : (
                    <textarea
                      id="ai_response"
                      name="ai_response"
                      data-agent-id="memo.ai-response"
                      ref={composeTextareaRef}
                      className="memo-control memo-control--response"
                      value={formState.ai_response}
                      onChange={handleFormChange}
                      placeholder={english ? "Write a memo…" : "メモを入力..."}
                      rows={1}
                      required
                    />
                  )}
                </div>

                <div className="memo-quick-capture__bottom-row">
                  {collections.length > 0 && (
                    <MemoSelect
                      id="compose_collection"
                      className="memo-select--quick"
                      value={String(formState.collection_id ?? "")}
                      onChange={(v) => setFormState((prev) => ({ ...prev, collection_id: v === "" ? null : Number(v) }))}
                      options={[
                        { value: "", label: english ? "No collection" : "コレクションなし" },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
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
                      type="button"
                      className={`memo-compose-palette__trigger${isComposePaletteOpen ? " is-active" : ""}`}
                      onClick={openComposePalette}
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
                  <div className="memo-quick-capture__actions">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => {
                        setFormState({ ai_response: "", title: "", collection_id: null, background_color: null });
                        setPreviewMode(false);
                        setIsComposeExpanded(false);
                        setIsComposePaletteOpen(false);
                      }}
                      disabled={submitting}
                    >
                      {t("common.close")}
                    </button>
                    <button type="submit" className="primary-button" data-agent-id="memo.save" disabled={submitting}>
                      <i className="bi bi-check2" aria-hidden="true"></i>
                      {english ? "Done" : "完了"}
                    </button>
                  </div>
                </div>
              </form>
            )}
          </section>
  );
}
