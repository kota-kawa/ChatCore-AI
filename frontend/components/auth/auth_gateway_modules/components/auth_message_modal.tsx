type AuthMessageModalProps = {
  isModalClosing: boolean;
  message: string | null;
  onHide: () => void;
};

export function AuthMessageModal({ isModalClosing, message, onHide }: AuthMessageModalProps) {
  return (
    <div
      id="messageModal"
      className={`modal ${message ? "is-open" : ""} ${isModalClosing ? "hide-animation" : ""}`}
      onClick={onHide}
    >
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <button className="close" type="button" onClick={onHide} aria-label="閉じる">
          &times;
        </button>
        <p id="modalMessage">{message}</p>
      </div>
    </div>
  );
}
