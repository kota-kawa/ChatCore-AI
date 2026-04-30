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

type PromptEditFormState = {
  id: string;
  title: string;
  category: string;
  content: string;
  inputExamples: string;
  outputExamples: string;
};

const TITLE_CHAR_LIMIT = 17;
const CONTENT_CHAR_LIMIT = 160;

function truncateText(text: string, limit: number) {
  const chars = Array.from(text || "");
  return chars.length > limit ? `${chars.slice(0, limit).join("")}...` : text;
}

function toDisplayDate(createdAt?: string): string {
  if (!createdAt) {
    return "";
  }
  return formatDateTime(createdAt) || createdAt;
}

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

function PromptManageHeader() {
  return (
    <header className="main-header">
      <div className="container">
        <h1 className="logo">Prompt Manager</h1>
      </div>
    </header>
  );
}

type PromptCardProps = {
  prompt: PromptRecord;
  onEdit: (prompt: PromptRecord) => void;
  onDelete: (prompt: PromptRecord) => void;
};

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

type PromptEditModalProps = {
  isSaving: boolean;
  formState: PromptEditFormState;
  onClose: () => void;
  onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

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

export default function PromptManagePage() {
  const [prompts, setPrompts] = useState<PromptRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editFormState, setEditFormState] = useState<PromptEditFormState | null>(null);

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

  useEffect(() => {
    document.body.classList.add("prompt-manage-page");
    void loadMyPrompts();
    return () => {
      document.body.classList.remove("prompt-manage-page");
      document.body.classList.remove("modal-open");
    };
  }, [loadMyPrompts]);

  useEffect(() => {
    document.body.classList.toggle("modal-open", Boolean(editFormState));
    return () => {
      document.body.classList.remove("modal-open");
    };
  }, [editFormState]);

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

  const sortedPrompts = useMemo(() => {
    return [...prompts];
  }, [prompts]);

  const handleEditOpen = useCallback((prompt: PromptRecord) => {
    setEditFormState(createEditFormState(prompt));
  }, []);

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
      setPrompts((prev) => prev.filter((entry) => asId(entry.id) !== promptId));
    } catch (error) {
      showToast(error instanceof Error ? error.message : "プロンプトの削除に失敗しました。", { variant: "error" });
    }
  }, []);

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
        title="マイプロンプト管理 | Chat Core"
        description="Chat Coreで保存したプロンプトを管理するページです。"
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
            <h2 className="section-title">My Prompts</h2>
          </div>

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
