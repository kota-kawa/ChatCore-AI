// ローディングスピナーオーバーレイのprops型定義
// Props type definition for the loading spinner overlay
type LoadingSpinnerOverlayProps = {
  message?: string;
  title?: string;
  visible: boolean;
};

// 処理中にオーバーレイでローディングスピナーを表示するコンポーネント
// Component that displays a loading spinner overlay during processing
export function LoadingSpinnerOverlay({
  message,
  title,
  visible
}: LoadingSpinnerOverlayProps) {
  const { t } = useTranslation();
  const resolvedTitle = title ?? t("auth.processing");
  const resolvedMessage = message ?? t("auth.wait");
  // visible=falseの場合は何もレンダリングしない
  // Render nothing when visible is false
  if (!visible) {
    return null;
  }

  return (
    <div className="spinner-overlay" role="status" aria-live="polite" aria-label={`${resolvedTitle}. ${resolvedMessage}`}>
      <div className="spinner-card">
        <div className="spinner-ring" />
        <div className="spinner-copy">
          <p className="spinner-title">{resolvedTitle}</p>
          <p className="spinner-message">{resolvedMessage}</p>
        </div>
        {/* アニメーション用のドット / Dots for animation */}
        <div className="spinner-progress" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}
import { useTranslation } from "../../../../contexts/locale_context";
