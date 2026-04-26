import { useCallback, useRef, type Dispatch, type SetStateAction } from "react";

import { useModalFocusTrap } from "../../../hooks/use_modal_focus_trap";
import type { TaskEditFormState } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";

type TaskEditModalProps = {
  taskEditModalOpen: boolean;
  taskEditForm: TaskEditFormState;
  closeTaskEditModal: () => void;
  setTaskEditForm: Dispatch<SetStateAction<TaskEditFormState>>;
  onSave: () => void;
};

export function TaskEditModal({
  taskEditModalOpen,
  taskEditForm,
  closeTaskEditModal,
  setTaskEditForm,
  onSave,
}: TaskEditModalProps) {
  const modalRef = useRef<HTMLDivElement | null>(null);
  const getInitialFocus = useCallback(() => {
    return modalRef.current?.querySelector<HTMLElement>("#taskName") ?? null;
  }, []);

  useModalFocusTrap({
    isOpen: taskEditModalOpen,
    containerRef: modalRef,
    getInitialFocus,
    onEscape: closeTaskEditModal,
  });

  return (
    <div
      ref={modalRef}
      id="taskEditModal"
      className={`custom-modal modal-base ${taskEditModalOpen ? "is-open" : ""}`.trim()}
      role="dialog"
      aria-modal="true"
      aria-hidden={taskEditModalOpen ? "false" : "true"}
      aria-labelledby="taskEditModalTitle"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          closeTaskEditModal();
        }
      }}
    >
      <div className="custom-modal-dialog">
        <div className="custom-modal-content">
          <div className="custom-modal-header">
            <h5 className="custom-modal-title" id="taskEditModalTitle">タスク編集</h5>
            <ModalCloseButton
              className="custom-modal-close"
              id="closeTaskEditModal"
              label="タスク編集を閉じる"
              onClick={closeTaskEditModal}
            />
          </div>

          <div className="custom-modal-body">
            <form id="taskEditForm" onSubmit={(event) => event.preventDefault()}>
              <div className="custom-form-group">
                <label htmlFor="taskName" className="custom-form-label">
                  <span className="custom-form-label__required">タイトル</span>
                </label>
                <input
                  type="text"
                  className="custom-form-control"
                  id="taskName"
                  name="name"
                  placeholder="例：メール作成"
                  required
                  aria-required="true"
                  value={taskEditForm.new_task}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      new_task: event.target.value,
                    }));
                  }}
                />
                <div className="custom-form-text">タスクの名前を入力してください。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="promptTemplate" className="custom-form-label">
                  プロンプトテンプレート
                </label>
                <textarea
                  className="custom-form-control"
                  id="promptTemplate"
                  name="prompt_template"
                  rows={2}
                  placeholder="例：メール本文の書き出し..."
                  value={taskEditForm.prompt_template}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      prompt_template: event.target.value,
                    }));
                  }}
                ></textarea>
                <div className="custom-form-text">タスク実行時に使用するプロンプトテンプレートです。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="responseRules" className="custom-form-label">
                  回答ルール
                </label>
                <textarea
                  className="custom-form-control"
                  id="responseRules"
                  name="response_rules"
                  rows={2}
                  placeholder="例：不足情報があれば先に確認する。結論から先に書く。"
                  value={taskEditForm.response_rules}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      response_rules: event.target.value,
                    }));
                  }}
                ></textarea>
                <div className="custom-form-text">回答時に優先させたいルールを任意で指定します。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="outputSkeleton" className="custom-form-label">
                  出力テンプレート
                </label>
                <textarea
                  className="custom-form-control"
                  id="outputSkeleton"
                  name="output_skeleton"
                  rows={2}
                  placeholder={"例：## 結論\n## 詳細\n## 次の一手"}
                  value={taskEditForm.output_skeleton}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      output_skeleton: event.target.value,
                    }));
                  }}
                ></textarea>
                <div className="custom-form-text">回答の骨組みを任意で指定します。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="inputExamples" className="custom-form-label">
                  入力例
                </label>
                <textarea
                  className="custom-form-control"
                  id="inputExamples"
                  name="input_examples"
                  rows={2}
                  placeholder="例：今日の天気は？"
                  value={taskEditForm.input_examples}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      input_examples: event.target.value,
                    }));
                  }}
                ></textarea>
                <div className="custom-form-text">ユーザーが入力する例です。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="outputExamples" className="custom-form-label">
                  出力例
                </label>
                <textarea
                  className="custom-form-control"
                  id="outputExamples"
                  name="output_examples"
                  rows={2}
                  placeholder="例：晴れです。"
                  value={taskEditForm.output_examples}
                  onChange={(event) => {
                    setTaskEditForm((previous) => ({
                      ...previous,
                      output_examples: event.target.value,
                    }));
                  }}
                ></textarea>
                <div className="custom-form-text">タスク実行時の出力例です。</div>
              </div>
            </form>
          </div>

          <div className="custom-modal-footer">
            <button
              type="button"
              className="custom-btn-secondary"
              id="cancelTaskEditModal"
              onClick={closeTaskEditModal}
            >
              キャンセル
            </button>
            <button
              type="button"
              className="primary-button"
              id="saveTaskChanges"
              onClick={() => {
                onSave();
              }}
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
