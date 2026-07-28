import { useCallback, useRef } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { NormalizedTask } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { useTranslation } from "../../../contexts/locale_context";

// タスク詳細モーダルのprops型定義
// Props type definition for the task detail modal
type TaskDetailModalProps = {
  taskDetail: NormalizedTask | null;
  onClose: () => void;
};

// タスクの詳細情報（プロンプトテンプレート・回答ルール・例など）を表示するモーダルコンポーネント
// Modal component that displays task details (prompt template, response rules, examples, etc.)
export function TaskDetailModal({ taskDetail, onClose }: TaskDetailModalProps) {
  const { locale, t } = useTranslation();
  const modalRef = useRef<HTMLDivElement | null>(null);

  // 初期フォーカスを閉じるボタンに設定する
  // Set initial focus to the close button
  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("[data-close-task-detail]") ?? null;
  }, []);

  // フォーカストラップを有効化してキーボード操作でモーダル内に留まるようにする
  // Enable focus trap so keyboard navigation stays within the modal
  useModalFocusTrap({
    isOpen: Boolean(taskDetail),
    containerRef: modalRef,
    getInitialFocus,
    onEscape: onClose,
  });

  // 複数行テキストを改行を保持して表示するヘルパー
  // Helper to display multi-line text with preserved line breaks
  const renderMultilineText = (value: string) => (
    <div className="task-detail-section-body" style={{ whiteSpace: "pre-wrap" }}>
      {value}
    </div>
  );

  return (
    <div
      ref={modalRef}
      id="io-modal"
      className={`modal-base ${taskDetail ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="taskDetailTitle"
      aria-hidden={taskDetail ? "false" : "true"}
      tabIndex={-1}
      // モーダル背景クリックで閉じる
      // Close on backdrop click
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="io-modal-content"
        id="io-modal-content"
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {taskDetail && (
          <div className="task-detail-modal-shell">
            <div className="task-detail-modal-header">
              <div>
                <p className="task-detail-modal-eyebrow">{t("chat.taskDetails")}</p>
                <h5 className="task-detail-modal-title" id="taskDetailTitle">
                  {t("chat.taskDetails")}
                </h5>
              </div>
              <ModalCloseButton
                className="task-detail-modal-close"
                data-close-task-detail
                label={t("chat.closeModal")}
                onClick={onClose}
              />
            </div>

            {/* タスクの各フィールドをセクションとして表示する / Display each task field as a section */}
            <div className="task-detail-sections">
              <section className="task-detail-section">
                <h6 className="task-detail-section-title">{t("chat.taskTitle")}</h6>
                <div className="task-detail-section-body task-detail-section-body-compact">{taskDetail.name}</div>
              </section>

              <section className="task-detail-section">
                <h6 className="task-detail-section-title">{locale === "en" ? "Prompt template" : "プロンプトテンプレート"}</h6>
                {renderMultilineText(taskDetail.prompt_template)}
              </section>

              {taskDetail.response_rules && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">{locale === "en" ? "Response rules" : "回答ルール"}</h6>
                  {renderMultilineText(taskDetail.response_rules)}
                </section>
              )}

              {taskDetail.output_skeleton && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">{locale === "en" ? "Output template" : "出力テンプレート"}</h6>
                  {renderMultilineText(taskDetail.output_skeleton)}
                </section>
              )}

              {taskDetail.input_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">{locale === "en" ? "Input example" : "入力例"}</h6>
                  {renderMultilineText(taskDetail.input_examples)}
                </section>
              )}

              {taskDetail.output_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">{locale === "en" ? "Output example" : "出力例"}</h6>
                  {renderMultilineText(taskDetail.output_examples)}
                </section>
              )}

              {/* 補助情報がいずれも未設定の場合のフォールバック表示 / Fallback display when no supplementary info is set */}
              {!taskDetail.response_rules &&
                !taskDetail.output_skeleton &&
                !taskDetail.input_examples &&
                !taskDetail.output_examples && (
                  <section className="task-detail-section">
                    <h6 className="task-detail-section-title">{locale === "en" ? "Additional information" : "補助情報"}</h6>
                    <div className="task-detail-section-body">
                      {locale === "en" ? "No additional response rules or examples have been provided." : "追加の回答ルールや例は設定されていません。"}
                    </div>
                  </section>
                )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
