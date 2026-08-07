import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 最終CTAセクション（深緑の締めのブロック）
// Final CTA section (deep-green closing block)
export function LpFinalCta() {
  const { locale, t } = useTranslation();
  return (
    <section className="lp-final-cta">
      <div className="lp-container lp-final-cta__inner">
        {/* 日本語は狭い画面向けに改行位置を指定する。英語は単語間の空白が必要なため
            改行を入れず自然な折り返しに任せる
            Japanese pins the line break for narrow screens. English needs word spacing,
            so it wraps naturally instead */}
        <h2 className="lp-final-cta__title">
          {locale === "en" ? "Turn today’s questions into useful knowledge." : (
            <>
              今日の調べものから、
              <br className="lp-br-sp" />
              始めてみませんか。
            </>
          )}
        </h2>
        <p className="lp-final-cta__note">{locale === "en" ? "Create an account in minutes. Chat Core is free to use." : "登録は数分で完了します。いつでも無料で使えます。"}</p>
        <Link href="/register" className="lp-btn lp-btn--inverse lp-btn--large">
          {t("lp.start")}
        </Link>
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
          <Link href="/">{t("nav.chat")}</Link>
          <Link href="/prompt_share">{t("nav.promptShare")}</Link>
          <Link href="/memo">{t("nav.memo")}</Link>
          <Link href="/help">{t("nav.help")}</Link>
          <a
            href="https://docs.google.com/forms/d/e/1FAIpQLSe2QqacIPAnKeZtFGHxb61YYjVjrrixcIsV2wDPoyFMXG-F2w/viewform?usp=publish-editor"
            target="_blank"
            rel="noopener noreferrer"
          >
            {locale === "en" ? "Contact" : "お問い合わせ"}
          </a>
          <Link href="/terms">{locale === "en" ? "Terms" : "利用規約"}</Link>
          <Link href="/privacy">{locale === "en" ? "Privacy" : "プライバシーポリシー"}</Link>
          <Link href="/login">{t("nav.login")}</Link>
          <Link href="/register">{locale === "en" ? "Sign up" : "新規登録"}</Link>
        </nav>
        <p className="lp-footer__copyright">© {new Date().getFullYear()} Chat Core</p>
      </div>
    </footer>
  );
}
