import { formatMultilineHtml } from "../../../scripts/core/html";
import type { NormalizedTask } from "../../../lib/chat_page/types";

type TaskDetailModalProps = {
  taskDetail: NormalizedTask | null;
  onClose: () => void;
};

export function TaskDetailModal({ taskDetail, onClose }: TaskDetailModalProps) {
  return (
    <div
      id="io-modal"
      style={{ display: taskDetail ? "flex" : "none" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="taskDetailTitle"
      aria-hidden={taskDetail ? "false" : "true"}
      tabIndex={-1}
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
                <p className="task-detail-modal-eyebrow">Task Detail</p>
                <h5 className="task-detail-modal-title" id="taskDetailTitle">
                  タスク詳細
                </h5>
              </div>
              <button
                type="button"
                className="task-detail-modal-close"
                data-close-task-detail
                aria-label="タスク詳細を閉じる"
                onClick={onClose}
              >
                <i className="bi bi-x-lg"></i>
              </button>
            </div>

            <div className="task-detail-sections">
              <section className="task-detail-section">
                <h6 className="task-detail-section-title">タスク名</h6>
                <div className="task-detail-section-body task-detail-section-body-compact">{taskDetail.name}</div>
              </section>

              <section className="task-detail-section">
                <h6 className="task-detail-section-title">プロンプトテンプレート</h6>
                <div
                  className="task-detail-section-body"
                  dangerouslySetInnerHTML={{
                    __html: formatMultilineHtml(taskDetail.prompt_template),
                  }}
                ></div>
              </section>

              {taskDetail.response_rules && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">回答ルール</h6>
                  <div
                    className="task-detail-section-body"
                    dangerouslySetInnerHTML={{
                      __html: formatMultilineHtml(taskDetail.response_rules),
                    }}
                  ></div>
                </section>
              )}

              {taskDetail.output_skeleton && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">出力テンプレート</h6>
                  <div
                    className="task-detail-section-body"
                    dangerouslySetInnerHTML={{
                      __html: formatMultilineHtml(taskDetail.output_skeleton),
                    }}
                  ></div>
                </section>
              )}

              {taskDetail.input_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">入力例</h6>
                  <div
                    className="task-detail-section-body"
                    dangerouslySetInnerHTML={{
                      __html: formatMultilineHtml(taskDetail.input_examples),
                    }}
                  ></div>
                </section>
              )}

              {taskDetail.output_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">出力例</h6>
                  <div
                    className="task-detail-section-body"
                    dangerouslySetInnerHTML={{
                      __html: formatMultilineHtml(taskDetail.output_examples),
                    }}
                  ></div>
                </section>
              )}

              {!taskDetail.response_rules &&
                !taskDetail.output_skeleton &&
                !taskDetail.input_examples &&
                !taskDetail.output_examples && (
                  <section className="task-detail-section">
                    <h6 className="task-detail-section-title">補助情報</h6>
                    <div className="task-detail-section-body">
                      追加の回答ルールや例は設定されていません。
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
