import type { ChangeEvent, FormEvent } from "react";

import type { EditPromptFormState } from "../../scripts/user/settings/page_types";
import { PromptCategorySelect } from "./prompt_category_select";

// プロンプト編集用のモーダルダイアログ — 保存中は全フォームを無効化する
// Modal dialog for editing a prompt — disables all form controls while saving
export function EditPromptModal({
  formState,
  saving,
  onClose,
  onCategoryChange,
  onChange,
  onSubmit
}: {
  formState: EditPromptFormState;
  saving: boolean;
  onClose: () => void;
  onCategoryChange: (value: string) => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  // 複数の入力欄で共通利用するクラス名をまとめて管理する
  // Reusable class string shared across all text inputs and textareas in the modal
  const inputClassName = [
    "w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5",
    "text-sm text-slate-900 shadow-sm outline-none transition",
    "placeholder:text-slate-400",
    "focus:border-primary focus:ring-4 focus:ring-primary/10",
    "disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500",
    "[html[data-theme='dark']_&]:border-slate-700",
    "[html[data-theme='dark']_&]:bg-slate-900/80",
    "[html[data-theme='dark']_&]:text-slate-100",
    "[html[data-theme='dark']_&]:focus:border-emerald-400",
    "[html[data-theme='dark']_&]:focus:ring-emerald-400/15"
  ].join(" ");
  const labelClassName = "mb-2 block text-sm font-semibold text-slate-700 [html[data-theme='dark']_&]:text-slate-200";

  return (
    <div
      id="editModal"
      className="fixed inset-0 z-[var(--z-modal)] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm [html[data-theme='dark']_&]:bg-slate-950/75"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="editPromptModalTitle"
      onClick={(event) => {
        // モーダル背景クリックでも閉じられるが、保存中は誤操作を防ぐためブロックする
        // Allow closing by clicking the backdrop, but block it during save to prevent accidental dismissal
        if (event.target === event.currentTarget && !saving) {
          onClose();
        }
      }}
    >
      <div className="flex max-h-[min(92vh,820px)] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/70 bg-white shadow-2xl shadow-slate-950/25 [html[data-theme='dark']_&]:border-slate-700/80 [html[data-theme='dark']_&]:bg-slate-950" role="document">
        <div className="flex min-h-0 w-full flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-slate-200/80 bg-slate-50 px-6 py-5 [html[data-theme='dark']_&]:border-slate-800 [html[data-theme='dark']_&]:bg-slate-900">
            <div className="flex min-w-0 items-center gap-3">
              <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-lg text-primary ring-1 ring-primary/15 [html[data-theme='dark']_&]:bg-emerald-400/10 [html[data-theme='dark']_&]:text-emerald-300 [html[data-theme='dark']_&]:ring-emerald-400/20" aria-hidden="true">
                <i className="bi bi-pencil-square"></i>
              </span>
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-[0.22em] text-primary [html[data-theme='dark']_&]:text-emerald-300">投稿したプロンプト</p>
                <h5 id="editPromptModalTitle" className="m-0 text-xl font-semibold text-slate-950 [html[data-theme='dark']_&]:text-slate-50">
                  プロンプトを編集
                </h5>
              </div>
            </div>
            <button
              type="button"
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-50 [html[data-theme='dark']_&]:border-slate-700 [html[data-theme='dark']_&]:bg-slate-900 [html[data-theme='dark']_&]:text-slate-300 [html[data-theme='dark']_&]:hover:bg-slate-800 [html[data-theme='dark']_&]:hover:text-white"
              aria-label="閉じる"
              onClick={onClose}
              disabled={saving}
            >
              <i className="bi bi-x-lg" aria-hidden="true"></i>
            </button>
          </div>

          <form id="editForm" className="flex min-h-0 flex-1 flex-col" onSubmit={onSubmit}>
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
              {/* 編集対象のプロンプト ID を hidden フィールドで保持する / Hold the target prompt ID in a hidden field for form submission */}
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="editTitle" className={labelClassName}>
                    タイトル
                  </label>
                  <input
                    type="text"
                    className={inputClassName}
                    id="editTitle"
                    name="title"
                    required
                    value={formState.title}
                    onChange={onChange}
                    disabled={saving}
                  />
                </div>

                <div>
                  <label htmlFor="editCategory" className={labelClassName}>
                    カテゴリ
                  </label>
                  <PromptCategorySelect
                    selectId="editCategory"
                    value={formState.category}
                    disabled={saving}
                    onChange={onCategoryChange}
                  />
                </div>
              </div>

              <div>
                <label htmlFor="editContent" className={labelClassName}>
                  内容
                </label>
                <textarea
                  className={`${inputClassName} min-h-44 resize-y leading-6`}
                  id="editContent"
                  name="content"
                  rows={5}
                  required
                  value={formState.content}
                  onChange={onChange}
                  disabled={saving}
                ></textarea>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label htmlFor="editInputExamples" className={labelClassName}>
                    入力例
                  </label>
                  <textarea
                    className={`${inputClassName} min-h-32 resize-y leading-6`}
                    id="editInputExamples"
                    name="inputExamples"
                    rows={3}
                    value={formState.inputExamples}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>

                <div>
                  <label htmlFor="editOutputExamples" className={labelClassName}>
                    出力例
                  </label>
                  <textarea
                    className={`${inputClassName} min-h-32 resize-y leading-6`}
                    id="editOutputExamples"
                    name="outputExamples"
                    rows={3}
                    value={formState.outputExamples}
                    onChange={onChange}
                    disabled={saving}
                  ></textarea>
                </div>
              </div>
            </div>

            <div className="flex flex-col-reverse gap-3 border-t border-slate-200/80 bg-white px-6 py-4 sm:flex-row sm:justify-end [html[data-theme='dark']_&]:border-slate-800 [html[data-theme='dark']_&]:bg-slate-950">
              <button
                type="button"
                className="inline-flex h-11 items-center justify-center rounded-lg border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 focus:outline-none focus:ring-4 focus:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-50 [html[data-theme='dark']_&]:border-slate-700 [html[data-theme='dark']_&]:bg-slate-900 [html[data-theme='dark']_&]:text-slate-200 [html[data-theme='dark']_&]:hover:bg-slate-800"
                onClick={onClose}
                disabled={saving}
              >
                閉じる
              </button>
              <button
                type="submit"
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-white shadow-lg shadow-emerald-900/10 transition hover:bg-primary-hover focus:outline-none focus:ring-4 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60 [html[data-theme='dark']_&]:shadow-emerald-950/30"
                disabled={saving}
              >
                <i className="bi bi-save" aria-hidden="true"></i>
                {saving ? "更新中..." : "更新する"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
