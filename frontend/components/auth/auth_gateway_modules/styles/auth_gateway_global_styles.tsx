type AuthGatewayGlobalStylesProps = {
  fontFamily: string;
};

export function AuthGatewayGlobalStyles({ fontFamily }: AuthGatewayGlobalStylesProps) {
  return (
    <style jsx global>{`
      body.auth-page,
      .auth-page-root {
        --accent: var(--primary-color, #19c37d);
        --accent-soft: var(--primary-soft, #e8f9f3);
        --bg-1: #0e401e;
        --bg-2: #164f2f;
        --glass: rgba(12, 28, 20, 0.72);
        --glass-border: rgba(255, 255, 255, 0.12);
        --text: #eafff3;
        --muted: rgba(255, 255, 255, 0.72);
      }

      * {
        box-sizing: border-box;
      }

      body.auth-page,
      .auth-page-root {
        margin: 0;
        padding: 0;
        font-family: ${fontFamily}, var(--font-app-sans), "Segoe UI", sans-serif;
        background: linear-gradient(135deg, var(--bg-1), var(--bg-2));
        min-height: 100vh;
        min-height: 100svh;
        width: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
        color: var(--text);
        overflow: hidden;
        position: relative;
      }

      .auth-page-root {
        width: 100vw;
        min-height: 100vh;
        min-height: 100svh;
        isolation: isolate;
      }

      .auth-container {
        position: relative;
        z-index: 1;
        background: var(--glass);
        border: 1px solid var(--glass-border);
        backdrop-filter: blur(12px);
        padding: 36px 32px 32px;
        border-radius: 24px;
        text-align: center;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.08);
        width: min(92vw, 460px);
        margin: 0 auto;
        animation: cardIn 0.8s ease;
      }

      @media (max-width: 600px) {
        .auth-container {
          padding: 28px 22px 26px;
        }
      }

      @keyframes cardIn {
        from {
          opacity: 0;
          transform: translateY(18px) scale(0.98);
        }
        to {
          opacity: 1;
          transform: translateY(0) scale(1);
        }
      }

      .bot-icon {
        font-size: 3rem;
        line-height: 1;
      }

      .title {
        font-size: 2.1rem;
        color: var(--accent);
        margin: 12px 0 10px;
        letter-spacing: 0.06em;
        text-shadow: 0 8px 24px rgba(25, 195, 125, 0.25);
      }

      .subtitle {
        margin: 0 0 20px;
        color: var(--muted);
        font-size: 0.95rem;
        line-height: 1.6;
      }

      .divider {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 18px 0 14px;
        color: var(--muted);
        font-size: 0.9rem;
      }

      .divider::before,
      .divider::after {
        content: "";
        flex: 1;
        height: 1px;
        background: rgba(255, 255, 255, 0.12);
      }

      .email-label {
        display: block;
        font-size: 0.95rem;
        color: var(--muted);
        margin: 12px 0 8px;
        text-align: left;
      }

      .email-input {
        width: 100%;
        padding: 12px 16px;
        font-size: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px;
        background: rgba(10, 20, 15, 0.55);
        color: #ffffff;
        outline: none;
        transition: border 0.25s ease, box-shadow 0.25s ease, background 0.25s ease;
        margin-bottom: 16px;
      }

      .email-input::placeholder {
        color: rgba(255, 255, 255, 0.5);
      }

      .email-input:focus {
        background: rgba(10, 20, 15, 0.7);
        border-color: var(--accent);
        box-shadow: 0 0 0 4px rgba(25, 195, 125, 0.12);
      }

      .submit-btn,
      .passkey-btn,
      .ghost-btn,
      .google-btn {
        width: 100%;
        border: none;
        border-radius: 16px;
        cursor: pointer;
        transition: transform 0.2s ease, box-shadow 0.25s ease, background 0.25s ease;
        --auth-button-base: rgba(255, 255, 255, 0.98);
        --auth-button-accent: rgba(241, 245, 249, 0.98);
        --auth-button-shadow-color: rgba(7, 20, 14, 0.22);
        background:
          radial-gradient(circle at 28% 28%, rgba(255, 255, 255, 0.3), transparent 34%),
          linear-gradient(135deg, var(--auth-button-base) 0%, var(--auth-button-accent) 100%);
        box-shadow:
          0 14px 24px var(--auth-button-shadow-color),
          inset 0 1px 0 rgba(255, 255, 255, 0.24);
      }

      .submit-btn,
      .passkey-btn {
        padding: 13px 18px;
        font-size: 1rem;
        font-weight: 700;
        margin-top: 4px;
      }

      .passkey-btn {
        --auth-button-base: var(--primary-color, #19c37d);
        --auth-button-accent: var(--primary-hover, #15a86b);
        --auth-button-shadow-color: rgba(25, 195, 125, 0.25);
        color: #052517;
      }

      .submit-btn {
        --auth-button-base: #f2fcf7;
        --auth-button-accent: #e4f7ef;
        --auth-button-shadow-color: rgba(15, 122, 81, 0.18);
        color: #0a2a18;
      }

      .ghost-btn {
        margin-top: 12px;
        padding: 12px 16px;
        --auth-button-base: rgba(255, 255, 255, 0.24);
        --auth-button-accent: rgba(255, 255, 255, 0.12);
        --auth-button-shadow-color: rgba(7, 20, 14, 0.22);
        color: var(--text);
        font-weight: 600;
      }

      .submit-btn:hover:not(:disabled),
      .passkey-btn:hover:not(:disabled),
      .ghost-btn:hover:not(:disabled),
      .google-btn:hover:not(:disabled) {
        transform: translateY(-1px);
      }

      .submit-btn:disabled,
      .passkey-btn:disabled,
      .ghost-btn:disabled,
      .google-btn:disabled {
        cursor: wait;
        opacity: 0.65;
      }

      .google-container {
        margin-top: 8px;
      }

      .google-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        padding: 12px 16px;
        --auth-button-base: #ffffff;
        --auth-button-accent: #edf2f7;
        --auth-button-shadow-color: rgba(22, 48, 34, 0.2);
        color: #163022;
        font-weight: 700;
      }

      .google-icon {
        flex: 0 0 auto;
      }

      .step-caption {
        margin: 0 0 6px;
        color: var(--muted);
        line-height: 1.6;
      }

      .code-panel,
      .passkey-panel {
        animation: sectionIn 0.2s ease;
      }

      @keyframes sectionIn {
        from {
          opacity: 0;
          transform: translateY(8px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .error-message {
        min-height: 24px;
        margin-bottom: 6px;
        color: #ffb3b3;
        font-size: 0.92rem;
      }

      .spinner-overlay {
        position: absolute;
        inset: 0;
        display: grid;
        place-items: center;
        background: rgba(7, 20, 14, 0.45);
        border-radius: 24px;
        z-index: 3;
      }

      .spinner-ring {
        width: 48px;
        height: 48px;
        border-radius: var(--radius-full, 999px);
        border: 4px solid rgba(255, 255, 255, 0.18);
        border-top-color: var(--accent);
        animation: spin 0.85s linear infinite;
      }

      @keyframes spin {
        to {
          transform: rotate(360deg);
        }
      }

      .modal {
        position: fixed;
        inset: 0;
        z-index: 40;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
        background: rgba(0, 0, 0, 0.5);
      }

      .modal.is-open {
        display: flex;
      }

      .modal-content {
        position: relative;
        width: min(92vw, 360px);
        padding: 24px 22px 22px;
        border-radius: 22px;
        background: rgba(8, 20, 14, 0.95);
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 20px 40px rgba(0, 0, 0, 0.45);
        animation: modalIn 0.18s ease;
      }

      .modal.hide-animation .modal-content {
        animation: modalOut 0.18s ease forwards;
      }

      @keyframes modalIn {
        from {
          opacity: 0;
          transform: scale(0.96);
        }
        to {
          opacity: 1;
          transform: scale(1);
        }
      }

      @keyframes modalOut {
        to {
          opacity: 0;
          transform: scale(0.96);
        }
      }

      .close {
        position: absolute;
        top: 10px;
        right: 12px;
        border: none;
        background: transparent;
        color: #ffffff;
        font-size: 1.5rem;
        cursor: pointer;
      }

      #modalMessage {
        margin: 0;
        white-space: pre-wrap;
        line-height: 1.6;
      }
    `}</style>
  );
}
