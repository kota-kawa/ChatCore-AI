type LoadingSpinnerOverlayProps = {
  visible: boolean;
};

export function LoadingSpinnerOverlay({ visible }: LoadingSpinnerOverlayProps) {
  if (!visible) {
    return null;
  }

  return (
    <div className="spinner-overlay" role="status" aria-live="polite" aria-label="処理中">
      <div className="spinner-ring" />
    </div>
  );
}
