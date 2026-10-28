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
      if (!DemoLoginResponseSchema.safeParse(payload).success) {
        throw new Error(t("auth.demoFailed"));
      }
      onSuccess();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("auth.demoFailed"));
      setPending(false);
    }
  };

  return { code, setCode, pending, error, submit };
}
