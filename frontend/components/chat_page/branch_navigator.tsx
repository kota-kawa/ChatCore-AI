import type { UiChatMessage } from "../../lib/chat_page/types";

type BranchNavigatorProps = {
  message: UiChatMessage;
  disabled?: boolean;
  onSwitchBranch: (messageId: number) => void;
};

// ChatGPT-style ‹ n/m › control for switching between branch versions of a
// message (edited user prompts, or regenerated assistant answers).
export function BranchNavigator({ message, disabled, onSwitchBranch }: BranchNavigatorProps) {
  const versionCount = message.versionCount ?? 1;
  const versionIndex = message.versionIndex ?? 1;
  const siblingIds = message.siblingIds;

  if (versionCount <= 1 || !siblingIds || siblingIds.length <= 1) {
    return null;
  }

  const currentZeroBased = versionIndex - 1;
  const prevId = siblingIds[currentZeroBased - 1];
  const nextId = siblingIds[currentZeroBased + 1];

  const goPrev = () => {
    if (typeof prevId === "number") onSwitchBranch(prevId);
  };
  const goNext = () => {
    if (typeof nextId === "number") onSwitchBranch(nextId);
  };

  return (
    <div className="branch-navigator" role="group" aria-label="メッセージのバージョン切り替え">
      <button
        type="button"
        className="branch-navigator__btn"
        aria-label="前のバージョン"
        disabled={disabled || typeof prevId !== "number"}
        onClick={goPrev}
      >
        <i className="bi bi-chevron-left" aria-hidden="true"></i>
      </button>
      <span className="branch-navigator__count" aria-live="polite">
        {versionIndex}/{versionCount}
      </span>
      <button
        type="button"
        className="branch-navigator__btn"
        aria-label="次のバージョン"
        disabled={disabled || typeof nextId !== "number"}
        onClick={goNext}
      >
        <i className="bi bi-chevron-right" aria-hidden="true"></i>
      </button>
    </div>
  );
}
