import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 最終CTA。ログインなしでも送れるので、まず1通試してもらう導線を主役にする
// Final CTA. Sending works without an account, so trying one message is the primary action
export function ChatLpFinalCta() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="lp-final-cta" aria-labelledby="cslp-cta-heading">
      <div className="lp-container lp-final-cta__inner">
        <h2 id="cslp-cta-heading" className="lp-final-cta__title">
          {isEn ? (
            <>Send one message and see what comes back.</>
          ) : (
            <>
              まずは1通送って、
              <br className="lp-br-sp" />
              返ってくる形を見る。
            </>
          )}
        </h2>
        <p className="lp-final-cta__note">
          {isEn
            ? "Sending works without an account, though the daily count is capped and nothing is kept. Sign up when you want history, your own tasks, memos, and share links."
            : "送るだけならアカウントは要りません（1日の回数に上限があり、履歴は残りません）。履歴・自分のタスク・メモ保存・共有リンクが欲しくなったら、そのとき登録してください。"}
        </p>
        <Link href="/" className="lp-btn lp-btn--inverse lp-btn--large">
          {isEn ? "Open the chat" : "チャットを開く"}
        </Link>
      </div>
    </section>
  );
}
