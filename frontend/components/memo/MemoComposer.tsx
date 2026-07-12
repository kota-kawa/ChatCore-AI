import React, {
  type ChangeEvent,
  type Dispatch,
  type FormEvent,
  type RefObject,
  type SetStateAction,
} from "react";

import { MEMO_COLOR_OPTIONS } from "../../lib/memo/constants";
import { parseMemoText } from "../../lib/memo/utils";
import type { Collection, MemoComposeFormState } from "../../lib/memo/types";
import { MemoMarkdown } from "./MemoMarkdown";
import { MemoSelect } from "./MemoSelect";

type MemoComposerProps = {
  composeIsExpanded: boolean;
  openTextComposer: () => void;
  openChecklistComposer: () => void;
  openComposePalette: () => void;
  handleSubmitMemo: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  formState: MemoComposeFormState;
  handleFormChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => void;
  previewMode: boolean;
  setPreviewMode: Dispatch<SetStateAction<boolean>>;
  composeTextareaRef: RefObject<HTMLTextAreaElement | null>;
  collections: Collection[];
  setFormState: Dispatch<SetStateAction<MemoComposeFormState>>;
  aiSuggesting: boolean;
  handleAiSuggest: () => Promise<void>;
  isComposePaletteOpen: boolean;
  submitting: boolean;
  setIsComposeExpanded: Dispatch<SetStateAction<boolean>>;
  setIsComposePaletteOpen: Dispatch<SetStateAction<boolean>>;
  hasComposeDraft: boolean;
};

// ── Quick capture ──
export function MemoComposer({
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
  collections,
  setFormState,
  aiSuggesting,
  handleAiSuggest,
  isComposePaletteOpen,
  submitting,
  setIsComposeExpanded,
  setIsComposePaletteOpen,
  hasComposeDraft,
}: MemoComposerProps) {
  return (
          <section className={`memo-card memo-compose-panel memo-quick-capture${composeIsExpanded ? " is-expanded" : ""}`}>
            {!composeIsExpanded ? (
              <div className="memo-quick-capture__collapsed" aria-label="新しいメモを作成">
                <button
                  type="button"
                  className="memo-quick-capture__text-button"
                  onClick={openTextComposer}
                  aria-label="テキストメモを作成"
                >
                  <span>メモを入力...</span>
                </button>
                <div className="memo-quick-capture__shortcuts" role="toolbar" aria-label="新しいメモの種類">
                  <button
                    type="button"
                    className="memo-quick-capture__shortcut-btn"
                    onClick={openChecklistComposer}
                    aria-label="チェックリストを作成"
                    data-tooltip="チェックリスト"
                    data-tooltip-placement="top"
                  >
                    <i className="bi bi-check2-square" aria-hidden="true"></i>
                  </button>
                  <button
                    type="button"
                    className="memo-quick-capture__shortcut-btn"
                    onClick={openComposePalette}
                    aria-label="色を選択"
                    data-tooltip="色を選択"
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
                  <label htmlFor="title" className="sr-only">タイトル</label>
                  <input
                    id="title"
                    name="title"
                    data-agent-id="memo.title"
                    type="text"
                    className="memo-control memo-quick-capture__title-input"
                    value={formState.title}
                    onChange={handleFormChange}
                    maxLength={255}
                    placeholder="タイトル"
                    autoFocus={!hasComposeDraft}
                  />
                </div>

                <div className="form-group">
                  <div className="memo-response-header memo-quick-capture__response-header">
                    <label htmlFor="ai_response" className="sr-only">本文</label>
                    <div className="memo-response-tabs">
                      <button type="button" className={`memo-response-tab${!previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(false)}>
                        <i className="bi bi-pencil" aria-hidden="true"></i>編集
                      </button>
                      <button type="button" className={`memo-response-tab${previewMode ? " is-active" : ""}`} onClick={() => setPreviewMode(true)} disabled={!formState.ai_response.trim()}>
                        <i className="bi bi-eye" aria-hidden="true"></i>プレビュー
                      </button>
                    </div>
                  </div>
                  {previewMode ? (
                    <div className="memo-preview-pane">
                      {formState.ai_response.trim()
                        ? <MemoMarkdown text={parseMemoText(formState.ai_response)} className="memo-preview-content" />
                        : <p className="memo-preview-empty">プレビューするテキストがありません。</p>}
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
                      placeholder="メモを入力..."
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
                        { value: "", label: "コレクションなし" },
                        ...collections.map((c) => ({ value: String(c.id), label: c.name })),
                      ]}
                    />
                  )}
                  <button
                    type="button"
                    className={`memo-ai-suggest-btn${aiSuggesting ? " is-loading" : ""}`}
                    onClick={() => { void handleAiSuggest(); }}
                    disabled={aiSuggesting || !formState.ai_response.trim()}
                    data-tooltip="AIがタイトルを提案"
                    data-tooltip-placement="top"
                  >
                    {aiSuggesting
                      ? <><i className="bi bi-arrow-repeat memo-spin" aria-hidden="true"></i>提案中...</>
                      : <><i className="bi bi-stars" aria-hidden="true"></i>AIタイトル</>}
                  </button>
                  <div className="memo-compose-palette">
                    <button
                      type="button"
                      className={`memo-compose-palette__trigger${isComposePaletteOpen ? " is-active" : ""}`}
                      onClick={openComposePalette}
                      aria-label="色を選択"
                      aria-expanded={isComposePaletteOpen}
                      data-tooltip="色を選択"
                      data-tooltip-placement="top"
                    >
                      <i className="bi bi-palette" aria-hidden="true"></i>
                    </button>
                    {isComposePaletteOpen && (
                      <div className="memo-compose-palette__menu" role="listbox" aria-label="メモの背景色">
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
                            <span>{option.label}</span>
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
                      閉じる
                    </button>
                    <button type="submit" className="primary-button" data-agent-id="memo.save" disabled={submitting}>
                      <i className="bi bi-check2" aria-hidden="true"></i>
                      完了
                    </button>
                  </div>
                </div>
              </form>
            )}
          </section>
  );
}
