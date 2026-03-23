type AuthEntryStepProps = {
  email: string;
  passkeyPending: boolean;
  sendingCode: boolean;
  supportsPasskeys: boolean;
  onEmailChange: (value: string) => void;
  onGoogleLogin: () => void;
  onPasskeyLogin: () => void;
  onSendCode: () => void;
};

export function AuthEntryStep({
  email,
  passkeyPending,
  sendingCode,
  supportsPasskeys,
  onEmailChange,
  onGoogleLogin,
  onPasskeyLogin,
  onSendCode
}: AuthEntryStepProps) {
  return (
    <>
      {supportsPasskeys ? (
        <button
          type="button"
          className="passkey-btn"
          onClick={onPasskeyLogin}
          disabled={passkeyPending}
        >
          Passkeyで続ける
        </button>
      ) : null}

      <div className="google-container">
        <button
          type="button"
          className="google-btn"
          id="googleAuthBtn"
          onClick={onGoogleLogin}
        >
          <svg
            className="google-icon"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            aria-hidden="true"
            focusable="false"
          >
            <path
              fill="#EA4335"
              d="M12 10.2v3.9h5.5c-.2 1.2-.9 2.2-1.9 3v2.5h3.1c1.8-1.6 2.8-4.1 2.8-7 0-.7-.1-1.5-.2-2.2H12z"
            />
            <path
              fill="#34A853"
              d="M12 22c2.7 0 5-0.9 6.6-2.4l-3.1-2.5c-.9.6-2 .9-3.4.9-2.6 0-4.8-1.7-5.6-4.1H3.3v2.6C4.9 19.8 8.2 22 12 22z"
            />
            <path
              fill="#4A90E2"
              d="M6.4 13.9c-.2-.6-.3-1.2-.3-1.9s.1-1.3.3-1.9V7.5H3.3C2.5 9 2 10.5 2 12s.5 3 1.3 4.5l3.1-2.6z"
            />
            <path
              fill="#FBBC05"
              d="M12 6.1c1.5 0 2.8.5 3.9 1.5l2.9-2.9C17 2.9 14.7 2 12 2 8.2 2 4.9 4.2 3.3 7.5l3.1 2.6c.8-2.4 3-4 5.6-4z"
            />
          </svg>
          <span>Googleで続ける</span>
        </button>
      </div>

      <div className="divider"><span>またはメール</span></div>

      <label htmlFor="email" className="email-label">メールアドレス</label>
      <input
        type="email"
        id="email"
        name="email"
        required
        className="email-input"
        placeholder="example@mail.com"
        value={email}
        onChange={(event) => onEmailChange(event.target.value)}
        autoComplete="email webauthn"
      />
      <button
        type="button"
        className="submit-btn"
        onClick={onSendCode}
        disabled={sendingCode}
      >
        メールで続ける
      </button>
    </>
  );
}
