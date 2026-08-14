import Link from "next/link";
import { useTranslation } from "../../contexts/locale_context";

// 最終CTA。メモの作成・閲覧にはログインが必要なので、メモ画面へ進む導線を主役にする
// Final CTA. Creating and reading memos needs an account, so opening the memo screen leads
export function MemoLpFinalCta() {
  const { locale } = useTranslation();
  const isEn = locale === "en";
  return (
    <section className="lp-final-cta">
      <div className="lp-container lp-final-cta__inner">
        <h2 className="lp-final-cta__title">
          {isEn ? (
            <>The answer you got today is worth keeping.</>
          ) : (
            <>
              今日もらった回答を、
              <br className="lp-br-sp" />
              手元に残しませんか。
            </>
          )}
        </h2>
        <p className="lp-final-cta__note">
          {isEn
            ? "Memos need a free account. Sign up with an email address or with Google, and the bookmark button under any chat answer starts working."
            : "メモの利用には無料アカウントが必要です。メールアドレスかGoogleで登録すれば、チャットの回答の下のブックマークのボタンがそのまま使えます。"}
        </p>
        <Link href="/memo" className="lp-btn lp-btn--inverse lp-btn--large">
          {isEn ? "Open memos" : "メモを開く"}
        </Link>
      </div>
    </section>
  );
}
