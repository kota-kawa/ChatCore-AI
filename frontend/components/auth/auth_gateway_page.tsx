import { Outfit } from "next/font/google";
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { ensureCsrfProtection } from "../../scripts/core/csrf";
import {
  authenticateWithPasskey,
  browserSupportsPasskeys,
  PasskeyCancelledError,
  registerPasskey
} from "../../scripts/core/passkeys";
import { REDIRECT_DELAY_MS } from "./auth_gateway_modules/constants";
import { AuthCodeStep } from "./auth_gateway_modules/components/auth_code_step";
import { AuthEntryStep } from "./auth_gateway_modules/components/auth_entry_step";
import { AuthGatewayHead } from "./auth_gateway_modules/components/auth_gateway_head";
import { AuthMessageModal } from "./auth_gateway_modules/components/auth_message_modal";
import { AuthPasskeyStep } from "./auth_gateway_modules/components/auth_passkey_step";
import { LoadingSpinnerOverlay } from "./auth_gateway_modules/components/loading_spinner_overlay";
import { useModalMessage } from "./auth_gateway_modules/hooks/use_modal_message";
import { AuthGatewayGlobalStyles } from "./auth_gateway_modules/styles/auth_gateway_global_styles";
import type { AuthStep, EmailAuthFlow, PasskeySetupProvider } from "./auth_gateway_modules/types";
import { buildGoogleLoginUrl, getPostAuthRedirectPath, getSearchParams } from "./auth_gateway_modules/url_utils";

const authHeadingFont = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap"
});

export default function AuthGatewayPage() {
  const [step, setStep] = useState<AuthStep>("entry");
  const [email, setEmail] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [verifyingCode, setVerifyingCode] = useState(false);
  const [passkeyPending, setPasskeyPending] = useState(false);
  const [supportsPasskeys, setSupportsPasskeys] = useState(false);
  const [emailAuthFlow, setEmailAuthFlow] = useState<EmailAuthFlow>(null);
  const [passkeySetupProvider, setPasskeySetupProvider] = useState<PasskeySetupProvider>(null);

  const {
    hideModal,
    isModalClosing,
    modalMessage,
    showModalMessage
  } = useModalMessage();

  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = (timerRef: MutableRefObject<ReturnType<typeof setTimeout> | null>) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const scheduleRedirect = (targetPath: string = getPostAuthRedirectPath()) => {
    clearTimer(redirectTimerRef);
    redirectTimerRef.current = setTimeout(() => {
      window.location.href = targetPath;
    }, REDIRECT_DELAY_MS);
  };

  useEffect(() => {
    ensureCsrfProtection();
    document.body.classList.add("auth-page");
    setSupportsPasskeys(browserSupportsPasskeys());
    return () => {
      document.body.classList.remove("auth-page");
      clearTimer(redirectTimerRef);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const checkLoginState = async () => {
      const query = getSearchParams();
      const nextPath = getPostAuthRedirectPath();
      const supportsPasskeysNow = browserSupportsPasskeys();
      const shouldOfferPasskeySetup = supportsPasskeysNow && query.get("offer_passkey_setup") === "1";
      const queryFlow = query.get("flow") === "register" ? "register" : "login";
      const provider = query.get("provider") === "google" ? "google" : "email";

      try {
        const response = await fetch("/api/current_user", {
          credentials: "same-origin"
        });
        const data = await response.json();

        if (!cancelled && data.logged_in) {
          if (shouldOfferPasskeySetup) {
            setEmailAuthFlow(queryFlow);
            setPasskeySetupProvider(provider);
            setStep("passkey");
            showModalMessage(
              provider === "google"
                ? "Googleでログインしました。必要ならこのままPasskeyを追加できます。"
                : "アカウントを作成しました。必要ならこのままPasskeyを追加できます。"
            );
            return;
          }
          window.location.href = nextPath;
        }
      } catch (error) {
        console.error("Error checking login state:", error);
      }
    };

    const checkTimerId = window.setTimeout(() => {
      void checkLoginState();
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(checkTimerId);
    };
  }, []);

  const handleSendCode = async () => {
    const trimmedEmail = email.trim();
    setErrorMessage("");
    setEmailAuthFlow(null);
    setPasskeySetupProvider(null);

    if (!trimmedEmail) {
      setErrorMessage("メールアドレスを入力してください。");
      return;
    }

    setSendingCode(true);
    try {
      const response = await fetch("/api/auth/send_email_code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmedEmail })
      });
      const data = await response.json().catch(() => ({}));

      if (data.status === "success") {
        setStep("code");
        showModalMessage("認証コードを送信しました。メールを確認してください。");
      } else {
        setErrorMessage(typeof data.error === "string" ? data.error : "認証コード送信に失敗しました。");
      }
    } catch (error) {
      console.error("Error sending email auth code:", error);
      setErrorMessage("サーバーエラーが発生しました。");
    } finally {
      setSendingCode(false);
    }
  };

  const handleVerifyCode = async () => {
    const trimmedCode = authCode.trim();
    setErrorMessage("");

    if (!trimmedCode) {
      setErrorMessage("認証コードを入力してください。");
      return;
    }

    setVerifyingCode(true);
    try {
      const response = await fetch("/api/auth/verify_email_code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ authCode: trimmedCode })
      });
      const data = await response.json().catch(() => ({}));

      if (data.status === "success") {
        const flow = data.flow === "register" ? "register" : "login";
        const shouldOfferPasskeySetup = flow === "register" && supportsPasskeys && data.offer_passkey_setup === true;
        setEmailAuthFlow(flow);
        setPasskeySetupProvider("email");

        if (shouldOfferPasskeySetup) {
          setStep("passkey");
          showModalMessage("アカウントを作成しました。必要ならこのままPasskeyを追加できます。");
        } else {
          if (flow === "register") {
            showModalMessage("アカウントを作成しました。");
          }
          scheduleRedirect();
        }
      } else {
        setErrorMessage(typeof data.error === "string" ? data.error : "認証に失敗しました。");
      }
    } catch (error) {
      console.error("Error verifying email auth code:", error);
      setErrorMessage("サーバーエラーが発生しました。");
    } finally {
      setVerifyingCode(false);
    }
  };

  const handlePasskeyLogin = async () => {
    setErrorMessage("");
    setPasskeyPending(true);
    try {
      await authenticateWithPasskey();
      window.location.href = getPostAuthRedirectPath();
    } catch (error) {
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "Passkey認証に失敗しました。");
    } finally {
      setPasskeyPending(false);
    }
  };

  const handlePasskeyRegistration = async () => {
    setErrorMessage("");
    setPasskeyPending(true);
    try {
      await registerPasskey();
      showModalMessage("Passkeyを保存しました。");
      scheduleRedirect();
    } catch (error) {
      if (error instanceof PasskeyCancelledError) {
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "Passkey登録に失敗しました。");
    } finally {
      setPasskeyPending(false);
    }
  };

  return (
    <>
      <AuthGatewayHead />

      <div className="auth-page-root">
        <div className="chat-background" />

        <div className="auth-container">
          <LoadingSpinnerOverlay visible={sendingCode || verifyingCode || passkeyPending} />

          <div className="bot-icon">{step === "passkey" ? "🔐" : supportsPasskeys ? "🌿" : "✉️"}</div>
          <h1 className="title">アカウントに続ける</h1>
          <p className="subtitle">
            Passkey、Google、メール認証に対応しています。
            <br />
            初めての場合はメール認証後にアカウントを作成します。
          </p>

          <div className="error-message" role="alert">{errorMessage}</div>

          {step === "entry" ? (
            <AuthEntryStep
              email={email}
              passkeyPending={passkeyPending}
              sendingCode={sendingCode}
              supportsPasskeys={supportsPasskeys}
              onEmailChange={setEmail}
              onGoogleLogin={() => {
                window.location.href = buildGoogleLoginUrl();
              }}
              onPasskeyLogin={() => {
                void handlePasskeyLogin();
              }}
              onSendCode={() => {
                void handleSendCode();
              }}
            />
          ) : null}

          {step === "code" ? (
            <AuthCodeStep
              authCode={authCode}
              verifyingCode={verifyingCode}
              onAuthCodeChange={setAuthCode}
              onBack={() => {
                setAuthCode("");
                setErrorMessage("");
                setStep("entry");
              }}
              onVerifyCode={() => {
                void handleVerifyCode();
              }}
            />
          ) : null}

          {step === "passkey" ? (
            <AuthPasskeyStep
              emailAuthFlow={emailAuthFlow}
              passkeyPending={passkeyPending}
              passkeySetupProvider={passkeySetupProvider}
              onLater={() => scheduleRedirect()}
              onRegisterPasskey={() => {
                void handlePasskeyRegistration();
              }}
            />
          ) : null}
        </div>

        <AuthMessageModal
          isModalClosing={isModalClosing}
          message={modalMessage}
          onHide={hideModal}
        />
      </div>

      <AuthGatewayGlobalStyles fontFamily={authHeadingFont.style.fontFamily} />
    </>
  );
}
