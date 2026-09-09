import type { NormalizedTask } from "../../../lib/chat_page/types";
import { ModalCloseButton } from "../../ui/modal_close_button";
import { ModalShell } from "../../ui/modal_shell";
import { useTranslation } from "../../../contexts/locale_context";

// タスク詳細モーダルのprops型定義
// Props type definition for the task detail modal
type TaskDetailModalProps = {
  taskDetail: NormalizedTask | null;
  onClose: () => void;
};

// タスクの詳細情報（プロンプトテンプレート・回答ルール・例など）を表示するモーダルコンポーネント
// 共通モーダル面（cc-modal）の大サイズで描き、各フィールドを cc-modal__section で並べる。
// Modal component that displays task details (prompt template, response rules, examples, etc.),
// drawn on the large shared modal surface (cc-modal) with one cc-modal__section per field.
export function TaskDetailModal({ taskDetail, onClose }: TaskDetailModalProps) {
  const { locale, t } = useTranslation();

  // 1 フィールド分のセクション。複数行テキストは改行を保持して表示する
  // One field section; multi-line text keeps its line breaks
  const renderSection = (id: string, title: string, value: string) => (
    <section className="cc-modal__section" aria-labelledby={id}>
      <div className="cc-modal__section-head">
        <h3 className="cc-modal__section-title" id={id}>{title}</h3>
      </div>
      <div className="task-detail-section-body">{value}</div>
    </section>
  );

  return (
    <ModalShell
      isOpen={Boolean(taskDetail)}
      onClose={onClose}
      id="io-modal"
      className="cc-modal task-detail-modal"
      labelledBy="taskDetailTitle"
      initialFocusSelector="[data-close-task-detail]"
    >
      {taskDetail && (
        <div className="cc-modal__panel cc-modal__panel--lg" tabIndex={-1}>
          <header className="cc-modal__header">
            <div className="cc-modal__heading">
              <h2 className="cc-modal__title" id="taskDetailTitle">{t("chat.taskDetails")}</h2>
              <p className="cc-modal__lead">{taskDetail.name}</p>
            </div>
            <ModalCloseButton data-close-task-detail label={t("chat.closeModal")} onClick={onClose} />
          </header>

          {/* タスクの各フィールドをセクションとして表示する / Display each task field as a section */}
          <div className="cc-modal__body">
            {renderSection("taskDetailPromptTemplate", locale === "en" ? "Prompt template" : "プロンプトテンプレート", taskDetail.prompt_template)}

            {taskDetail.response_rules
              ? renderSection("taskDetailResponseRules", locale === "en" ? "Response rules" : "回答ルール", taskDetail.response_rules)
              : null}

            {taskDetail.output_skeleton
              ? renderSection("taskDetailOutputSkeleton", locale === "en" ? "Output template" : "出力テンプレート", taskDetail.output_skeleton)
              : null}

            {taskDetail.input_examples
              ? renderSection("taskDetailInputExamples", locale === "en" ? "Input example" : "入力例", taskDetail.input_examples)
              : null}

            {taskDetail.output_examples
              ? renderSection("taskDetailOutputExamples", locale === "en" ? "Output example" : "出力例", taskDetail.output_examples)
              : null}

            {/* 補助情報がいずれも未設定の場合のフォールバック表示 / Fallback display when no supplementary info is set */}
            {!taskDetail.response_rules &&
              !taskDetail.output_skeleton &&
              !taskDetail.input_examples &&
              !taskDetail.output_examples
              ? renderSection(
                  "taskDetailAdditional",
                  locale === "en" ? "Additional information" : "補助情報",
                  locale === "en" ? "No additional response rules or examples have been provided." : "追加の回答ルールや例は設定されていません。",
                )
              : null}
          </div>
        </div>
      )}
    </ModalShell>
  );
}
