import { memo, useCallback, useId, useMemo, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { InteractiveButtonsV1 } from "../../lib/chat_page/types";

// 選択ボタンのprops型定義。onSubmit が無いときは共有表示などの読み取り専用として描く。
// Props of the choice buttons. Without onSubmit they render read-only, as in a shared view.
type Props = {
  buttons: InteractiveButtonsV1;
  // 選んだ選択肢を次の発話として送る / Sends the chosen option(s) as the next message
  onSubmit?: (text: string) => void;
  // 回答済みや生成中など、今は答えられない状態 / The question cannot be answered right now
  disabled?: boolean;
};

// チャット標準の選択ボタン。Yes/No と単一選択は押した選択肢をそのまま、複数選択は
// チェックした選択肢をまとめて1つの発話として送る。0件では送れない。
// Standard chat choice buttons. Yes/no and single choice send the pressed option as is;
// multiple select sends the ticked options together as one message and needs at least one.
function InteractiveButtonsComponent({ buttons, onSubmit, disabled = false }: Props) {
  const { t } = useTranslation();
  const questionId = useId();
  // 押してから次の発話が一覧に載るまでの二重送信を防ぐ
  // Blocks a second send between the press and the next message reaching the list
  const [submitted, setSubmitted] = useState(false);
  const [checkedIndexes, setCheckedIndexes] = useState<ReadonlySet<number>>(() => new Set());
  const readOnly = !onSubmit;
  const inactive = readOnly || disabled || submitted;
  const isMultipleSelect = buttons.type === "multiple_select";
  const options = useMemo(
    () => (buttons.type === "yes_no" ? [t("common.yes"), t("common.no")] : (buttons.options ?? [])),
    [buttons, t],
  );

  const send = useCallback(
    (text: string) => {
      if (inactive || !onSubmit || !text) return;
      setSubmitted(true);
      onSubmit(text);
    },
    [inactive, onSubmit],
  );

  const toggleOption = useCallback((index: number) => {
    setCheckedIndexes((current) => {
      const next = new Set(current);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  // 選んだ順ではなく提示順に並べ、どれを選んだかを読み取りやすくする
  // Keep the presented order rather than the click order so the answer reads predictably
  const sendCheckedOptions = useCallback(() => {
    send(options.filter((_, index) => checkedIndexes.has(index)).join(t("chat.choiceSeparator")));
  }, [checkedIndexes, options, send, t]);

  return (
    <div className="interactive-buttons-container" role="group" aria-labelledby={questionId}>
      <div className="interactive-buttons-header">
        <div id={questionId} className="interactive-buttons-question">
          {buttons.question}
        </div>
        {isMultipleSelect ? <div className="interactive-buttons-hint">{t("chat.choiceMultipleHint")}</div> : null}
      </div>
      <div className="interactive-buttons-actions">
        {isMultipleSelect
          ? options.map((option, index) => {
              const checked = checkedIndexes.has(index);
              return (
                <label
                  key={`${index}-${option}`}
                  className={[
                    "interactive-button",
                    "interactive-button--checkbox",
                    checked ? "interactive-button--checked" : "",
                    inactive ? "interactive-button--disabled" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <input
                    type="checkbox"
                    className="interactive-button__checkbox"
                    checked={checked}
                    disabled={inactive}
                    onChange={() => toggleOption(index)}
                  />
                  <span>{option}</span>
                </label>
              );
            })
          : options.map((option, index) => (
              <button
                key={`${index}-${option}`}
                type="button"
                className="interactive-button"
                disabled={inactive}
                onClick={() => send(option)}
              >
                {option}
              </button>
            ))}
      </div>
      {isMultipleSelect ? (
        <div className="interactive-buttons-footer">
          <button
            type="button"
            className="interactive-buttons-submit"
            disabled={inactive || checkedIndexes.size === 0}
            onClick={sendCheckedOptions}
          >
            {t("chat.choiceSubmit")}
          </button>
        </div>
      ) : null}
      {readOnly ? <p className="interactive-buttons-readonly-note">{t("chat.choiceReadOnlyNote")}</p> : null}
    </div>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const InteractiveButtons = memo(InteractiveButtonsComponent);
