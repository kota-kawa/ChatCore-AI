// 最終CTAセクション（深緑の締めのブロック）
// Final CTA section (deep-green closing block)
export function LpFinalCta() {
  const { locale, t } = useTranslation();
  return (
    <section className="lp-final-cta">
      <div className="lp-container lp-final-cta__inner">
        <h2 className="lp-final-cta__title">
          {locale === "en" ? "Turn today’s questions" : "今日の調べものから、"}
          <br className="lp-br-sp" />
          {locale === "en" ? "into useful knowledge." : "始めてみませんか。"}
        </h2>
        <p className="lp-final-cta__note">{locale === "en" ? "Create an account in minutes. Chat Core is free to use." : "登録は数分で完了します。いつでも無料で使えます。"}</p>
        <a href="/register" className="lp-btn lp-btn--inverse lp-btn--large">
          {t("lp.start")}
        </a>
      </div>
    </section>
  );
}

// フッター（既存ページへのリンクとコピーライト）
// Footer (links to existing pages and copyright)
export function LpFooter() {
  const { locale, t } = useTranslation();
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer__inner">
        <p className="lp-footer__brand">ChatCore-AI</p>
        <nav className="lp-footer__nav" aria-label={locale === "en" ? "Site links" : "サイト内リンク"}>
          <a href="/">{t("nav.chat")}</a>
          <a href="/prompt_share">{t("nav.promptShare")}</a>
          <a href="/memo">{t("nav.memo")}</a>
          <a href="/help">{t("nav.help")}</a>
          <a
            href="https://docs.google.com/forms/d/e/1FAIpQLSe2QqacIPAnKeZtFGHxb61YYjVjrrixcIsV2wDPoyFMXG-F2w/viewform?usp=publish-editor"
            target="_blank"
            rel="noopener noreferrer"
          >
            {locale === "en" ? "Contact" : "お問い合わせ"}
          </a>
          <a href="/terms">{locale === "en" ? "Terms" : "利用規約"}</a>
          <a href="/privacy">{locale === "en" ? "Privacy" : "プライバシーポリシー"}</a>
          <a href="/login">{t("nav.login")}</a>
          <a href="/register">{locale === "en" ? "Sign up" : "新規登録"}</a>
        </nav>
        <p className="lp-footer__copyright">© {new Date().getFullYear()} Chat Core</p>
      </div>
    </footer>
  );
}
import { useTranslation } from "../../contexts/locale_context";
