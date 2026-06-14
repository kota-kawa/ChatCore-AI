// 回答再生成ボタンのprops型定義
// Props type definition for the response regenerate button
type RegenerateActionButtonProps = {
  onRegenerate: () => void;
  disabled?: boolean;
};

// AIの回答を再生成するアクションボタン
// Action button to regenerate the AI's response
export function RegenerateActionButton({ onRegenerate, disabled }: RegenerateActionButtonProps) {
  return (
    <button
      type="button"
      className="regenerate-btn message-action-btn"
      aria-label="再生成"
      data-tooltip="AIの回答を再生成"
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
