import { SeoHead } from "../../components/SeoHead";
import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";

import "../../scripts/core/csrf";
import { showConfirmModal } from "../../scripts/core/alert_modal";
import { showToast } from "../../scripts/core/toast";
import { fetchJsonOrThrow } from "../../scripts/core/runtime_validation";
import { formatDateTime } from "../../lib/datetime";
import { asId } from "../../lib/utils";
import {
  parseMyPromptsResponse,
  parsePromptManageMutationResponse,
  type PromptRecord
} from "../../scripts/user/settings/types";

// プロンプト編集フォームの状態型
// State type for the prompt edit form
type PromptEditFormState = {
  id: string;
  title: string;
  category: string;
  content: string;
  inputExamples: string;
  outputExamples: string;
};

// 一覧カードに表示するタイトル・本文の最大文字数
// Maximum character counts for title and content shown in list cards
const TITLE_CHAR_LIMIT = 17;
const CONTENT_CHAR_LIMIT = 160;

// テキストを指定文字数で切り詰めてサロゲートペアを考慮する
// Truncate text to specified character count with surrogate pair support
function truncateText(text: string, limit: number) {
  const chars = Array.from(text || "");
  return chars.length > limit ? `${chars.slice(0, limit).join("")}...` : text;
}

// 日付文字列を表示用フォーマットに変換する（変換失敗時は元の文字列を返す）
// Convert date string to display format (return the original string if conversion fails)
function toDisplayDate(createdAt?: string): string {
  if (!createdAt) {
    return "";
  }
  return formatDateTime(createdAt) || createdAt;
}

// PromptRecordからフォーム状態を初期化する
// Initialize form state from a PromptRecord
function createEditFormState(prompt: PromptRecord): PromptEditFormState {
  return {
    id: asId(prompt.id),
    title: prompt.title,
    category: prompt.category,
    content: prompt.content,
    inputExamples: prompt.inputExamples,
    outputExamples: prompt.outputExamples
  };
}

// プロンプト管理ページのヘッダーコンポーネント
// Header component for the prompt manage page
function PromptManageHeader() {
  return (
    <header className="main-header">
      <div className="container">
        <h1 className="logo">Prompt Manager</h1>
      </div>
    </header>
  );
}

// プロンプト一覧カードのプロップス
// Props for a prompt list card
type PromptCardProps = {
  prompt: PromptRecord;
  onEdit: (prompt: PromptRecord) => void;
  onDelete: (prompt: PromptRecord) => void;
};

// プロンプトの概要を表示するカードコンポーネント
// Card component displaying a prompt summary
function PromptCard({ prompt, onEdit, onDelete }: PromptCardProps) {
  const promptId = asId(prompt.id);
  const truncatedTitle = truncateText(prompt.title, TITLE_CHAR_LIMIT);
  const truncatedContent = truncateText(prompt.content, CONTENT_CHAR_LIMIT);

  return (
    <article className="prompt-card" data-prompt-id={promptId}>
      <div className="prompt-card__main">
        <h3 title={prompt.title}>{truncatedTitle}</h3>
        <p className="prompt-card__content" title={prompt.content}>{truncatedContent}</p>
        <div className="meta">
          <span>カテゴリ: {prompt.category || "未設定"}</span>
          <br />
          <span>投稿日: {toDisplayDate(prompt.createdAt)}</span>
        </div>
      </div>
      {/* 入力例・出力例はスクリーンリーダー等のための非表示テキストとして保持 / Hidden text for input/output examples kept for accessibility */}
      <p className="d-none input-examples">{prompt.inputExamples}</p>
      <p className="d-none output-examples">{prompt.outputExamples}</p>
      <div className="prompt-card__footer">
        <div className="btn-group">
          <button
            type="button"
            className="btn btn-sm btn-warning edit-btn"
            data-id={promptId}
            onClick={() => onEdit(prompt)}
          >
            <i className="bi bi-pencil"></i> 編集
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger delete-btn"
            data-id={promptId}
            onClick={() => onDelete(prompt)}
          >
            <i className="bi bi-trash"></i> 削除
          </button>
        </div>
      </div>
    </article>
  );
}

// プロンプト編集モーダルのプロップス
// Props for the prompt edit modal
type PromptEditModalProps = {
  isSaving: boolean;
  formState: PromptEditFormState;
  onClose: () => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

// プロンプト編集モーダルコンポーネント
// Prompt edit modal component
function PromptEditModal({ isSaving, formState, onClose, onChange, onSubmit }: PromptEditModalProps) {
  return (
    <div
      id="editModal"
      className="modal show"
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      style={{ display: "block", backgroundColor: "rgba(15, 23, 42, 0.5)" }}
      onClick={(event) => {
        {/* オーバーレイ背景クリックでモーダルを閉じる / Close modal on overlay background click */}
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal-dialog modal-dialog-centered modal-dialog-scrollable" role="document">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">
              <i className="bi bi-pencil-square me-2"></i>プロンプト編集
            </h5>
            <button
              type="button"
              className="btn-close"
              aria-label="Close"
              onClick={onClose}
              disabled={isSaving}
            ></button>
          </div>

          <div className="modal-body">
            <form id="editForm" className="modal-form" onSubmit={onSubmit}>
              <input type="hidden" id="editPromptId" value={formState.id} readOnly />

              <div className="form-group">
                <label htmlFor="editTitle" className="form-label">
                  タイトル
                </label>
                <input
                  type="text"
                  className="form-control input-field"
                  id="editTitle"
                  name="title"
                  required
                  value={formState.title}
                  onChange={onChange}
                  disabled={isSaving}
                />
              </div>

              <div className="form-group">
                <label htmlFor="editCategory" className="form-label">
                  カテゴリ
                </label>
                <input
                  type="text"
                  className="form-control input-field"
                  id="editCategory"
                  name="category"
                  required
                  value={formState.category}
                  onChange={onChange}
                  disabled={isSaving}
                />
              </div>

              <div className="form-group">
                <label htmlFor="editContent" className="form-label">
                  内容
                </label>
                <textarea
                  className="form-control input-field"
                  id="editContent"
                  name="content"
                  rows={5}
                  required
                  value={formState.content}
                  onChange={onChange}
                  disabled={isSaving}
                ></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editInputExamples" className="form-label">
                  入力例
                </label>
                <textarea
                  className="form-control input-field"
                  id="editInputExamples"
                  name="inputExamples"
                  rows={3}
                  value={formState.inputExamples}
                  onChange={onChange}
                  disabled={isSaving}
                ></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editOutputExamples" className="form-label">
                  出力例
                </label>
                <textarea
                  className="form-control input-field"
                  id="editOutputExamples"
                  name="outputExamples"
                  rows={3}
                  value={formState.outputExamples}
                  onChange={onChange}
                  disabled={isSaving}
                ></textarea>
              </div>

              <div className="form-actions">
                <button type="submit" className="btn btn-primary w-100" disabled={isSaving}>
                  <i className="bi bi-save me-2"></i>{isSaving ? "更新中..." : "更新する"}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

// プロンプト管理ページ（一覧表示・編集・削除を提供する）
// Prompt manage page (provides list view, edit, and delete functionality)
export default function PromptManagePage() {
  const [prompts, setPrompts] = useState<PromptRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editFormState, setEditFormState] = useState<PromptEditFormState | null>(null);

  // 自分のプロンプト一覧をAPIから取得する
  // Fetch the user's own prompts from the API
  const loadMyPrompts = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const { payload } = await fetchJsonOrThrow(
        "/prompt_manage/api/my_prompts",
        { credentials: "same-origin" },
        { defaultMessage: "プロンプトの取得に失敗しました。" }
      );
      setPrompts(parseMyPromptsResponse(payload));
    } catch (error) {
      setPrompts([]);
      setLoadError(error instanceof Error ? error.message : "プロンプトの取得に失敗しました。");
    } finally {
      setIsLoading(false);
    }
  }, []);

  // マウント時にbodyクラスを付与し、アンマウント時に除去する
  // Add body class on mount and remove it on unmount
  useEffect(() => {
    document.body.classList.add("prompt-manage-page");
    void loadMyPrompts();
    return () => {
      document.body.classList.remove("prompt-manage-page");
      document.body.classList.remove("modal-open");
    };
  }, [loadMyPrompts]);

  // 編集モーダルの開閉に応じてbodyのスクロールを制御する
  // Control body scroll based on edit modal open/close state
  useEffect(() => {
    document.body.classList.toggle("modal-open", Boolean(editFormState));
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [editFormState]);

  // 編集モーダルが開いている間はEscキーで閉じられるようにする（保存中は除く）
  // Allow closing the edit modal with Escape key while it's open (disabled while saving)
  useEffect(() => {
    if (!editFormState) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isSaving) {
        setEditFormState(null);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [editFormState, isSaving]);

  // プロンプト一覧をメモ化して不要な再計算を防ぐ
  // Memoize the prompt list to prevent unnecessary recalculations
  const sortedPrompts = useMemo(() => {
    return [...prompts];
  }, [prompts]);

  // 編集モーダルを開いてフォームを初期化する
  // Open the edit modal and initialize the form
  const handleEditOpen = useCallback((prompt: PromptRecord) => {
    setEditFormState(createEditFormState(prompt));
  }, []);

  // 確認ダイアログを表示してからプロンプトを削除する
  // Delete a prompt after showing a confirmation dialog
  const handleDelete = useCallback(async (prompt: PromptRecord) => {
    const promptId = asId(prompt.id);
    if (!promptId) {
      showToast("削除対象のプロンプトIDが不正です。", { variant: "error" });
      return;
    }

    const confirmed = await showConfirmModal("本当にこのプロンプトを削除しますか？");
    if (!confirmed) {
      return;
    }

    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${promptId}`,
        {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin"
        },
        {
          defaultMessage: "プロンプトの削除に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "削除しました。", { variant: "success" });
      // 削除されたプロンプトをローカルの状態から即座に除去する
      // Immediately remove the deleted prompt from local state
      setPrompts((prev) => prev.filter((entry) => asId(entry.id) !== promptId));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "プロンプトの削除に失敗しました。", { variant: "error" });
    }
  }, []);

  // フォームの各フィールドの変更を編集フォーム状態に反映する
  // Reflect each form field change into the edit form state
  const handleEditChange = useCallback((event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = event.target;
    setEditFormState((prev) => {
      if (!prev) {
        return prev;
      }
      return {
        ...prev,
        [name]: value
      };
    });
  }, []);

  // 編集フォームの送信処理（バリデーション→PUT→一覧リロード）
  // Handle edit form submission (validate → PUT → reload list)
  const handleEditSubmit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editFormState) {
      return;
    }

    if (!editFormState.id || !editFormState.title.trim() || !editFormState.category.trim() || !editFormState.content.trim()) {
      showToast("編集フォームの値が不足しています。", { variant: "error" });
      return;
    }

    setIsSaving(true);
    try {
      const { payload } = await fetchJsonOrThrow(
        `/prompt_manage/api/prompts/${editFormState.id}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({
            title: editFormState.title,
            category: editFormState.category,
            content: editFormState.content,
            input_examples: editFormState.inputExamples,
            output_examples: editFormState.outputExamples
          })
        },
        {
          defaultMessage: "プロンプトの更新に失敗しました。"
        }
      );
      const response = parsePromptManageMutationResponse(payload);
      showToast(response.message || "更新しました。", { variant: "success" });
      setEditFormState(null);
      await loadMyPrompts();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "プロンプトの更新に失敗しました。", { variant: "error" });
    } finally {
      setIsSaving(false);
    }
  }, [editFormState, loadMyPrompts]);

  return (
    <>
      <SeoHead
        title="投稿したプロンプト | Chat Core"
        description="Chat Coreで投稿したプロンプトを管理するページです。"
        canonicalPath="/prompt_share/manage_prompts"
        noindex
      >
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link rel="stylesheet" href="/prompt_share/static/css/pages/prompt_manage.css" />
      </SeoHead>

      <div className="prompt-manage-page">
        <PromptManageHeader />

        <main className="container main-container">
          <div className="header-bar">
            <h2 className="section-title">投稿したプロンプト</h2>
          </div>

          {/* ローディング・エラー・空状態のフィードバック / Loading, error, and empty state feedback */}
          {isLoading ? <p>プロンプトを読み込み中です...</p> : null}
          {!isLoading && loadError ? <p role="alert">{loadError}</p> : null}
          {!isLoading && !loadError && sortedPrompts.length === 0 ? <p>プロンプトが存在しません。</p> : null}

          <div id="promptList" className="prompt-grid">
            {sortedPrompts.map((prompt, index) => {
              const key = asId(prompt.id) || `${prompt.title}-${index}`;
              return (
                <PromptCard
                  key={key}
                  prompt={prompt}
                  onEdit={handleEditOpen}
                  onDelete={handleDelete}
                />
              );
            })}
          </div>
        </main>

        {/* 編集モーダルはフォーム状態が存在する場合のみレンダリング / Edit modal rendered only when form state is present */}
        {editFormState ? (
          <PromptEditModal
            isSaving={isSaving}
            formState={editFormState}
            onClose={() => {
              if (!isSaving) {
                setEditFormState(null);
              }
            }}
            onChange={handleEditChange}
            onSubmit={handleEditSubmit}
          />
        ) : null}
      </div>
    </>
  );
}
