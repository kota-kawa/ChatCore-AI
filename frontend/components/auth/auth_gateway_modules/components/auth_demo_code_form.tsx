import type { FormEvent } from "react";

import { useTranslation } from "../../../../contexts/locale_context";

// デモコード入力フォームのprops型定義
// Props type definition for the demo code form
type AuthDemoCodeFormProps = {
  code: string;
  error: string;
  pending: boolean;
  onCodeChange: (value: string) => void;
  onSubmit: () => void;
};

// ログイン方法とは別の、デモコードをお持ちの方向けの控えめな入口
// A quiet, separate entry for people who hold a demo code
export function AuthDemoCodeForm({ code, error, pending, onCodeChange, onSubmit }: AuthDemoCodeFormProps) {
  const { t } = useTranslation();
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pending && code.trim()) onSubmit();
  };

  return (
    <section className="demo-code" aria-labelledby="demoCodeHeading">
      <h2 className="demo-code-heading" id="demoCodeHeading">{t("auth.demoHeading")}</h2>
      <p className="demo-code-lead">{t("auth.demoLead")}</p>
      <form className="demo-code-form" onSubmit={handleSubmit}>
        <label htmlFor="demoCode" className="email-label">{t("auth.demoCodeLabel")}</label>
        <input
          type="text"
          id="demoCode"
          name="demoCode"
          className="email-input"
          placeholder={t("auth.demoCodePlaceholder")}
          value={code}
          onChange={(event) => onCodeChange(event.target.value)}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={64}
          disabled={pending}
        />
        {error ? <div className="error-message" role="alert">{error}</div> : null}
        <button
          type="submit"
          className="ghost-btn demo-code-submit cc-press"
          disabled={pending || !code.trim()}
          aria-busy={pending}
        >
          {pending ? t("auth.demoSubmitting") : t("auth.demoSubmit")}
        </button>
      </form>
    </section>
  );
}
