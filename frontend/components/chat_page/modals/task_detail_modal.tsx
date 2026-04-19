import type { NormalizedTask } from "../../../lib/chat_page/types";

type TaskDetailModalProps = {
  taskDetail: NormalizedTask | null;
  onClose: () => void;
};

export function TaskDetailModal({ taskDetail, onClose }: TaskDetailModalProps) {
  const renderMultilineText = (value: string) => (
    <div className="task-detail-section-body" style={{ whiteSpace: "pre-wrap" }}>
      {value}
    </div>
  );

  return (
    <div
      id="io-modal"
      className={`modal-base ${taskDetail ? "is-open" : ""}`.trim()}
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
                {renderMultilineText(taskDetail.prompt_template)}
              </section>

              {taskDetail.response_rules && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">回答ルール</h6>
                  {renderMultilineText(taskDetail.response_rules)}
                </section>
              )}

              {taskDetail.output_skeleton && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">出力テンプレート</h6>
                  {renderMultilineText(taskDetail.output_skeleton)}
                </section>
              )}

              {taskDetail.input_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">入力例</h6>
                  {renderMultilineText(taskDetail.input_examples)}
                </section>
              )}

              {taskDetail.output_examples && (
                <section className="task-detail-section">
                  <h6 className="task-detail-section-title">出力例</h6>
                  {renderMultilineText(taskDetail.output_examples)}
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
