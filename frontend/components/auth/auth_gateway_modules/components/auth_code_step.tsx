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
      />
      <button
        type="button"
        className="submit-btn"
        onClick={onVerifyCode}
        disabled={verifyingCode}
      >
        認証して続ける
      </button>
      <button
        type="button"
        className="ghost-btn"
        onClick={onBack}
      >
        戻る
      </button>
    </div>
  );
}
