import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  useHomePageChatContext,
  useHomePageProjectContext,
} from "../../contexts/chat_page/home_page_context";
import {
  CHAT_ATTACHMENT_ACCEPT,
  getAttachmentIconClass,
  readSelectedChatAttachments,
} from "../../lib/chat_page/file_attachments";
import { showToast } from "../../scripts/core/toast";
import { InlineLoading } from "../ui/inline_loading";

// バイト数を人間可読なサイズ表記に変換する。
// Format a byte count into a human-readable size string.
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1_048_576).toFixed(1)}MB`;
}

// プロジェクト詳細オーバーレイ。指示・ナレッジ・所属チャットを管理する。
// Project detail overlay: manage instructions, knowledge files, and member chats.
export function ProjectSection() {
  const {
    activeProjectId,
    activeProjectDetail,
    isProjectDetailLoading,
    isSavingProject,
    isUploadingProjectFiles,
    closeProject,
    updateProject,
    deleteProject,
    uploadProjectFiles,
    deleteProjectFile,
    setNewChatProject,
  } = useHomePageProjectContext();
  const { switchChatRoom, handleNewChat } = useHomePageChatContext();

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");

  // 詳細が読み込まれたら編集フォームへ反映する。
  // Seed the edit form whenever the loaded detail changes.
  useEffect(() => {
    if (activeProjectDetail) {
      setName(activeProjectDetail.name);
      setInstructions(activeProjectDetail.instructions);
    }
  }, [activeProjectDetail]);

  const isOpen = activeProjectId !== null;

  const handleSaveDetails = useCallback(() => {
    if (activeProjectId === null) return;
    void updateProject(activeProjectId, { name: name.trim() || "新規プロジェクト", instructions });
  }, [activeProjectId, instructions, name, updateProject]);

  const handleUploadClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFilesSelected = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0 || activeProjectId === null) return;
      const prepared = await readSelectedChatAttachments(Array.from(files), [], (message) => {
        showToast(message, { variant: "error" });
      });
      if (event.target) {
        event.target.value = "";
      }
      if (prepared.length > 0) {
        await uploadProjectFiles(activeProjectId, prepared);
      }
    },
    [activeProjectId, uploadProjectFiles],
  );

  const handleStartChatInProject = useCallback(() => {
    if (activeProjectId === null) return;
    // 通常の新規チャット状態にリセットしてからプロジェクト紐づけを設定する。
    // Reset to a fresh new-chat state, then set the project association.
    handleNewChat();
    setNewChatProject(activeProjectId);
    closeProject();
  }, [activeProjectId, closeProject, handleNewChat, setNewChatProject]);

  if (!isOpen) return null;

  const detail = activeProjectDetail;
  const hasUnsavedChanges =
    detail !== null && (name !== detail.name || instructions !== detail.instructions);

  return (
    <div className="project-overlay" role="dialog" aria-modal="true" aria-label="プロジェクト詳細">
      <div className="project-overlay__panel">
        <header className="project-overlay__header">
          <button
            type="button"
            className="project-overlay__back icon-button cc-press"
            aria-label="プロジェクトを閉じる"
            onClick={closeProject}
          >
            <i className="bi bi-arrow-left" aria-hidden="true"></i>
          </button>
          <span className="project-overlay__title">
            <i className="bi bi-folder2-open" aria-hidden="true"></i>
            プロジェクト
          </span>
          {detail !== null && (
            <button
              type="button"
              className="project-overlay__delete cc-press"
              onClick={() => {
                void deleteProject(detail.id, detail.name);
              }}
            >
              <i className="bi bi-trash" aria-hidden="true"></i>
              <span>削除</span>
            </button>
          )}
        </header>

        {isProjectDetailLoading && detail === null ? (
          <div className="project-overlay__loading">
            <InlineLoading label="読み込み中" />
          </div>
        ) : detail === null ? (
          <div className="project-overlay__loading">プロジェクトを読み込めませんでした。</div>
        ) : (
          <div className="project-overlay__body">
            {/* 基本情報・カスタム指示 / Basic info and custom instructions */}
            <section className="project-section-block">
              <label className="project-field">
                <span className="project-field__label">プロジェクト名</span>
                <input
                  type="text"
                  className="project-field__input"
                  value={name}
                  maxLength={255}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label className="project-field">
                <span className="project-field__label">カスタム指示</span>
                <textarea
                  className="project-field__textarea"
                  rows={6}
                  maxLength={20000}
                  placeholder="このプロジェクト内の全会話に適用される指示（口調・役割・出力形式など）"
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                />
              </label>
              <div className="project-section-block__actions">
                <button
                  type="button"
                  className="primary-button cc-press"
                  disabled={!hasUnsavedChanges || isSavingProject}
                  onClick={handleSaveDetails}
                >
                  {isSavingProject ? "保存中..." : "指示を保存"}
                </button>
              </div>
            </section>

            {/* ナレッジ（参照ファイル）/ Knowledge (reference files) */}
            <section className="project-section-block">
              <div className="project-section-block__heading">
                <h3 className="project-section-block__title">
                  <i className="bi bi-journal-text" aria-hidden="true"></i> ナレッジ
                </h3>
                <button
                  type="button"
                  className="project-knowledge__add cc-press"
                  onClick={handleUploadClick}
                  disabled={isUploadingProjectFiles}
                >
                  <i className="bi bi-plus-lg" aria-hidden="true"></i>
                  {isUploadingProjectFiles ? "追加中..." : "ファイルを追加"}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={CHAT_ATTACHMENT_ACCEPT}
                  className="chat-file-input-hidden"
                  aria-hidden="true"
                  tabIndex={-1}
                  onChange={handleFilesSelected}
                />
              </div>
              <p className="project-section-block__hint">
                追加した資料はこのプロジェクト内の全会話で AI が参照します（PDF / Office / テキスト）。
              </p>
              {detail.files.length === 0 ? (
                <p className="project-knowledge__empty">まだファイルがありません。</p>
              ) : (
                <ul className="project-knowledge__list">
                  {detail.files.map((file) => (
                    <li key={file.id} className="project-knowledge__item">
                      <i
                        className={`bi ${getAttachmentIconClass(file.fileName)} project-knowledge__icon`}
                        aria-hidden="true"
                      ></i>
                      <span className="project-knowledge__name" title={file.fileName}>
                        {file.fileName}
                      </span>
                      <span className="project-knowledge__size">{formatBytes(file.byteSize)}</span>
                      <button
                        type="button"
                        className="project-knowledge__remove"
                        aria-label={`${file.fileName}を削除`}
                        onClick={() => {
                          void deleteProjectFile(detail.id, file.id);
                        }}
                      >
                        <i className="bi bi-x" aria-hidden="true"></i>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* 所属チャット / Member chats */}
            <section className="project-section-block">
              <div className="project-section-block__heading">
                <h3 className="project-section-block__title">
                  <i className="bi bi-chat-left-text" aria-hidden="true"></i> チャット
                </h3>
                <button type="button" className="project-newchat-btn cc-press" onClick={handleStartChatInProject}>
                  <i className="bi bi-plus-lg" aria-hidden="true"></i>
                  このプロジェクトで新規チャット
                </button>
              </div>
              {detail.rooms.length === 0 ? (
                <p className="project-chats__empty">このプロジェクトにはまだチャットがありません。</p>
              ) : (
                <ul className="project-chats__list">
                  {detail.rooms.map((room) => (
                    <li key={room.id}>
                      <button
                        type="button"
                        className="project-chats__item cc-press"
                        onClick={() => {
                          switchChatRoom(room.id, room.mode);
                          closeProject();
                        }}
                      >
                        <i className="bi bi-chat-dots project-chats__item-icon" aria-hidden="true"></i>
                        <span className="project-chats__item-title">{room.title || "新規チャット"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
