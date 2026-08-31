// 途中までしか生成されなかった回答の続きを求めるアクションボタンのprops型定義
// Props type definition for the action button that asks for the rest of a partial answer
type ContinueActionButtonProps = {
  onContinue: () => void;
  disabled?: boolean;
};

// 出力上限や接続断で途中保存された回答の続きを生成するアクションボタン。
// 再生成と違い、保存済みの本文を捨てずに続きだけを書かせる。
// Action button that continues an answer saved partway after an output limit or a dropped
// connection. Unlike regenerate, it keeps the saved body and asks only for the remainder.
export function ContinueActionButton({ onContinue, disabled }: ContinueActionButtonProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className="continue-btn message-action-btn"
      aria-label={t("chat.continueAnswer")}
      data-tooltip={t("chat.continueAnswer")}
      data-tooltip-placement="top"
      disabled={disabled}
      onClick={() => {
        onContinue();
      }}
    >
      <i className="bi bi-arrow-right-circle"></i>
    </button>
  );
}
import { useTranslation } from "../../contexts/locale_context";
