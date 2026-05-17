type LoadingSpinnerOverlayProps = {
  message?: string;
  title?: string;
  visible: boolean;
};

export function LoadingSpinnerOverlay({
  message = "このままお待ちください。",
  title = "処理中",
  visible
}: LoadingSpinnerOverlayProps) {
  if (!visible) {
    return null;
  }

  return (
    <div className="spinner-overlay" role="status" aria-live="polite" aria-label={`${title}。${message}`}>
      <div className="spinner-card">
        <div className="spinner-ring" />
        <div className="spinner-copy">
          <p className="spinner-title">{title}</p>
          <p className="spinner-message">{message}</p>
        </div>
        <div className="spinner-progress" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}
