// メッセージ編集ボタンのprops型定義
// Props type definition for the message edit button
type EditActionButtonProps = {
  onEdit: () => void;
  disabled?: boolean;
};

// ユーザーメッセージを編集して再生成するアクションボタン
// Action button to edit a user message and regenerate the response
export function EditActionButton({ onEdit, disabled }: EditActionButtonProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className="edit-btn message-action-btn"
      aria-label={t("common.edit")}
      data-tooltip={t("chat.edit")}
      data-tooltip-placement="top"
      disabled={disabled}
      onClick={() => {
        onEdit();
      }}
    >
      <i className="bi bi-pencil-square"></i>
    </button>
  );
}
import { useTranslation } from "../../contexts/locale_context";
