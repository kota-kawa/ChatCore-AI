// 回答再生成ボタンのprops型定義
// Props type definition for the response regenerate button
type RegenerateActionButtonProps = {
  onRegenerate: () => void;
  disabled?: boolean;
};

// AIの回答を再生成するアクションボタン
// Action button to regenerate the AI's response
export function RegenerateActionButton({ onRegenerate, disabled }: RegenerateActionButtonProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className="regenerate-btn message-action-btn"
      aria-label={t("chat.regenerate")}
      data-tooltip={t("chat.regenerate")}
      data-tooltip-placement="top"
      disabled={disabled}
      onClick={() => {
        onRegenerate();
      }}
    >
      <i className="bi bi-arrow-clockwise"></i>
    </button>
  );
}
import { useTranslation } from "../../contexts/locale_context";
