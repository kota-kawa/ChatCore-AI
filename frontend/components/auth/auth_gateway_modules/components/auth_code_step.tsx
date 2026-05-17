type AuthCodeStepProps = {
  authCode: string;
  verifyingCode: boolean;
  onAuthCodeChange: (value: string) => void;
  onBack: () => void;
  onVerifyCode: () => void;
};

export function AuthCodeStep({
  authCode,
  verifyingCode,
  onAuthCodeChange,
  onBack,
  onVerifyCode
}: AuthCodeStepProps) {
  return (
    <div className="code-panel">
      <p className="step-caption">メールに届いた認証コードを入力してください。</p>
      <label htmlFor="authCode" className="email-label">認証コード</label>
      <input
        type="text"
        id="authCode"
        name="authCode"
        required
        className="email-input"
        placeholder="認証コードを入力"
        value={authCode}
        onChange={(event) => onAuthCodeChange(event.target.value)}
        autoComplete="one-time-code"
        disabled={verifyingCode}
      />
      <button
        type="button"
        className="submit-btn"
        onClick={onVerifyCode}
        disabled={verifyingCode}
      >
        {verifyingCode ? "認証コードを確認中..." : "認証して続ける"}
      </button>
      {verifyingCode ? (
        <div className="code-status" role="status" aria-live="polite">
          <span className="code-status-pulse" aria-hidden="true" />
          <span>ログインの準備をしています。このままお待ちください。</span>
        </div>
      ) : null}
      <button
        type="button"
        className="ghost-btn"
        onClick={onBack}
        disabled={verifyingCode}
      >
        戻る
      </button>
    </div>
  );
}
