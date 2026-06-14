import type { UiChatMessage } from "../../lib/chat_page/types";

// ブランチナビゲーターのprops型定義
// Props type definition for the branch navigator
type BranchNavigatorProps = {
  message: UiChatMessage;
  disabled?: boolean;
  onSwitchBranch: (messageId: number) => void;
};

// ChatGPT-style ‹ n/m › control for switching between branch versions of a
// message (edited user prompts, or regenerated assistant answers).
// メッセージのバージョン（編集済みプロンプトや再生成された回答）を切り替えるコンポーネント
// Component for switching between versions of a message (edited prompts or regenerated answers)
export function BranchNavigator({ message, disabled, onSwitchBranch }: BranchNavigatorProps) {
  const versionCount = message.versionCount ?? 1;
  const versionIndex = message.versionIndex ?? 1;
  const siblingIds = message.siblingIds;

  // バージョンが1つしかない場合は何も表示しない
  // Render nothing if there is only one version
  if (versionCount <= 1 || !siblingIds || siblingIds.length <= 1) {
    return null;
  }

  // 0始まりのインデックスで前後のメッセージIDを取得する
  // Get the previous and next message IDs using zero-based index
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
      {/* 前のバージョンへ / Go to previous version */}
      <button
        type="button"
        className="branch-navigator__btn"
        aria-label="前のバージョン"
        disabled={disabled || typeof prevId !== "number"}
        onClick={goPrev}
      >
        <i className="bi bi-chevron-left" aria-hidden="true"></i>
      </button>
      {/* 現在のバージョン番号 / Current version number */}
      <span className="branch-navigator__count" aria-live="polite">
        {versionIndex}/{versionCount}
      </span>
      {/* 次のバージョンへ / Go to next version */}
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
