// デモコードによるログイン処理（入力値・通信中・エラー）を管理するフック。/api/auth/demo-login を呼ぶ。
// Hook that manages demo-code sign-in state (input, pending, error) by calling /api/auth/demo-login.
import { useState } from "react";

import { useTranslation } from "../../../../contexts/locale_context";
import { resilientFetch } from "../../../../scripts/core/resilient_fetch";
import { fetchJsonOrThrow } from "../../../../scripts/core/runtime_validation";
import { DemoLoginResponseSchema } from "../../../../types/generated/api_schemas";

// デモコードでのログインを管理するフック。成功したら onSuccess を呼ぶ（遷移は呼び出し側が決める）。
// Hook that manages signing in with a demo code; calls onSuccess afterwards (the caller decides the navigation).
export function useDemoLogin(onSuccess: () => void) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    const trimmedCode = code.trim();
    if (!trimmedCode) {
      setError(t("auth.demoCodeRequired"));
      return;
    }
    setError("");
    setPending(true);
    try {
      // 401（無効・終了・停止）と 429（試行制限）はサーバーの文言をそのまま見せる
      // Show the server's own message for 401 (wrong / ended / revoked) and 429 (rate limited)
      const { payload } = await fetchJsonOrThrow<unknown>(
        "/api/auth/demo-login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: trimmedCode })
        },
        { fetchImpl: resilientFetch, defaultMessage: t("auth.demoFailed") }
      );
      // 成功レスポンスの形が想定と違う場合はログイン成功として扱わない
      // Do not treat the login as successful when the response shape is not what we expect
      if (!DemoLoginResponseSchema.safeParse(payload).success) {
        throw new Error(t("auth.demoFailed"));
      }
      onSuccess();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("auth.demoFailed"));
      // 失敗時だけ pending を戻す。成功時は true のままにして、遷移が終わるまで再送信できないようにする
      // Reset pending only on failure; on success it stays true so the form cannot be resubmitted before the navigation finishes
      setPending(false);
    }
  };

  return { code, setCode, pending, error, submit };
}
