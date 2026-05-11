type RegenerateActionButtonProps = {
  onRegenerate: () => void;
  disabled?: boolean;
};

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
