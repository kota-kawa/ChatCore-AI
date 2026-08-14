import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 最終CTA。閲覧はログイン不要なので、まず一覧を見てもらう導線を主役にする
// Final CTA. Reading needs no account, so browsing the feed is the primary action
export function PromptShareLpFinalCta() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="lp-final-cta">
      <div className="lp-container lp-final-cta__inner">
        <h2 className="lp-final-cta__title">
          {isEn ? (
            <>Look at what other people are already using.</>
          ) : (
            <>
              まずは、ほかの人が
              <br className="lp-br-sp" />
              使っているものを見る。
            </>
          )}
        </h2>
        <p className="lp-final-cta__note">
          {isEn
            ? "The feed is open without an account. Sign up only when you want to post, comment, or use a prompt in chat."
            : "一覧はアカウントなしで見られます。投稿・コメント・「チャットで使う」を試したくなったら、そのとき登録してください。"}
        </p>
        <Link href="/prompt_share" className="lp-btn lp-btn--inverse lp-btn--large">
          {isEn ? "Browse public prompts" : "公開プロンプトを探す"}
        </Link>
      </div>
    </section>
  );
}
